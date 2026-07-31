"""项目初始化助手编排：对话引导 + 批量生成 8 章初稿。

定位（详见 docs/superpowers/plans/2026-07-30-init-assistant.md）：
- 助手只用于「项目冷启动」，不是项目内常驻统筹 agent。
- 对话挂在项目首个 section 下（复用 Conversation/Message，零 schema 改动）。
- 对话结束后后端批量生成 8 章初稿并回填（后端编排，非 LLM tool-call 自写）。

与 orchestrator.py 的区别：
- orchestrator 是 section 粒度（单章对话/生成），强依赖 build_system_prompt 的章节策略。
- init_orchestrator 是项目粒度：对话不绑定单 section（用 INIT_SYSTEM_PROMPT），
  生成时一次性循环 8 章（用 astream_llm 纯生成，不走 agent loop）。

阶段 A 简化：init chat 走裸 astream_llm（无工具调用）。rag_search/save_memory 工具
增强留到阶段 B（需 agent loop，届时给 build_agent 传首个 section 作占位）。
"""
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.ai.llm_client import astream_llm
from app.ai.orchestrator import build_generate_instruction
from app.ai.section_prompts import get_section_prompt
from app.models import Message, Project, Section
from app.services.llm_config_service import ResolvedChatConfig

# ── 项目初始化助手 system prompt（裁剪自 context_assembler.SYSTEM_PROMPT）──
# 不绑定单 section；目标是引导用户把想法说清楚，为生成 8 章做准备。
# 写作规范浓缩自 assets/skills/ 下的内置 skill（patent-de-ai / patent-writing-quality /
# patent-effect-contrast）——让助手引导用户时即遵守这些规范。
INIT_SYSTEM_PROMPT = """你是「天工」项目初始化助手。用户想新建一个专利交底书项目，但通常只有一个模糊的技术想法。你的任务是通过对话，帮用户把想法理清楚，为后续一键生成 8 章初稿做准备。

对话目标——逐步引导用户说清以下几方面（不必一次问全，每轮聚焦一个方向，结合用户已说的内容追问）：
1. 技术领域：这个发明属于什么领域？解决哪类问题？
2. 要解决的技术问题：现有技术有什么不足？本发明针对哪个具体问题？
3. 技术方案的大致轮廓：核心做法是什么？有哪些关键步骤/模块/组件？
4. 关键特征与效果：相比现有方案，新在哪、好在哪？

规则：
1. 用专业但通俗的中文，避免生硬法律术语
2. 引导用户补充真实技术细节，不要替用户编造数据或效果
3. 信息不足时主动追问；信息已较完整时，告诉用户可以点「生成项目骨架」了
4. 保持客观，不夸大技术效果
5. 回复简洁，每轮对话聚焦引导，不要长篇大论

写作规范（生成内容时也要遵守，此处作为对话引导的标尺）：
- 去 AI 味：禁用「更为关键的是」「换言之」「值得注意的是」等套话转折词；避免超长句和三连排比
- 英文术语首现必须带中文翻译，格式「中文译名（English Term）」
- 技术效果用「现有技术短板→本方案做法→量化差异」三段式，不臆测绝对数值
"""


async def _build_init_chat_messages(
    history: list[Message], user_input: str, llm_config,
    *, meta_sink: dict | None = None,
) -> list:
    """装配 init chat 消息：INIT_SYSTEM_PROMPT + 压缩后历史。

    历史先经 compress_history 压缩（压缩 spec），再转 LangChain 消息类型。
    meta_sink 非空时写入压缩 snapshot，供调用方记入 LLMCallLog.context_meta。
    """
    from app.ai.context_compactor import compress_history

    compressed, snapshot = await compress_history(
        history, user_input, llm_config, scene="init"
    )
    if snapshot.triggered:
        import logging
        logging.getLogger(__name__).info(
            "上下文压缩触发 (init chat): reason=%s %d→%d条",
            snapshot.reason, snapshot.original_count, snapshot.compressed_count,
        )
    if meta_sink is not None:
        meta_sink["context_meta"] = snapshot.to_dict()
    # compress_history 契约：触发/降级路径已在末尾 append current_input；
    # 未触发路径只返回历史 dict，不含 current_input —— 这里补一次。
    if not snapshot.triggered:
        compressed.append({"role": "user", "content": user_input})

    messages: list = [SystemMessage(content=INIT_SYSTEM_PROMPT)]
    for m in compressed:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        else:
            messages.append(AIMessage(content=m["content"]))
    return messages


