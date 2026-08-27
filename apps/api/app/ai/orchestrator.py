"""AI 编排：引导对话、生成草稿、段落重写。"""

from collections.abc import AsyncIterator, Iterator

import asyncio

from langchain_core.messages import HumanMessage
from loguru import logger

from app.ai.context_assembler import (
    assemble_messages,
    build_system_prompt,
    build_turn_reminder,
    get_project_summaries,
    wrap_user_message,
)
from app.ai.llm_client import (
    astream_llm,
    extract_cached_tokens as _extract_cached_tokens,
    extract_reasoning,
    stream_llm,
)
from app.ai.section_prompts import get_section_prompt
from app.ai.tool_timeout import AGENT_LOOP_TOTAL_TIMEOUT
from app.models import Message, Section
from app.services.llm_config_service import ResolvedChatConfig


def stream_chat(
    db, section: Section, history: list[Message], user_input: str,
    *, llm_config: ResolvedChatConfig,
) -> Iterator[str]:
    """引导对话：流式回复用户问题。"""
    summaries = get_project_summaries(db, section.project_id)
    knowledge = _retrieve_knowledge(db, section, user_input)
    messages = assemble_messages(section, history, user_input, summaries, knowledge)
    yield from stream_llm(messages, llm_config=llm_config)


def stream_generate(
    db, section: Section, history: list[Message],
    *, llm_config: ResolvedChatConfig,
) -> Iterator[str]:
    """生成草稿：基于对话历史生成本章草稿（Markdown 流式）。"""
    summaries = get_project_summaries(db, section.project_id)
    knowledge = _retrieve_knowledge(db, section, section.title)
    sp = get_section_prompt(section.key)
    messages = assemble_messages(
        section, history, project_summaries=summaries, knowledge_context=knowledge
    )
    instruction = (
        f"请根据以上对话内容，整理生成本章节【{section.title}】的草稿。"
        f"要求：{sp.output_format}。用 Markdown 格式输出。"
    )
    messages.append(HumanMessage(content=instruction))
    yield from stream_llm(messages, llm_config=llm_config)


def _retrieve_knowledge(db, section: Section, query: str) -> list[dict] | None:
    """检索用户知识库（RAG）。旧 skill 开关已删除，Task 10 改造为 @tool。临时返回 None。"""
    return None


def stream_rewrite(
    section: Section, selected_text: str, instruction: str,
    *, llm_config: ResolvedChatConfig,
) -> Iterator[str]:
    """段落重写：基于选中文字 + 指令，流式输出重写结果。"""
    from langchain_core.messages import SystemMessage

    sp = get_section_prompt(section.key)
    system = (
        f"你是专利交底书撰写助手。当前章节：【{section.title}】（{sp.goal}）。"
        f"用户选中了一段文字，请按指令重写。保持 Markdown 格式。"
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"原文：\n{selected_text}\n\n指令：{instruction}"),
    ]
    yield from stream_llm(messages, llm_config=llm_config)


def _section_owner(db, section: Section):
    """取 section 所属项目的 user_id（用于 skill 可见性）。

    build_agent 需要 user_id 来限定 personal skill 可见范围 + RAG 检索范围。
    """
    from sqlalchemy import select

    from app.models import Project

    project = db.scalar(select(Project).where(Project.id == section.project_id))
    return project.user_id if project else None


