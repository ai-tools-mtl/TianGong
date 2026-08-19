"""项目初始化助手编排：对话引导 + 扳机落地建项目并生成 8 章初稿。

定位（详见 docs/superpowers/specs/2026-07-31-chatgpt-style-init-assistant-design.md）：
- ChatGPT 式独立对话页的助手，对话在项目创建前进行（顶层 init 会话，kind='init'）。
- ready 判断由系统侧基于维度覆盖率算（brief_dimensions.compute_coverage），不再靠 LLM
  自吐 [READY_TO_CREATE] 标记。用户按扳机 → 本模块建项目 + 填 8 章。

与 orchestrator.py 的区别：
- orchestrator 是 section 粒度（单章对话/生成），强依赖 build_system_prompt 的章节策略。
- init_orchestrator 是项目粒度：对话不绑定单 section（用 INIT_CHAT_SYSTEM_PROMPT / INIT_GENERATE_SYSTEM_PROMPT，
  分别服务对话引导与正文生成两条链路），generate 时一次性循环 8 章（用 astream_llm 纯生成，不走 agent loop）。

init chat 走 agent loop（build_init_agent → create_deep_agent，带 save_memory 工具），
与普通助手 astream_chat 同构（事件遍历 + tool_call/tool_result SSE 透传）。
模型不支持工具时降级回裸 astream_llm（见 astream_init_chat 的 try/except 分支）。
"""
from collections.abc import AsyncIterator

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.ai.llm_client import astream_llm, extract_reasoning
from app.ai.orchestrator import build_generate_instruction
from app.models import Conversation, Message, Section
from app.services.llm_config_service import ResolvedChatConfig
from app.services.seed_service import DEFAULT_STRUCTURE

# 8 章 key → title（与 seed_service.DEFAULT_STRUCTURE 同源，brief 摘要用）
_OUTLINE_TITLES = [(s["key"], s["title"]) for s in DEFAULT_STRUCTURE]

# ── 项目初始化助手 system prompt（裁剪自 context_assembler.SYSTEM_PROMPT）──
# 不绑定单 section；目标是引导用户把想法说清楚，为生成 8 章做准备。
# 写作规范浓缩自 assets/skills/ 下的内置 skill（patent-de-ai / patent-writing-quality /
# patent-effect-contrast）——让助手引导用户时即遵守这些规范。
#
# 拆成对话版 / 生成版两条：
# - 对话版走 agent loop，工具实际可调用 → 文案说明「可用工具」
# - 生成版走裸 astream_llm，不带工具（RAG 片段由系统自动注入上下文）→ 不提「可用工具」，
#   改说「相关知识库片段已注入」，避免模型干等一个它无法调用的工具入口。
_INIT_COMMON = """你是「天工」项目初始化助手。用户想新建一个专利交底书项目，但通常只有一个模糊的技术想法。你的任务是通过对话，帮用户把想法理清楚，为后续一键生成 8 章初稿做准备。

对话目标——逐步引导用户说清以下 5 个核心方面（不必一次问全，每轮聚焦一个方向，结合用户已说的内容追问）：
1. 技术领域：这个发明属于什么领域？解决哪类问题？
2. 现有技术及其缺点：目前怎么做？具体哪里不行？（这是关键——没有缺点，技术问题和有益效果都失去锚点）
3. 要解决的技术问题：本发明针对现有技术的哪个/哪些具体不足？每个问题应对准一个缺点。
4. 技术方案的大致轮廓：核心做法是什么？有哪些关键步骤/模块/组件？每个关键部分解决哪个子问题？
5. 关键特征与效果：相比现有方案，新在哪、好在哪？每个效果对应解决哪个缺点。

引导规则：
1. 用专业但通俗的中文，避免生硬法律术语
2. 引导用户补充真实技术细节，不要替用户编造数据或效果
3. 信息不足时主动追问；每轮聚焦一个方向，不要一次问全 5 个方面
4. 保持客观，不夸大技术效果
5. 回复简洁，每轮对话聚焦引导，不要长篇大论
6. 重点挖「现有技术缺点」——用户常直接跳到自己的方案，要引导他们先讲清现有技术是什么、哪里不足
7. 谈到效果时，主动追问依据：有没有实测数据？对比基线是什么？
   明确告诉用户「没有实测数据没关系，可以说复杂度对比或数据量差异，但请别凭空给绝对数值」。
   （生成期禁止臆测如「约 10μs」这类绝对值，所以引导时就要把依据类型问清楚）
8. 帮用户把「缺点、技术问题、有益效果」对应起来——例如「您说的这个效果，是针对哪个现有技术缺点的？」

写作规范（生成内容时也要遵守，此处作为对话引导的标尺）：
- 去 AI 味：禁用「更为关键的是」「换言之」「值得注意的是」等套话转折词；避免超长句和三连排比
- 英文术语首现必须带中文翻译，格式「中文译名（English Term）」
- 技术效果用「现有技术短板→本方案做法→量化差异」三段式，不臆测绝对数值
"""

