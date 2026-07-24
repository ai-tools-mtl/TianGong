"""归档服务：交底书章节 → 分块 → 向量化 → 入库（设计 10.1/10.5）。"""

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, Project, Section
from app.rag.chunker import chunk_sections
from app.rag.embedding import embed_texts
from app.services.llm_config_service import resolve_embedding_config
from app.services.llm_log_helper import log_embed_call


def archive_project(db: Session, *, project: Project, user_id) -> int:
    """归档项目。返回写入的 chunk 数。幂等：先删旧 chunk 再重生成。

    向量化配置由 user_id 内部解析（断链修复：embed 真用自定义/全局配置）。
    无可用配置时返回 0（无法向量化则无法归档）。
    """
    embed_config = resolve_embedding_config(db, user_id=user_id)
    if embed_config is None:
        return 0

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
    try:
        vectors = embed_texts(texts, embed_config=embed_config)
    except Exception:
        # D7：embed 失败也记一条日志（仅元数据，不含内容），再向上抛
        log_embed_call(
            db, user_id=user_id, model=embed_config.model,
            provider=embed_config.source, project_id=project.id,
            status="failed",
        )
        raise
    # D7：写 embedding 调用日志（仅元数据，让 admin 统计区分 chat/embedding）
    log_embed_call(
        db, user_id=user_id, model=embed_config.model,
        provider=embed_config.source, project_id=project.id,
        status="success",
    )

    # 写入
    for chunk, vec in zip(chunks, vectors, strict=False):
        db.add(KnowledgeChunk(
            user_id=user_id,
            scope="personal",  # 三域隔离(关键约束 1):归档进个人库,上报通过才升 global
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