def build_generate_instruction(section: Section) -> str:
    """[S4-2] 构造 generate 草稿指令（含 CoT 分步思考引导）。

    此前 instruction 是端到端的「请整理生成草稿」，模型直接吐内容，容易：
    - 漏掉前文章节的呼应（如方案没对准技术问题）
    - 漏覆盖 completion_criteria 的维度（如只写结构没写流程）
    - 与前文术语不一致

    CoT（Chain-of-Thought）引导模型在生成前分步思考：回顾→梳理维度→检查一致性→输出。
    注意：CoT 是引导模型【内部推理】，指令明确要求只输出最终草稿，
    不把思考过程展示给用户（草稿是给用户看的成品，不是推理 trace）。

    Args:
        section: 当前要生成草稿的章节。

    Returns:
        含 CoT 引导的指令字符串，作为 messages 的最后一条 user 消息。
    """
    sp = get_section_prompt(section.key)
    return (
        f"请根据对话历史，整理生成本章节【{section.title}】的草稿。"
        f"格式要求：{sp.output_format}，用 Markdown 输出。"
        f"达标判定：{sp.completion_criteria}\n\n"
        f"思考步骤（【只输出最终草稿，不要输出思考过程】）：\n"
        f"1. 回顾对话中已确定的技术要点，以及前文章节（技术问题/技术方案等）的关键信息\n"
        f"2. 梳理本章应覆盖的维度（按上述达标判定）\n"
        f"3. 检查与「技术问题」「技术方案」等前文章节的一致性（术语、表述、不矛盾）\n"
        f"4. 输出最终 Markdown 草稿"
    )


def build_revise_instruction(db, section: Section, directives: list[str]) -> str:
    """[T2 spec §3.1.4] 构造章节针对性修订指令（评估建议 → 最小改动修订）。

    与 build_generate_instruction 的关键差异：
    - generate 从零写稿（吸收对话意图）；revise 对已成文内容做定点修改，
      现文 + 建议已自包含，不嵌对话历史（spec D2）。
    - 现有内容用 _tiptap_to_markdown 转换后嵌入——与 /diff 端点同款转换器，
      LLM 看到的原文 = diff 比较的原文，从源头减少格式伪 hunk（spec §7 R2）。
    - 术语优先级链（spec D13）：术语表 > 沿用现状 > 最小改动——现文含变体时
      指令明确「按标准术语修正（即使修订指令未提及）」，与 system prompt 的
      项目术语表层一致，不产生矛盾指令。
    """
    from app.services.export_service import _tiptap_to_markdown

    current_md = _tiptap_to_markdown(db, section.content) if section.content else ""
    numbered = "\n".join(f"{i}. {d}" for i, d in enumerate(directives, 1))
    return (
        f"你要对章节【{section.title}】执行一次针对性修订。\n\n"
        f"# 修订指令（逐条落实，全部处理）\n"
        f"{numbered}\n\n"
        f"# 修订约束（必须遵守）\n"
        f"- 最小改动原则：只修改与修订指令相关的段落；未涉及的段落保持原文，"
        f"禁止重排结构、调整编号、改写无关句子。\n"
        f"- 逐字保留：未涉及段落连同其格式（标题层级、列表标记、空行、表格结构）"
        f"原样输出，不做任何风格化改写。\n"
        f"- 术语：若上文中给出了本项目术语表，以其为准——正文中不符合术语表的"
        f"用法一并修正为标准术语（即使修订指令未提及）；未给术语表时，沿用全文"
        f"已确立的用法，不引入新的同义表述。\n"
        f"- 若某条指令与章节现状冲突（如建议修改的内容不存在），在相应位置合理落实，"
        f"不虚构不相关内容。\n"
        f"- 输出修订后的整章 Markdown（完整正文，不要输出 diff、解释或前后对照）。\n\n"
        f"# 现有章节内容（你的输出必须与它逐段对齐，格式风格保持一致）\n"
        f"{current_md}"
    )