# 对话引导版：走 agent loop，rag_search / save_memory 实际可调用
INIT_CHAT_SYSTEM_PROMPT = _INIT_COMMON + """
可用工具：
- save_memory：当用户透露跨项目稳定的画像信息（职业/专业水平/领域，如「我是做新能源的」「我是专利代理人」）
  或明确表达长期偏好（「以后都用这种写法」）时调用，用 memory_type="profile" 保存画像、默认保存偏好。
  临时性信息（如「我现在在写电池专利」）不要保存。
- rag_search：当用户的想法涉及具体技术领域、需要参考历史案例或已有交底书的写法/结构时调用，
  检索用户知识库。帮用户把想法讲清楚时，相关历史案例能提供有力的参照（如「这个领域的常见技术问题怎么表述」）。
  查询用技术关键词或问题描述。
"""

# 正文生成版：走裸 astream_llm，不带工具调用入口——知识库片段由系统自动检索后注入上下文
# （见 _retrieve_section_context）。此处不提「可用工具」，避免模型等待一个无法调用的工具。
INIT_GENERATE_SYSTEM_PROMPT = _INIT_COMMON + """
本章生成时，系统已根据对话要点自动检索用户知识库，命中的相关历史案例/已有交底书片段会作为
上下文注入（如存在）。请参考其写法与技术细节，但勿照搬，需结合本项目实际。
"""


async def _build_init_chat_messages(
    history: list[Message], user_input: str, llm_config,
    *, meta_sink: dict | None = None,
) -> list:
    """装配 init chat 消息：INIT_CHAT_SYSTEM_PROMPT + 压缩后历史。

    历史先经 compress_history 压缩（压缩 spec），再转 LangChain 消息类型。
    meta_sink 非空时写入压缩 snapshot，供调用方记入 LLMCallLog.context_meta。

    仅降级路径（裸 astream_llm）使用此函数；agent loop 主路径直接用 compress_history
    的 dict 输出喂给 agent.astream_events。
    """
    from loguru import logger
    from app.ai.context_compactor import compress_history

    compressed, snapshot = await compress_history(
        history, user_input, llm_config, scene="init"
    )
    if snapshot.triggered:
        logger.info(
            "上下文压缩触发 (init chat): reason={} {}→{}条",
            snapshot.reason, snapshot.original_count, snapshot.compressed_count,
        )
    if meta_sink is not None:
        meta_sink["context_meta"] = snapshot.to_dict()
    # compress_history 契约：触发/降级路径已在末尾 append current_input；
    # 未触发路径只返回历史 dict，不含 current_input —— 这里补一次。
    if not snapshot.triggered:
        compressed.append({"role": "user", "content": user_input})

    messages: list = [SystemMessage(content=INIT_CHAT_SYSTEM_PROMPT)]
    for m in compressed:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        else:
            messages.append(AIMessage(content=m["content"]))
    return messages


