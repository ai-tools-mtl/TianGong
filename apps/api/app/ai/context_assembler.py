"""五层上下文装配（设计 5.4）。

[系统层] 角色 + 输出规范
[项目层] 已确认章节的 summary
[章节层] 当前章节的 Prompt 策略
[对话层] 本章节历史对话
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select

from app.ai.section_prompts import get_section_prompt
from app.models import Message, Section
from app.services.summary_service import _extract_text

SYSTEM_PROMPT = """你是「天工」，一个专利交底书撰写助手。你的任务是引导发明人把技术想法整理成规范的专利交底书。

规则：
1. 用专业但通俗的中文交流，避免生硬的法律术语
2. 引导用户补充关键技术细节，不要替用户编造
3. 输出内容用 Markdown 格式（标题用 ##/###，可用列表）
4. 保持客观准确，不夸大技术效果
5. 如果用户的信息不完整，主动追问"""


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