def _extract_hitl_payload(data) -> dict | None:
    """从 on_interrupt 事件 data 提取 HITL 请求（{"actions": [{name,args,description}]}）。

    langgraph 各版本对 on_interrupt 的 data 包裹层级不统一（GraphInterruptEvent /
    interrupts 元组 / 直接 HITLRequest dict 都可能出现），按层探测；解析失败返回
    None 并打 debug 日志（不打断主流，前端拿不到 interrupt 事件时退化成普通结束）。
    """
    candidates = list(data.values()) if isinstance(data, dict) else [data]
    if isinstance(data, dict):
        candidates = [data.get("event"), data.get("interrupt"), *candidates]
    for cand in candidates:
        # GraphInterruptEvent.interrupts → tuple[Interrupt]；Interrupt.value = HITLRequest
        interrupts = getattr(cand, "interrupts", None)
        if interrupts:
            cand = interrupts
        if not isinstance(cand, (tuple, list)):
            continue
        for intr in cand:
            value = getattr(intr, "value", None) or intr
            if isinstance(value, dict) and "action_requests" in value:
                return {"actions": [
                    {
                        "name": r.get("name", ""),
                        "args": r.get("args", {}),
                        "description": r.get("description", ""),
                    }
                    for r in value["action_requests"] if isinstance(r, dict)
                ]}
    logger.debug("on_interrupt 事件 data 未能解析 HITL payload: %r", data)
    return None