async def _astream_init_chat_agent(
    db, user_id, history: list[Message], user_input: str,
    *, llm_config: ResolvedChatConfig, meta_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """init chat 的 agent loop 主路径（带工具：save_memory / rag_search / MCP）。

    与 orchestrator.astream_chat 同构：build_agent(system_prompt_override=INIT_CHAT_SYSTEM_PROMPT)
    → compress_history → agent.astream_events 事件遍历，yield (kind, payload) 元组。
    init 特殊性：无 section，用 INIT_CHAT_SYSTEM_PROMPT；user_id 直接是会话归属用户。

    usage_sink 不在此路径填充（agent loop 多步调用，与普通助手 astream_chat 一致，落 NULL）。
    """
    from loguru import logger

    from app.ai.agent import build_agent
    from app.ai.context_compactor import compress_history

    logger.info("astream_init_chat: 构建 init agent（model=%s）", llm_config.model)
    agent = await build_agent(
        db, llm_config=llm_config, user_id=user_id,
        system_prompt_override=INIT_CHAT_SYSTEM_PROMPT,
        tool_scope="init",
    )
    logger.info("astream_init_chat: init agent 构建完成，开始 agent loop")

    # 历史压缩（与 astream_chat 同构）+ 观测透传
    compressed, snapshot = await compress_history(
        history, user_input, llm_config, scene="init"
    )
    if snapshot.triggered:
        logger.info(
            "上下文压缩触发 (init chat): reason={} {}→{}条",
            snapshot.reason, snapshot.original_count, snapshot.compressed_count,
        )
    if meta_sink is not None:
        meta_sink["context_meta"] = snapshot.to_dict()
    if not snapshot.triggered:
        compressed.append({"role": "user", "content": user_input})

    # 层 3：agent loop 总超时兜底（与 orchestrator.astream_chat 同构）
    from app.ai.tool_timeout import AGENT_LOOP_TOTAL_TIMEOUT

    try:
        async with asyncio.timeout(AGENT_LOOP_TOTAL_TIMEOUT):
            async for event in agent.astream_events({"messages": compressed}, version="v2"):
                evt = event["event"]
                if evt == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    # 先透传思考过程（reasoning），再透传正文 token（与 orchestrator.astream_chat 同构）
                    reasoning = extract_reasoning(chunk)
                    if reasoning:
                        yield ("thinking", reasoning)
                    if chunk and chunk.content:
                        yield ("token", chunk.content)
                elif evt == "on_tool_start":
                    yield ("tool_call", {
                        "name": event.get("name", ""),
                        "args": event.get("data", {}).get("input", {}),
                    })
                elif evt == "on_tool_end":
                    result = event.get("data", {}).get("output")
                    result_str = str(result)[:500] if result is not None else ""
                    yield ("tool_result", {
                        "name": event.get("name", ""),
                        "result": result_str,
                    })
    except TimeoutError:
        logger.warning("init chat: agent loop 总超时（%ss），强制结束", AGENT_LOOP_TOTAL_TIMEOUT)
        yield ("token", "\n\n[系统提示：回复生成超时，已中止。请重试或简化问题。]")


async def _astream_init_chat_fallback(
    history: list[Message], user_input: str,
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
    meta_sink: dict | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """init chat 降级路径：裸 astream_llm（无工具）。

    模型不支持 tool calling（check_tool_support 抛 ToolSupportError）时走此路径——
    宁可丢工具能力也不阻断对话。ready 判断仍由 coverage 算（不依赖工具）。
    yield ("token", str) 元组，与主路径的 token 事件结构对齐（仅无 tool 事件）。
    """
    messages = await _build_init_chat_messages(
        history, user_input, llm_config, meta_sink=meta_sink
    )
    async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage_sink):
        yield ("token", token)


async def astream_init_chat(
    db, user_id, history: list[Message], user_input: str,
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
    meta_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """项目初始化对话：流式回复用户，yield (kind, payload) 元组。

    主路径走 agent loop（带 save_memory / rag_search / MCP 工具）；模型不支持工具时
    自动降级到裸 astream_llm（只丢工具能力，不阻断对话）。

    yield:
      - ("token", str)：文本 token
      - ("tool_call", {"name", "args"})：agent 发起工具调用（仅主路径）
      - ("tool_result", {"name", "result"})：工具返回（仅主路径）

    meta_sink 透传给压缩观测（spec §5.1）。usage_sink 仅降级路径填充
    （agent loop 路径与普通助手一致落 NULL）。
    """
    from loguru import logger

    from app.ai.tool_support import ToolSupportError

    try:
        # 主路径：agent loop（check_tool_support 在 build_agent 内首道闸）
        async for item in _astream_init_chat_agent(
            db, user_id, history, user_input, llm_config=llm_config, meta_sink=meta_sink
        ):
            yield item
    except ToolSupportError as e:
        # 降级：模型不支持工具 → 回退裸 LLM
        logger.warning("init chat 模型不支持工具，降级裸 LLM: %s", e)
        async for item in _astream_init_chat_fallback(
            history, user_input, llm_config=llm_config,
            usage_sink=usage_sink, meta_sink=meta_sink,
        ):
            yield item


def _format_brief_summary(outline: dict | None) -> str | None:
    """把 draft_outline 格式化成给生成阶段看的 brief 摘要。

    注入到生成消息，让每章生成时对齐已确认维度（而非只靠压缩历史猜），
    信噪比更高。effect 章额外带上 evidence_type 提示，避免生成时臆测绝对数值
    （借鉴 patent-disclosure-pro/references/effect-writing.md）。

    返回 None 表示 outline 为空/无实质内容，调用方据此决定是否注入。
    """
    if not outline:
        return None
    lines = []
    has_content = False
    for key, title in _OUTLINE_TITLES:
        entry = outline.get(key) or {}
        content = (entry.get("content") or "").strip()
        if not content:
            continue
        has_content = True
        evidence = entry.get("evidence_type")
        if key == "effect" and evidence:
            lines.append(f"【{title}】（依据类型：{evidence}）\n{content}")
        else:
            lines.append(f"【{title}】\n{content}")
    if not has_content:
        return None
    return "以下是初始化对话中已确认的项目要点（brief），生成本章时请对齐这些信息：\n\n" + "\n\n".join(lines)


def _retrieve_section_context(
    db, user_id, *, brief_text: str | None, section_title: str,
) -> str | None:
    """为单章生成检索知识库片段，返回格式化后的注入文本（无命中/失败返回 None）。

    query 用「brief 摘要 + 章节标题」组合——brief 提供项目技术语义（信号强于单标题），
    章节标题锚定当前生成维度。检索失败（embedding 未配/异常）静默降级，不阻断生成
    （与 rag_search 工具容错语义一致）。

    此函数同步调用 retrieve（retrieve 内部是同步混合检索）；放在 _build_section_generate_messages
    的 message 装配阶段一次性执行，不进入 agent loop。
    """
    if db is None or user_id is None:
        return None
    from loguru import logger
    from app.rag.retriever import retrieve

    query_parts = [p.strip() for p in (brief_text, section_title) if p and p.strip()]
    if not query_parts:
        return None
    query = "\n".join(query_parts)
    try:
        results = retrieve(db, user_id=user_id, query=query)
    except Exception as e:  # noqa: BLE001 — 检索失败绝不阻断生成
        logger.warning("init generate RAG 检索失败（section={}），跳过注入: {}", section_title, e)
        return None
    if not results:
        return None
    snippets = []
    for r in results:
        title = f"（来源：{r.project_title}）" if r.project_title else ""
        snippets.append(f"{r.content}{title}")
    logger.info("init generate RAG 命中 {} 条（section={}）", len(results), section_title)
    return (
        "以下是检索到的相关知识库片段，生成本章时可参考其写法/结构/技术细节"
        "（请勿照搬，需结合本项目实际）：\n\n" + "\n\n---\n\n".join(snippets)
    )


async def _build_section_generate_messages(
    section: Section, history: list[Message], llm_config,
    *, meta_sink: dict | None = None, outline: dict | None = None,
    db=None, user_id=None,
) -> list:
    """装配单章生成消息：INIT_GENERATE_SYSTEM_PROMPT + brief 摘要 + RAG 片段 + 压缩历史 + 本章生成指令。

    与 orchestrator.astream_generate 的区别：后者走 build_agent（章节策略进 system prompt），
    本函数走裸 astream_llm，故把章节策略揉进生成指令（user message）里。
    复用 build_generate_instruction（含 CoT 分步引导 + 章节 output_format/criteria）。

    outline（draft_outline）注入成 brief 摘要（SystemMessage），让生成对齐已确认维度——
    这是 generate 链路消费 brief 的核心注入点。

    RAG 注入（db + user_id 均提供时）：用「brief 摘要 + 本章标题」组合做 query 检索用户
    知识库，命中片段作为 SystemMessage 注入，供生成参考。检索失败/无命中 → 静默跳过
    （与 rag_search 工具的容错语义一致，绝不阻断生成）。

    meta_sink 非空时写入压缩 snapshot，供调用方记入 LLMCallLog.context_meta。
    """
    from loguru import logger
    from app.ai.context_compactor import compress_history

    instruction = build_generate_instruction(section)
    compressed, snapshot = await compress_history(
        history, instruction, llm_config, scene="init_generate"
    )
    if snapshot.triggered:
        logger.info(
            "上下文压缩触发 (init generate, section={}): reason={} {}→{}条",
            section.key, snapshot.reason, snapshot.original_count, snapshot.compressed_count,
        )
    if meta_sink is not None:
        meta_sink["context_meta"] = snapshot.to_dict()
    # 同 _build_init_chat_messages：未触发路径补 instruction。
    if not snapshot.triggered:
        compressed.append({"role": "user", "content": instruction})

    messages: list = [SystemMessage(content=INIT_GENERATE_SYSTEM_PROMPT)]
    # brief 摘要注入（generate 链路消费 draft_outline 的核心点）
    brief = _format_brief_summary(outline)
    if brief:
        messages.append(SystemMessage(content=brief))
    # RAG 片段注入：brief 摘要 + 本章标题组合做 query（信号强于单标题，省于整段历史）
    rag_snippet = _retrieve_section_context(db, user_id, brief_text=brief, section_title=section.title)
    if rag_snippet:
        messages.append(SystemMessage(content=rag_snippet))
    for m in compressed:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        else:
            messages.append(AIMessage(content=m["content"]))
    return messages


async def astream_init_generate(
    db, conversation, history: list[Message], user,
    *, llm_config: ResolvedChatConfig,
    sections: list[str] | None = None,
    usage_sink: dict | None = None,
    meta_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """扳机落地：为 init 会话建项目 + 填充各章节初稿，流式产出进度与 token。

    接收顶层 init 会话（conversation）+ 用户（user），内部：
    1. create_project 建项目 + 8 空章节
    2. 把 conversation.project_id 填上（标记已落地）
    3. 对项目 sections 循环生成初稿（复用 _build_section_generate_messages + astream_llm）
    4. 回写 section.content + status: empty→drafting

    yield 元组：
      - ("project_created", {"project_id": str})  # 项目建好后即发，前端可提前拿 id
      - ("chapter_start", {"index", "total", "title", "key"})
      - ("token", str)
      - ("chapter_done", {"index", "title", "key", "status", "error"})
      - ("all_done", {"project_id": str})

    单章失败不中断整体（标记 failed，继续下一章）——避免一章挂掉导致整批回滚。
    """
    from sqlalchemy import select

    from app.ai.markdown_to_tiptap import markdown_to_tiptap
    from app.services.project_service import create_project

    # 1. 建项目 + 8 空章节（标题从会话标题提炼）
    title = (conversation.title or "新项目").strip() or "新项目"

    # P0-1 防双击重复落地：对 conversation 行 FOR UPDATE 加锁后，create_project
    # 以 commit=False 并入同一事务，锁一直持有到「project_id 标记已落地」commit 完成。
    # 并发请求在此串行化：第二个请求拿锁后 refresh，project_id 已非空 → ConflictError。
    # SQLite 测试库不支持 FOR UPDATE（静默忽略，不影响测试）。
    from app.core.database import is_postgres
    if is_postgres(db):
        db.execute(
            select(Conversation)
            .where(Conversation.id == conversation.id)
            .with_for_update()
        )
        db.refresh(conversation)
        # 锁内二次检查：若已被并发请求落地，立即拒绝（不白建项目）
        if conversation.project_id is not None:
            from app.core.exceptions import ConflictError
            raise ConflictError("该会话正在落地中，请勿重复点击")

    # create_project 不得自管 commit：中途 commit 会释放上面的行锁，
    # 并发请求就能在「项目已建、标记未写」窗口钻进来（z1a2b3c4d5e6 删掉了
    # 部分唯一索引兜底，行锁是唯一防线，必须持锁到标记完成）。
    project = create_project(db, user=user, title=title[:60], commit=False)

    # 2. 标记会话已落地（project_id 填上 → 列表不再显示）。
    # 与建项目同一事务提交——要么都成，要么都不落地。
    conversation.project_id = project.id
    db.commit()

    yield ("project_created", {"project_id": str(project.id)})

    # 3. 循环生成各章节初稿（brief 来自 conversation.draft_outline，注入对齐已确认维度）
    outline = getattr(conversation, "draft_outline", None) or None
    stmt = select(Section).where(Section.project_id == project.id)
    if sections:
        stmt = stmt.where(Section.key.in_(sections))
    section_list = list(db.scalars(stmt.order_by(Section.order)))
    total = len(section_list)

    for idx, section in enumerate(section_list, start=1):
        yield ("chapter_start", {
            "index": idx, "total": total,
            "title": section.title, "key": section.key,
        })
        full_md = ""
        chapter_error = None
        try:
            messages = await _build_section_generate_messages(
                section, history, llm_config, meta_sink=meta_sink, outline=outline,
                db=db, user_id=user.id,
            )
            async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage_sink):
                full_md += token
                yield ("token", token)
            # 回写：草稿落库 + status 流转（与 generate 端点一致）
            section.content = markdown_to_tiptap(full_md)
            if section.status == "empty":
                section.status = "drafting"
            db.commit()
        except Exception as e:  # noqa: BLE001 — 单章失败不中断整体
            chapter_error = str(e)
            db.rollback()
            # 回滚后 section 对象可能 expire，重新 merge 取回以继续后续章节
            db.refresh(section)
        finally:
            yield ("chapter_done", {
                "index": idx, "title": section.title, "key": section.key,
                "status": "failed" if chapter_error else "ok",
                "error": chapter_error,
            })

    yield ("all_done", {"project_id": str(project.id)})