async def astream_init_chat(
    history: list[Message], user_input: str,
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
    meta_sink: dict | None = None,
) -> AsyncIterator[str]:
    """项目初始化对话：流式回复用户，逐 token yield 文本。

    阶段 A 走裸 astream_llm（无工具调用）。复用对话历史。
    meta_sink 透传给 _build_init_chat_messages 写入压缩 snapshot（spec §5.1）。
    """
    messages = await _build_init_chat_messages(
        history, user_input, llm_config, meta_sink=meta_sink
    )
    async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage_sink):
        yield token


async def _build_section_generate_messages(
    section: Section, history: list[Message], llm_config,
    *, meta_sink: dict | None = None,
) -> list:
    """装配单章生成消息：INIT_SYSTEM_PROMPT + 压缩历史 + 本章生成指令。

    与 orchestrator.astream_generate 的区别：后者走 build_agent（章节策略进 system prompt），
    本函数走裸 astream_llm，故把章节策略揉进生成指令（user message）里。
    复用 build_generate_instruction（含 CoT 分步引导 + 章节 output_format/criteria）。
    meta_sink 非空时写入压缩 snapshot，供调用方记入 LLMCallLog.context_meta。
    """
    from app.ai.context_compactor import compress_history

    instruction = build_generate_instruction(section)
    compressed, snapshot = await compress_history(
        history, instruction, llm_config, scene="init_generate"
    )
    if snapshot.triggered:
        import logging
        logging.getLogger(__name__).info(
            "上下文压缩触发 (init generate, section=%s): reason=%s %d→%d条",
            section.key, snapshot.reason, snapshot.original_count, snapshot.compressed_count,
        )
    if meta_sink is not None:
        meta_sink["context_meta"] = snapshot.to_dict()
    # 同 _build_init_chat_messages：未触发路径补 instruction。
    if not snapshot.triggered:
        compressed.append({"role": "user", "content": instruction})

    messages: list = [SystemMessage(content=INIT_SYSTEM_PROMPT)]
    for m in compressed:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        else:
            messages.append(AIMessage(content=m["content"]))
    return messages


async def astream_init_generate(
    db, project: Project, history: list[Message],
    *, llm_config: ResolvedChatConfig,
    sections: list[str] | None = None,
    usage_sink: dict | None = None,
    meta_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """批量生成项目各章节初稿，流式产出进度与 token。

    对项目的 sections 循环（可按 key 过滤，默认全部），每章：
    - 装配消息（对话历史 + 本章生成指令）
    - astream_llm 生成 Markdown
    - 回写 section.content（markdown_to_tiptap）+ status: empty→drafting
    - 流式产出 ("chapter_start", {...}) / ("token", str) / ("chapter_done", {...})

    yield 元组（与 astream_chat/generate 风格一致，供 SSE 层消费）：
      - ("chapter_start", {"index": int, "total": int, "title": str, "key": str})
      - ("token", str)  # 当前章节的生成 token
      - ("chapter_done", {"index": int, "title": str, "key": str, "status": "ok"|"failed", "error": str|None})
      - ("all_done", {"project_id": str})

    单章失败不中断整体（标记 failed，继续下一章）——避免一章挂掉导致整批回滚。
    token 用量累加进 usage_sink（多章调用，prompt/completion 分别累加）。
    """
    from sqlalchemy import select

    from app.ai.markdown_to_tiptap import markdown_to_tiptap

    # 取项目的 section，按 order 排序；可按 key 过滤
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
                section, history, llm_config, meta_sink=meta_sink
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
