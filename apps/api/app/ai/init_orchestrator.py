"""项目初始化助手编排：对话引导 + 扳机落地建项目并生成 8 章初稿。

定位（详见 docs/superpowers/specs/2026-07-31-chatgpt-style-init-assistant-design.md）：
- ChatGPT 式独立对话页的助手，对话在项目创建前进行（顶层 init 会话，kind='init'）。
- agent 判断信息充分后用 [READY_TO_CREATE] 标记，用户按扳机 → 本模块建项目 + 填 8 章。

与 orchestrator.py 的区别：
- orchestrator 是 section 粒度（单章对话/生成），强依赖 build_system_prompt 的章节策略。
- init_orchestrator 是项目粒度：对话不绑定单 section（用 INIT_SYSTEM_PROMPT），
  generate 时一次性循环 8 章（用 astream_llm 纯生成，不走 agent loop）。

init chat 走裸 astream_llm（无工具调用）。
"""
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.ai.llm_client import astream_llm
from app.ai.orchestrator import build_generate_instruction
from app.models import Message, Section
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
3. 信息不足时主动追问；信息已较完整时，按下方规则 6 输出时机标记
4. 保持客观，不夸大技术效果
5. 回复简洁，每轮对话聚焦引导，不要长篇大论
6. 当你判断已经收集到足够信息（技术领域、要解决的问题、技术方案的大致轮廓、关键特征都基本清楚），
   在回复的【最末尾】单独输出一行标记 `[READY_TO_CREATE]`（必须是这个精确字符串，独占一行）。
   前端会据此提示用户「可以创建项目了」。没收集够时不要输出这个标记。
   输出标记前照常把当轮该说的话说完（如总结你理解的需求、确认要点），标记只追加在最末尾。

写作规范（生成内容时也要遵守，此处作为对话引导的标尺）：
- 去 AI 味：禁用「更为关键的是」「换言之」「值得注意的是」等套话转折词；避免超长句和三连排比
- 英文术语首现必须带中文翻译，格式「中文译名（English Term）」
- 技术效果用「现有技术短板→本方案做法→量化差异」三段式，不臆测绝对数值
"""


def _build_init_chat_messages(history: list[Message], user_input: str) -> list:
    """装配 init chat 的消息列表：INIT_SYSTEM_PROMPT + 历史 + 当前输入。"""
    messages: list = [SystemMessage(content=INIT_SYSTEM_PROMPT)]
    for msg in history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))
    messages.append(HumanMessage(content=user_input))
    return messages


async def astream_init_chat(
    history: list[Message], user_input: str,
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
) -> AsyncIterator[str]:
    """项目初始化对话：流式回复用户，逐 token yield 文本。

    阶段 A 走裸 astream_llm（无工具调用）。复用对话历史。
    """
    messages = _build_init_chat_messages(history, user_input)
    async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage_sink):
        yield token


def _build_section_generate_messages(
    section: Section, history: list[Message],
) -> list:
    """装配单章生成消息：INIT_SYSTEM_PROMPT + 对话历史 + 本章生成指令。

    与 orchestrator.astream_generate 的区别：后者走 build_agent（章节策略进 system prompt），
    本函数走裸 astream_llm，故把章节策略揉进生成指令（user message）里。
    复用 build_generate_instruction（含 CoT 分步引导 + 章节 output_format/criteria）。
    """
    messages: list = [SystemMessage(content=INIT_SYSTEM_PROMPT)]
    for msg in history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))
    # 复用 orchestrator 的 CoT 生成指令（已含章节 goal/format/criteria + 分步思考）
    messages.append(HumanMessage(content=build_generate_instruction(section)))
    return messages


async def astream_init_generate(
    db, conversation, history: list[Message], user,
    *, llm_config: ResolvedChatConfig,
    sections: list[str] | None = None,
    usage_sink: dict | None = None,
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
    project = create_project(db, user=user, title=title[:60])

    # 2. 标记会话已落地（project_id 填上 → 列表不再显示）
    conversation.project_id = project.id
    db.commit()

    yield ("project_created", {"project_id": str(project.id)})

    # 3. 循环生成各章节初稿
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
            messages = _build_section_generate_messages(section, history)
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

