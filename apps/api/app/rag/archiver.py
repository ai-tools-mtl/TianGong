"""归档服务：交底书章节 → 分块 → 向量化 → 入库（设计 10.1/10.5）。"""

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, Project, Section
from app.rag.chunker import chunk_sections
from app.rag.embedding import embed_texts


def archive_project(db: Session, *, project: Project, user_id) -> int:
    """归档项目。返回写入的 chunk 数。幂等：先删旧 chunk 再重生成。"""
    sections = _get_section_texts(db, project)
    if not sections:
        return 0

    chunks = chunk_sections(sections)
    if not chunks:
        return 0

    # 删除该项目的旧 chunk（幂等，设计 10.5）
    db.execute(
        delete(KnowledgeChunk).where(
            (KnowledgeChunk.source_id == project.id)
            & (KnowledgeChunk.source_type == "disclosure")
        )
    )
    db.flush()

    # 批量向量化
    texts = [c.content for c in chunks]
    vectors = embed_texts(texts)

    # 写入
    for chunk, vec in zip(chunks, vectors, strict=False):
        db.add(KnowledgeChunk(
            user_id=user_id,
            source_type="disclosure",
            source_id=project.id,
            source_section_key=chunk.section_key,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            embedding=vec,
            metadata_={"project_title": project.title},
        ))

    project.status = "archived"
    project.archived_at = datetime.now(timezone.utc)
    db.commit()
    return len(chunks)


def _get_section_texts(db: Session, project: Project) -> list[dict]:
    """提取项目的章节文本（从 Tiptap JSON 提取纯文本）。"""
    from app.services.summary_service import _extract_text

    sections = list(db.scalars(
        select(Section).where(Section.project_id == project.id).order_by(Section.order)
    ))
    result = []
    for s in sections:
        text = _extract_text(s.content) if s.content else ""
        result.append({"key": s.key, "title": s.title, "content": text})
    return result
