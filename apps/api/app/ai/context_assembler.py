"""五层上下文装配（设计 5.4）。

[系统层] 角色 + 输出规范
[项目层] 已确认章节的 summary
[章节层] 当前章节的 Prompt 策略
[对话层] 本章节历史对话
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select

from app.ai.section_prompts import get_section_prompt
from app.models import Message, Project, Section
from app.services.summary_service import _extract_text

SYSTEM_PROMPT = """你是「天工」，一个专利交底书撰写助手。你的任务是引导发明人把技术想法整理成规范的专利交底书。

规则：
1. 用专业但通俗的中文交流，避免生硬的法律术语
2. 引导用户补充关键技术细节，不要替用户编造
3. 输出内容用 Markdown 格式（标题用 ##/###，可用列表）
4. 保持客观准确，不夸大技术效果
5. 如果用户的信息不完整，主动追问
6. 当用户表达了值得长期记住的偏好、事实或领域约定时，调用 save_memory 工具保存。
   只记跨项目稳定的信息（如「偏好简洁风格」「我做新能源电池」），不记项目内具体决策。"""


def assemble_messages(
    section: Section,
    history: list[Message],
    user_input: str | None = None,
    project_summaries: list[dict] | None = None,
    knowledge_context: list[dict] | None = None,
) -> list:
    """装配完整的消息列表。"""
    messages = []

    sp = get_section_prompt(section.key)
    system_content = SYSTEM_PROMPT + f"\n\n当前正在撰写章节：【{section.title}】\n"
    system_content += f"本章目标：{sp.goal}\n"
    system_content += f"输出格式要求：{sp.output_format}"

    if project_summaries:
        summary_text = "\n".join(
            f"- {s['title']}：{s['summary']}" for s in project_summaries if s.get("summary")
        )
        if summary_text:
            system_content += f"\n\n已完成章节摘要（可作为上下文参考）：\n{summary_text}"

    # 知识库层（RAG 检索注入，设计 10.4）
    if knowledge_context:
        kb_text = "\n".join(
            f"- 《{k.get('project_title', '历史案例')}》{k.get('section_key', '')}：{k['content'][:200]}"
            for k in knowledge_context
        )
        if kb_text:
            system_content += f"\n\n相关知识库参考（来自你的历史案例）：\n{kb_text}"

    messages.append(SystemMessage(content=system_content))

    for msg in history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))

    if user_input:
        messages.append(HumanMessage(content=user_input))

    return messages


def get_project_summaries(db, project_id) -> list[dict]:
    """获取项目已确认章节的 summary（跨章节上下文）。"""
    from sqlalchemy import select

    sections = db.scalars(
        select(Section).where(
            (Section.project_id == project_id)
            & (Section.status == "confirmed")
            & (Section.summary.isnot(None))
        ).order_by(Section.order)
    )
    return [{"title": s.title, "summary": s.summary} for s in sections]


# 前文注入字符软上限（T1 方案，spec §2.3 决策③）
# MVP 阶段无真实长文数据，覆盖 90% 场景；超长文场景等真实数据出现再做分块/滑动窗口
WRITTEN_SECTIONS_CHAR_BUDGET = 8000


def get_written_sections_text(db, project_id, exclude_key: str) -> str:
    """查询同项目所有非空章节（不论 status，排除当前章节），提取纯文本，截断到软上限。

    - 不论 status：drafting / confirmed 都注入（绕开 summary 的 confirmed 触发限制，spec §3.1.2）
    - content.isnot(None)：空章节跳过
    - 按 Section.order 装配，超 WRITTEN_SECTIONS_CHAR_BUDGET 时截断当前章并中止（保证前面章节完整）
    - 复用 summary_service._extract_text 提取 Tiptap JSON 纯文本（与 rag/archiver、review_service 同一既定模式）
    """
    sections = db.scalars(
        select(Section).where(
            (Section.project_id == project_id)
            & (Section.key != exclude_key)
            & (Section.content.isnot(None))
        ).order_by(Section.order)
    )
    parts: list[str] = []
    total = 0
    for s in sections:
        text = _extract_text(s.content).strip()
        if not text:
            continue
        chunk = f"## {s.title}\n{text}"
        if total + len(chunk) > WRITTEN_SECTIONS_CHAR_BUDGET:
            # 软上限：保留前面已装配的，当前章截断后中止
            remaining = WRITTEN_SECTIONS_CHAR_BUDGET - total
            if remaining > 20:  # 剩余空间太小（连标题+几个字都塞不下）就不塞半截
                parts.append(f"## {s.title}\n{text[:remaining]}\n…（已截断）")
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)


def _format_metadata(metadata: dict | None) -> str:
    """格式化项目 metadata（JSON dict）为可读文本。防御性：只取字符串/数字值，跳过嵌套结构。

    metadata 结构未定死（Project.metadata_ 是自由 JSON），做防御性格式化避免
    嵌套 dict/list 把 system prompt 搞乱。spec §3.1.3。
    """
    if not isinstance(metadata, dict) or not metadata:
        return ""
    lines = []
    for k, v in metadata.items():
        if isinstance(v, (str, int, float)):
            lines.append(f"- {k}：{v}")
    return "\n".join(lines)


def _search_user_memories(db, user_id, query: str):
    """检索用户记忆，失败时静默返回空（不阻断 prompt 装配）。"""
    try:
        from app.services.memory_service import search_memories
        return search_memories(db, user_id=user_id, query=query)
    except Exception:
        # embedding/检索失败不阻断主流程，记忆层留空
        return []


def build_system_prompt(db, section: Section) -> str:
    """装配动态 system prompt（agent loop 路线用，spec §3.1.1）。

    拼接顺序：项目元信息 [L4] → 已写章节 [前文直注入] → 当前章节策略 → 角色定义。

    项目元信息在顶部（全局不变量先建立上下文），角色定义在底部（行为规范在看到具体任务后理解更准确）。
    此顺序与原 assemble_messages 的拼接顺序保持心智模型统一。
    """
    project = db.get(Project, section.project_id)
    sp = get_section_prompt(section.key)

    parts: list[str] = []

    # [L4] 项目元信息层（顶部，全局上下文）
    parts.append("# 当前交底书项目")
    parts.append(f"项目标题：{project.title}")
    if project.metadata_:
        meta_text = _format_metadata(project.metadata_)
        if meta_text:
            parts.append(f"项目背景信息：\n{meta_text}")

    # [前文直注入] 已写章节层（中部，跨章节上下文）
    written = get_written_sections_text(db, section.project_id, exclude_key=section.key)
    if written:
        parts.append("# 已完成章节内容（请保持术语、技术方案一致性）")
        parts.append(written)

    # 【新增】用户长期记忆层（检索注入，纯检索式策略）
    # 用章节标题 + 目标做检索 query，覆盖本章节最可能相关的用户偏好/事实/know-how
    # project 已在上方 fetch（L164），直接复用其 user_id，避免重复查询。
    if project.user_id is not None:
        memories = _search_user_memories(db, project.user_id, f"{section.title} {sp.goal}")
        if memories:
            memory_lines = "\n".join(f"- {m.content}" for m in memories)
            parts.append("# 关于这位用户的长期记忆（请遵循其偏好与约定）")
            parts.append(memory_lines)

    # 章节策略层（底部偏上，当前章节聚焦）
    parts.append("# 当前正在撰写章节")
    parts.append(f"章节标题：【{section.title}】")
    parts.append(f"本章目标：{sp.goal}")
    parts.append(f"输出格式要求：{sp.output_format}")

    # 角色定义层（最底部，兜底规范）
    parts.append(SYSTEM_PROMPT)

    return "\n\n".join(parts)