async def _astream_agent_events(
    agent, input_value, *, thread_id: str | None,
    usage_sink: dict | None = None, timeout_notice: str,
    token_budget: int | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """共享 agent loop 事件循环（chat/generate/resume/revise 四路复用）。

    yield (kind, payload)：
      - ("token", str) / ("thinking", str) / ("tool_call", dict) / ("tool_result", dict)
      - ("interrupt", {"actions": [...]})：HITL 工具确认请求（层 3 总超时同样适用）

    input_value：常规跑传 {"messages": [...]}；续跑传 None（checkpoint 续跑）或
    Command(resume=...)（HITL 决策恢复）。

    token_budget（A-4）：单 turn 累计 token 上限（prompt+completion 逐步累加，
    记入 usage_sink["turn_total"]）。超限时 yield 一条收尾提示、置
    usage_sink["_budget_capped"]=True 并停止消费后续事件——温和熔断而非抛错。
    None / <=0 表示关闭。
    """
    try:
        async with asyncio.timeout(AGENT_LOOP_TOTAL_TIMEOUT):
            config = {"configurable": {"thread_id": thread_id}} if thread_id else None
            async for event in agent.astream_events(input_value, version="v2", config=config):
                evt = event["event"]
                if evt == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    # 先透传思考过程（reasoning），再透传正文 token。思考片段在正文之前产出
                    # （GLM-4.x 思考模型先 think 后答），前端据此展示可折叠思考块。
                    reasoning = extract_reasoning(chunk)
                    if reasoning:
                        yield ("thinking", reasoning)
                    if chunk and chunk.content:
                        yield ("token", chunk.content)
                    # P0-2：捕获 token 用量。usage_metadata 仅在 stream_usage=True 时由
                    # provider 在最后一块 chunk 回填（见 agent.py 的 get_llm(stream_usage=True)）。
                    # agent loop 多步调用（先 tool_call 再生成），on_chat_model_stream 会触发
                    # 多次，故 completion 用累加而非覆盖；prompt 取 last-wins（每次调用的
                    # input_tokens 包含完整上下文，最后一次最准）。
                    _usage = getattr(chunk, "usage_metadata", None) if chunk else None
                    if _usage and usage_sink is not None:
                        usage_sink["prompt"] = _usage.get("input_tokens")
                        usage_sink["completion"] = (
                            usage_sink.get("completion", 0) + (_usage.get("output_tokens") or 0)
                        )
                        # A-3：前缀缓存命中数（last-wins，与 prompt 同语义）
                        cached = _extract_cached_tokens(_usage)
                        if cached is not None:
                            usage_sink["cached"] = cached
                        # A-4：单 turn 累计（真实计费口径——每步都为全上下文付费）
                        step_total = (_usage.get("input_tokens") or 0) + (_usage.get("output_tokens") or 0)
                        usage_sink["turn_total"] = usage_sink.get("turn_total", 0) + step_total
                        if (
                            token_budget and token_budget > 0
                            and usage_sink["turn_total"] > token_budget
                            and not usage_sink.get("_budget_capped")
                        ):
                            usage_sink["_budget_capped"] = True
                            logger.warning(
                                "_astream_agent_events: 触达单 turn token 预算 %s（累计 %s），温和收束",
                                token_budget, usage_sink["turn_total"],
                            )
                            yield ("token",
                                   "\n\n[系统提示：本轮生成已达到 token 预算上限，已提前收束。"
                                   "如需继续请重试或联系管理员调整预算。]")
                            break
                elif evt == "on_tool_start":
                    yield ("tool_call", {
                        "name": event.get("name", ""),
                        "args": event.get("data", {}).get("input", {}),
                    })
                elif evt == "on_tool_end":
                    result = event.get("data", {}).get("output")
                    # result 可能是各种类型（str / ToolMessage / dict），统一转 str 截断
                    result_str = str(result)[:500] if result is not None else ""
                    yield ("tool_result", {
                        "name": event.get("name", ""),
                        "result": result_str,
                    })
                elif evt == "on_interrupt":
                    info = _extract_hitl_payload(event.get("data"))
                    if info is not None:
                        yield ("interrupt", info)
    except TimeoutError:
        logger.warning("_astream_agent_events: agent loop 总超时（%ss），强制结束", AGENT_LOOP_TOTAL_TIMEOUT)
        yield ("token", timeout_notice)


def _prepare_turn_layers(db, section: Section, *, user_id,
                         user_input: str | None, intent: str | None) -> tuple[str, str]:
    """装配 agent 路线的两段上下文（批次 A 决策 D1）。

    返回 (system_prompt, reminder)：
    - system_prompt：静态骨架（build_system_prompt），传给 build_agent 的
      system_prompt_override——跨轮字节稳定，供应商前缀缓存的锚。
    - reminder：逐轮易变快照（build_turn_reminder），含知识库预检索结果。
      由调用方 wrap 进当轮消息尾部；resume 场景经 checkpoint 已包裹的
      历史消息自然还原首跑上下文，无需重建检索。

    检索/装配失败静默降级不阻断（与其他层一致）。
    """
    from app.ai.context_assembler import _retrieve_knowledge_for_section

    knowledge_context = _retrieve_knowledge_for_section(
        db, user_id, section, user_input=user_input,
    )
    system_prompt = build_system_prompt(db, section)
    try:
        reminder = build_turn_reminder(
            db, section, knowledge_context=knowledge_context,
            user_input=user_input, intent=intent,
        )
    except Exception:  # noqa: BLE001 — 快照装配失败降级空串，绝阻断主对话
        logger.exception("build_turn_reminder 失败，降级注入空易变块")
        db.rollback()
        reminder = ""
    return system_prompt, reminder


def _apply_reminder(messages: list[dict], reminder: str) -> None:
    """把当轮易变快照包进 messages 末条（决策 D1）。

    末条恒为当前轮的 user 输入/generate 指令（compress_history 契约保证）。
    防御：末条形状不符时跳过注入并告警，绝不炸主对话。
    """
    if not messages or not reminder:
        return
    last = messages[-1]
    if isinstance(last, dict) and last.get("role") == "user":
        last["content"] = wrap_user_message(last.get("content") or "", reminder)
    else:
        logger.warning("_apply_reminder: 末条非 user dict（%s），跳过快照注入", type(last).__name__)


async def astream_chat(
    db, section: Section, history: list[Message], user_input: str,
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
    meta_sink: dict | None = None,
    thread_id: str | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """异步引导对话：委托 deepagents agent loop（路线 B）。

    yield (kind, payload) 元组（Task 23：agent loop 透明化）：
      - ("token", str)：文本 token
      - ("thinking", str)：模型思考过程片段（GLM/DeepSeek 推理模型的 reasoning）
      - ("tool_call", {"name", "args"})：agent 发起工具调用
      - ("tool_result", {"name", "result"})：工具返回
      - ("interrupt", {"actions": [...]})：HITL 工具确认请求（agent 停在该断点等决策）

    agent.astream_events 暴露 token + thinking + tool_call/tool_result 事件，本函数
    全部透传给 SSE 层（thinking 由 ReasoningChatOpenAI 回填进 chunk.additional_kwargs，
    extract_reasoning 读出）。

    注意：usage_sink 在 agent loop 路径下**会被填充**——P0-2 修复后，on_chat_model_stream
    分支捕获 chunk 的 usage_metadata（agent.py 的 get_llm(stream_usage=True) 已开启回填）。
    agent loop 多步调用时 completion 累加，prompt 取 last-wins。旧 astream_llm 路径
    （astream_rewrite 仍在用）也正确填充 usage_sink。
    """
    from app.ai.agent import build_agent
    from app.ai.checkpoint import get_checkpointer
    from app.ai.intent import classify_intent

    # [L1] 传 section + user_input，让 build_agent 装配静态 system prompt（spec §3.3.2）
    # [批次 A 决策 D1] 两段式装配：_prepare_turn_layers 返回（静态骨架, 易变快照）；
    # 骨架经 override 传给 build_agent；快照附着当轮消息尾部。
    # [S2-2] 规则层意图识别：draft/edit/info/guide → 意图指令随快照注入（LLM 兜底默认关）
    intent = classify_intent(user_input)
    logger.info("astream_chat: 开始构建 agent（intent=%s model=%s）", intent, llm_config.model)
    owner_id = _section_owner(db, section)
    system_prompt, reminder = _prepare_turn_layers(
        db, section, user_id=owner_id, user_input=user_input, intent=intent,
    )
    agent = await build_agent(db, llm_config=llm_config, user_id=owner_id,
                        section=section, user_input=user_input, intent=intent,
                        system_prompt_override=system_prompt,
                        checkpointer=get_checkpointer())
    logger.info("astream_chat: agent 构建完成，开始 agent loop")

    # [L2] 透传历史 + 当前用户输入，长历史先压缩（spec §3.3.2 + 压缩 spec）
    from app.ai.context_compactor import compress_history

    compressed, snapshot = await compress_history(
        history, user_input, llm_config, scene="chat"
    )
    if snapshot.triggered:
        # 用 loguru（项目既定日志出口；标准 logging 在本项目默认 WARNING+ 无 handler，info 会被静默）
        logger.info(
            "上下文压缩触发 (chat, section={}): reason={} {}→{}条 fallback={}",
            section.id, snapshot.reason, snapshot.original_count,
            snapshot.compressed_count, snapshot.fallback,
        )
    # 压缩观测透传：把 snapshot 写入 meta_sink，供 SSE 层记入 LLMCallLog.context_meta（spec §5.1）。
    if meta_sink is not None:
        meta_sink["context_meta"] = snapshot.to_dict()
    # compress_history 的契约：触发/降级路径已在末尾 append current_input；
    # 未触发路径只返回历史 dict，不含 current_input —— 这里补一次，保证末尾恒为当前输入。
    messages = compressed
    if not snapshot.triggered:
        messages.append({"role": "user", "content": user_input})
    # 决策 D1：易变快照附着当轮消息尾部。落库剥离自动成立——DB 存原始输入，
    # 注入只发生在发送侧；历史回放永远是无快照的原文。
    _apply_reminder(messages, reminder)

    from app.services.agent_budget_service import get_turn_token_budget
    async for item in _astream_agent_events(
        agent, {"messages": messages}, thread_id=thread_id, usage_sink=usage_sink,
        timeout_notice="\n\n[系统提示：回复生成超时，已中止。请重试或简化问题。]",
        token_budget=get_turn_token_budget(db),
    ):
        yield item


async def astream_generate(
    db, section: Section, history: list[Message],
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
    meta_sink: dict | None = None,
    thread_id: str | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """异步生成草稿：委托 deepagents agent loop（路线 B）。

    yield (kind, payload) 元组（Task 23：agent loop 透明化）：
      - ("token", str)：文本 token
      - ("thinking", str)：模型思考过程片段（GLM/DeepSeek 推理模型的 reasoning）
      - ("tool_call", {"name", "args"})：agent 发起工具调用
      - ("tool_result", {"name", "result"})：工具返回

    agent.astream_events 暴露 token + thinking + tool_call/tool_result 事件，本函数
    全部透传给 SSE 层（thinking 由 ReasoningChatOpenAI 回填进 chunk.additional_kwargs，
    extract_reasoning 读出）。

    注意：usage_sink 在 agent loop 路径下**会被填充**——P0-2 修复后，on_chat_model_stream
    分支捕获 chunk 的 usage_metadata（agent.py 的 get_llm(stream_usage=True) 已开启回填）。
    agent loop 多步调用时 completion 累加，prompt 取 last-wins。旧 astream_llm 路径
    （astream_rewrite 仍在用）也正确填充 usage_sink。
    """
    from app.ai.agent import build_agent

    # [L1] 传 section + user_input，让 build_agent 装配动态 system prompt（spec §3.3.1）
    # generate 场景无新输入，用 history 最后一条 user message 作为记忆检索信号
    # （比章节标题强：用户刚聊的内容更可能关联其偏好/事实记忆）。
    gen_query = next(
        (m.content for m in reversed(history) if m.role == "user"), None
    )
    # [S2-2] generate 场景无新输入，意图恒为「代写草稿」——直接传 draft（比让规则层猜更准）
    # [T2 探针坐实 2026-08-17] checkpointer 显式 None：generate 无 thread_id（config=None），
    # langgraph 入口级要求「有 checkpointer 必须有 configurable」（pregel/main.py:2589）——
    # 传 checkpointer 时 generate 在 PG 环境（checkpointer 初始化成功）下每次调用都抛
    # ValueError（test_langgraph_probe.py）。generate 无 message、无 resume 能力，
    # checkpoint 零收益纯隐患，去除。
    # [批次 A 决策 D1] 两段式装配（同 astream_chat）：generate 为单发无跨轮前缀收益，
    # 但统一同一装配路径、不做分支——静态骨架走 override，快照附指令尾部。
    gen_query = next(
        (m.content for m in reversed(history) if m.role == "user"), None
    )
    # [S2-2] generate 场景无新输入，意图恒为「代写草稿」——直接传 draft（比让规则层猜更准）
    # [T2 探针坐实 2026-08-17] checkpointer 显式 None：generate 无 thread_id（config=None），
    # langgraph 入口级要求「有 checkpointer 必须有 configurable」（pregel/main.py:2589）——
    # 传 checkpointer 时 generate 在 PG 环境（checkpointer 初始化成功）下每次调用都抛
    # ValueError（test_langgraph_probe.py）。generate 无 message、无 resume 能力，
    # checkpoint 零收益纯隐患，去除。
    owner_id = _section_owner(db, section)
    system_prompt, reminder = _prepare_turn_layers(
        db, section, user_id=owner_id, user_input=gen_query, intent="draft",
    )
    agent = await build_agent(db, llm_config=llm_config, user_id=owner_id,
                        section=section, user_input=gen_query, intent="draft",
                        system_prompt_override=system_prompt,
                        checkpointer=None)
    # [S4-2] 用 build_generate_instruction 构造含 CoT 分步思考的指令
    instruction = build_generate_instruction(section)

    # [L2] 透传历史，长历史先压缩，再 append generate 指令（压缩 spec）
    from app.ai.context_compactor import compress_history

    compressed, snapshot = await compress_history(
        history, instruction, llm_config, scene="generate"
    )
    if snapshot.triggered:
        logger.info(
            "上下文压缩触发 (generate, section={}): reason={} {}→{}条",
            section.id, snapshot.reason, snapshot.original_count, snapshot.compressed_count,
        )
    # 压缩观测透传：把 snapshot 写入 meta_sink，供 SSE 层记入 LLMCallLog.context_meta（spec §5.1）。
    if meta_sink is not None:
        meta_sink["context_meta"] = snapshot.to_dict()
    # compress_history 的契约：触发/降级路径已在末尾 append instruction；
    # 未触发路径只返回历史 dict，不含 instruction —— 这里补一次，保证末尾恒为 generate 指令。
    messages = compressed
    if not snapshot.triggered:
        messages.append({"role": "user", "content": instruction})
    _apply_reminder(messages, reminder)

    from app.services.agent_budget_service import get_turn_token_budget
    async for item in _astream_agent_events(
        agent, {"messages": messages}, thread_id=thread_id, usage_sink=usage_sink,
        timeout_notice="\n\n[系统提示：草稿生成超时，已中止。请重试。]",
        token_budget=get_turn_token_budget(db),
    ):
        yield item


async def build_resume_agent(
    db, section: Section, *, llm_config: ResolvedChatConfig, user_input: str | None = None,
):
    """构建与 astream_chat 同参的 agent（供 resume 端点先 aget_state 判可续性后复用同一实例）。

    user_input 传原 turn 的用户消息内容——system prompt / 记忆检索 / 意图识别
    尽量还原首跑时的装配上下文（resume 不重发 input，但每步 model call 仍会
    用到 system prompt）。
    """
    from app.ai.agent import build_agent
    from app.ai.checkpoint import get_checkpointer
    from app.ai.intent import classify_intent

    return await build_agent(
        db, llm_config=llm_config, user_id=_section_owner(db, section),
        section=section, user_input=user_input, intent=classify_intent(user_input or ""),
        checkpointer=get_checkpointer(),
    )


async def astream_resume(
    db, section: Section, *, llm_config: ResolvedChatConfig, thread_id: str,
    user_input: str | None = None,
    decision: str | None = None, decision_message: str | None = None,
    usage_sink: dict | None = None,
    agent=None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """续跑一个中断/未完成的 turn（Checkpoint 红利：断点恢复）。

    input 语义（langgraph 1.2.9 已核实 _loop.py 的 is_resuming 判定）：
    - None：从 checkpoint 续跑——崩溃/断连的 turn，channel_versions 非空即续跑，
      被中断的节点**从头重放**（含整段重流其 token）
    - Command(resume={"decisions": [...]})：HITL 中断恢复。decisions 与
      action_requests 等长（HITLRequest 契约，见 langchain HumanInTheLoopMiddleware）；
      {"type": "approve"} 放行 / {"type": "reject", "message": ...} 拒绝并让
      agent 收到 error ToolMessage 后继续生成

    agent 可由调用方预先构建（resume 端点要用同一实例 aget_state 检查可续性，
    避免重复装配）；None 时现场构建（等价 build_resume_agent）。
    """
    if agent is None:
        agent = await build_resume_agent(db, section, llm_config=llm_config, user_input=user_input)
    input_value = None
    if decision:
        from langgraph.types import Command

        d: dict = {"type": decision}
        if decision_message:
            d["message"] = decision_message
        input_value = Command(resume={"decisions": [d]})
    async for item in _astream_agent_events(
        agent, input_value, thread_id=thread_id, usage_sink=usage_sink,
        timeout_notice="\n\n[系统提示：续跑超时，已中止。可再次点击「继续」。]",
    ):
        yield item


async def collect_final_answer(agent, thread_id: str) -> str | None:
    """turn 完成后从 checkpoint 权威重建 assistant 全文。

    双真源约定下 messages 表是 canonical、checkpoint 是 transient——这里只借
    checkpoint 把「跨节点全文」一次性取齐：崩溃续跑时被中断的节点会整段重放，
    若直接拼接「DB 半截 + 续跑流」会产生重复前缀，故完成时以 state 重建为准
    （拼接所有非空 AIMessage.content，与 SSE 累积语义一致）。
    任何失败返回 None（调用方退回拼接值），不影响主流程。
    """
    try:
        from langchain_core.messages import AIMessage

        state = await agent.aget_state({"configurable": {"thread_id": thread_id}})
        msgs = (state.values or {}).get("messages") or []
        parts = [m.content for m in msgs if isinstance(m, AIMessage) and m.content]
        return "".join(parts) or None
    except Exception as e:  # noqa: BLE001 — fail-open，退回拼接值
        logger.warning("collect_final_answer 失败，退回拼接值: %s", e)
        return None


async def astream_revise(
    db, section: Section, directives: list[str],
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """章节针对性修订（T2 spec §3.1.2）：建议 directives → 流式修订稿（Markdown）。

    与 astream_generate 的三点差异（spec D2）：
    - **不传 checkpointer（显式 None）**：探针坐实 config=None + checkpointer 会
      入口级 ValueError（test_langgraph_probe.py）；revise 无 resume 能力，
      checkpoint 零收益，interrupt_on 随 checkpointer=None 一并禁用（工具直通）。
    - **不带聊天历史、不 compress_history**：generate 需吸收对话意图从零写稿；
      revise 针对已成文内容定点修改，现文 + 建议自包含，历史只引入无关噪音。
    - **不落库**：产出候选稿，全文经 done 事件返回，由前端走 /diff + apply-diff
      人工审核应用（spec D8：不提供跳过审核的路径）。

    yield (kind, payload) 与 astream_generate 同协议（token/thinking/tool_call/
    tool_result；interrupt 不会出现——已禁用）。
    """
    from app.ai.agent import build_agent

    # [批次 A 决策 D1] 与 chat/generate 同一两段式装配：静态骨架走 override，
    # 术语表/已写章节/记忆等易变层随修订指令尾部注入（revise 不带聊天历史，
    # 这些层正是它保持术语一致所需的全部上下文）。
    owner_id = _section_owner(db, section)
    system_prompt, reminder = _prepare_turn_layers(
        db, section, user_id=owner_id, user_input=None, intent="edit",
    )
    agent = await build_agent(db, llm_config=llm_config, user_id=owner_id,
                        section=section, user_input=None, intent="edit",
                        system_prompt_override=system_prompt,
                        checkpointer=None)
    instruction = build_revise_instruction(db, section, directives)
    revise_messages = [{"role": "user", "content": instruction}]
    _apply_reminder(revise_messages, reminder)

    from app.services.agent_budget_service import get_turn_token_budget
    async for item in _astream_agent_events(
        agent, {"messages": revise_messages}, thread_id=None,
        usage_sink=usage_sink,
        timeout_notice="\n\n[系统提示：修订生成超时，已中止。可重新发起修订。]",
        token_budget=get_turn_token_budget(db),
    ):
        yield item


async def astream_rewrite(
    section: Section, selected_text: str, instruction: str,
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
) -> AsyncIterator[str]:
    """异步段落重写：基于选中文字 + 指令，流式输出重写结果。

    usage_sink 透传给 astream_llm（断链 C3：捕获 token 用量记入 LLMCallLog）。
    """
    from langchain_core.messages import SystemMessage

    sp = get_section_prompt(section.key)
    system = (
        f"你是专利交底书撰写助手。当前章节：【{section.title}】（{sp.goal}）。"
        f"用户选中了一段文字，请按指令重写。保持 Markdown 格式。"
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"原文：\n{selected_text}\n\n指令：{instruction}"),
    ]
    async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage_sink):
        yield token
