"""AI 编排：引导对话、生成草稿、段落重写。"""

from collections.abc import AsyncIterator, Iterator

import asyncio

from langchain_core.messages import HumanMessage
from loguru import logger

from app.ai.context_assembler import assemble_messages, get_project_summaries
from app.ai.llm_client import astream_llm, extract_reasoning, stream_llm
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

    # [L1] 传 section + user_input，让 build_agent 装配动态 system prompt（spec §3.3.2）
    # user_input 用于记忆检索（用户当前输入是最强语义信号，如「检查写作风格」→命中偏好记忆）
    # [S2-2] 规则层意图识别：draft/edit/info/guide → 注入对应行为指令（D1，LLM 兜底默认关）
    intent = classify_intent(user_input)
    logger.info("astream_chat: 开始构建 agent（intent=%s model=%s）", intent, llm_config.model)
    agent = await build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section),
                        section=section, user_input=user_input, intent=intent,
                        checkpointer=get_checkpointer())
    logger.info("astream_chat: agent 构建完成，开始 agent loop")

    # [L2] 透传历史 + 当前用户输入，长历史先压缩（spec §3.3.2 + 压缩 spec）
    from app.ai.context_compactor import compress_history

    compressed, snapshot = await compress_history(
        history, user_input, llm_config, scene="chat"
    )
    if snapshot.triggered:
        # 用 loguru（项目既定日志出口；标准 logging 在本项目默认 WARNING+无 handler，info 会被静默）
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

    # 层 3：agent loop 总超时兜底，防极端情况（多步工具 + 生成）无限循环
    try:
        async with asyncio.timeout(AGENT_LOOP_TOTAL_TIMEOUT):
            async for event in agent.astream_events(
                {"messages": messages},
                version="v2",
                config={"configurable": {"thread_id": thread_id}} if thread_id else None,
            ):
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
    except TimeoutError:
        logger.warning("astream_chat: agent loop 总超时（%ss），强制结束", AGENT_LOOP_TOTAL_TIMEOUT)
        yield ("token", "\n\n[系统提示：回复生成超时，已中止。请重试或简化问题。]")


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
    from app.ai.checkpoint import get_checkpointer

    # [L1] 传 section + user_input，让 build_agent 装配动态 system prompt（spec §3.3.1）
    # generate 场景无新输入，用 history 最后一条 user message 作为记忆检索信号
    # （比章节标题强：用户刚聊的内容更可能关联其偏好/事实记忆）。
    gen_query = next(
        (m.content for m in reversed(history) if m.role == "user"), None
    )
    # [S2-2] generate 场景无新输入，意图恒为「代写草稿」——直接传 draft（比让规则层猜更准）
    agent = await build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section),
                        section=section, user_input=gen_query, intent="draft",
                        checkpointer=get_checkpointer())
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

    # 层 3：agent loop 总超时兜底，防极端情况（多步工具 + 生成）无限循环
    try:
        async with asyncio.timeout(AGENT_LOOP_TOTAL_TIMEOUT):
            async for event in agent.astream_events(
                {"messages": messages},
                version="v2",
                config={"configurable": {"thread_id": thread_id}} if thread_id else None,
            ):
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
    except TimeoutError:
        logger.warning("astream_generate: agent loop 总超时（%ss），强制结束", AGENT_LOOP_TOTAL_TIMEOUT)
        yield ("token", "\n\n[系统提示：草稿生成超时，已中止。请重试。]")


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
