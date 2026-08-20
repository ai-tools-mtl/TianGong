"""章节 summary 生成（设计 5.10）。

确认章节时触发，生成 100-200 字摘要供跨章节上下文用。
失败降级为取正文前 N 字。
"""

from sqlalchemy.orm import Session

from app.models import Section
from app.core.logging import get_logger

logger = get_logger(__name__)


def generate_summary(db: Session, section: Section) -> str:
    """为章节生成 summary。失败降级取前 200 字。"""
    if not section.content:
        return ""

    text = _extract_text(section.content)
    if not text.strip():
        return ""

    try:
        from langchain_core.messages import HumanMessage

        from app.ai.llm_client import get_llm
        from app.models import Project
        from app.services.llm_config_service import resolve_lite_config

        # Section 无 user_id，经 project 取归属用户后解析轻量任务模型配置。
        # resolve_lite_config 优先用 admin 配的轻量模型（典型 GLM-4.7-Flash），
        # 未配则回退该用户 chat 配置。无配置 → raise ValueError，被下方 except
        # 捕获后走降级（取正文前 200 字）。
        project = db.get(Project, section.project_id)
        if project is None:
            raise ValueError("section has no project")
        llm_config = resolve_lite_config(db, user_id=project.user_id)
        if llm_config is None:
            raise ValueError("no llm config")

        llm = get_llm(llm_config)
        resp = llm.invoke([
            HumanMessage(content=(
                f"请用 100-200 字概括以下专利交底书章节内容的核心要点：\n\n"
                f"章节：{section.title}\n内容：{text[:2000]}"
            ))
        ])
        summary = resp.content.strip()
        section.summary = summary[:500]
        db.commit()
        return summary
    except Exception:
        logger.warning("章节摘要生成失败，降级截断原文（跨章节上下文质量会受影响）")
        fallback = text[:200]
        section.summary = fallback
        db.commit()
        return fallback


def _extract_text(tiptap_doc: dict) -> str:
    """从 Tiptap JSON 提取纯文本。

    返回前清洗 NUL/控制字符（sanitize_text_for_pg）：用户在编辑器粘贴的内容
    可能含控制字符，写入 Section.summary / KnowledgeChunk.content（PG text 列）
    会触发 DataError。与 dispatcher.extract_text 同根，统一在出口清洗。
    """
    from app.core.text_utils import sanitize_text_for_pg

    parts: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            for child in node.get("content", []):
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(tiptap_doc)
    return sanitize_text_for_pg("".join(parts))
