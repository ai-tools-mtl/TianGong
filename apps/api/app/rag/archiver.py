"""归档服务：交底书章节 → 分块 → 向量化 → 入库（设计 10.1/10.5）。

2026-07 异步化改造（与知识库上传同模式）：
- archive_project 请求内只做：提取章节 + 分块 + 删旧 chunk + 写空 embedding 新 chunk
  + 置 project.status="archiving"，立即返回。embed 在后台 standalone 任务跑。
- run_archive_embed_standalone：自开 session，FOR UPDATE SKIP LOCKED 查 project，
  批量 embed 该 project 的 disclosure chunk，成功→archived，失败→completed 回滚。
- 数据安全：旧 chunk 在新 chunk 写入后才删（不再先删后建）；失败时 project 回到 completed。

注意：归档无 KnowledgeFile 载体，用 Project.status 状态机跟踪进度。
"""

import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import delete, select, text as sa_text
from sqlalchemy.orm import Session

from app.core.database import is_postgres
from app.models import KnowledgeChunk, Project, Section
from app.rag.chunker import chunk_sections
from app.rag.embedding import embed_texts
from app.services.llm_config_service import resolve_embedding_config
from app.services.llm_log_helper import log_embed_call


def archive_project(db: Session, *, project: Project, user_id) -> int:
    """归档项目（请求内阶段）：分块 + 删旧 + 写空 embedding 新 chunk + 置 archiving。

    返回写入的 chunk 数（供 API 返回）。向量化在 run_archive_embed_standalone 后台跑。
    幂等：先删旧 chunk 再重生（同 project 的 disclosure chunk）。
    """
    sections = _get_section_texts(db, project)
    if not sections:
        return 0

    chunks = chunk_sections(sections)
    if not chunks:
        return 0

    # 删除该项目的旧 chunk（幂等，设计 10.5）。先删后建在新 embed 前，避免新旧并存。
    db.execute(
        delete(KnowledgeChunk).where(
            (KnowledgeChunk.source_id == project.id)
            & (KnowledgeChunk.source_type == "disclosure")
        )
    )
    db.flush()

    # 写入空 embedding 的 chunk（向量化后台做）
    for chunk in chunks:
        db.add(KnowledgeChunk(
            user_id=user_id,
            scope="personal",  # 三域隔离:归档进个人库,上报通过才升 global
            source_type="disclosure",
            source_id=project.id,
            source_section_key=chunk.section_key,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            embedding=None,  # 待后台 embed 填充
            metadata_={"project_title": project.title},
        ))

    # G3：生成 tsv（仅 PG）。先 flush 让 INSERT 落 DB，UPDATE 才能命中本批 chunk。
    if is_postgres():
        db.flush()
        db.execute(sa_text(
            "UPDATE knowledge_chunks SET tsv = to_tsvector('simple', coalesce(content, '')) "
            "WHERE tsv IS NULL AND source_id = :sid AND source_type = 'disclosure'"
        ), {"sid": str(project.id)})

    # 置 archiving 态（后台 embed 完成后改 archived）
    project.status = "archiving"
    db.commit()
    return len(chunks)


def run_archive_embed_standalone(project_id: str) -> None:
    """后台向量化归档 chunk（standalone session，镜像 run_embed_job_standalone）。

    状态流转：archiving → archived（成功）/ completed（失败，回滚到归档前）。
    FOR UPDATE SKIP LOCKED 防 recover 与 background 并发夺同一 project。
    """
    try:
        pid = uuid.UUID(project_id)
    except (ValueError, TypeError):
        logger.warning(f"run_archive_embed_standalone 收到非法 project_id={project_id!r}，忽略")
        return

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        # FOR UPDATE SKIP LOCKED（仅 PG）：防并发夺锁
        if is_postgres():
            project = db.scalar(
                select(Project).where(Project.id == pid).with_for_update(skip_locked=True)
            )
        else:
            project = db.get(Project, pid)
        if project is None:
            logger.info(f"归档向量化 {project_id[:8]}... project 不存在或被锁，跳过")
            return
        if project.status != "archiving":
            logger.info(f"归档向量化 {project_id[:8]}... status={project.status} 非 archiving，跳过")
            return

        # 查待 embed 的 chunk（embedding IS NULL 的 disclosure chunk）
        chunks = db.execute(
            select(KnowledgeChunk).where(
                (KnowledgeChunk.source_id == pid)
                & (KnowledgeChunk.source_type == "disclosure")
                & (KnowledgeChunk.embedding.is_(None))
            )
        ).scalars().all()
        if not chunks:
            # 没有待 embed 的，直接标记完成
            project.status = "archived"
            project.archived_at = datetime.now(timezone.utc)
            db.commit()
            return

        embed_config = resolve_embedding_config(db, user_id=project.user_id)
        if embed_config is None:
            logger.warning(f"归档向量化 {project_id[:8]}... 无 embedding 配置，回滚到 completed")
            project.status = "completed"
            db.commit()
            return

        try:
            vectors = embed_texts([c.content for c in chunks], embed_config=embed_config)
        except Exception:
            log_embed_call(
                db, user_id=project.user_id, model=embed_config.model,
                provider=embed_config.source, project_id=pid, status="failed",
            )
            raise
        log_embed_call(
            db, user_id=project.user_id, model=embed_config.model,
            provider=embed_config.source, project_id=pid, status="success",
        )

        for chunk, vec in zip(chunks, vectors, strict=False):
            chunk.embedding = vec

        project.status = "archived"
        project.archived_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"归档向量化 {project_id[:8]}... 完成，{len(chunks)} 个 chunk 已向量化")
    except Exception as e:
        logger.exception(f"归档向量化 {project_id[:8]}... 失败：{e}")
        try:
            project = db.get(Project, pid)
            if project is not None and project.status == "archiving":
                # 失败回滚到归档前状态（completed），让用户可重试
                project.status = "completed"
                db.commit()
        except Exception:
            logger.exception(f"归档向量化 {project_id[:8]}... 写回滚状态也失败")
    finally:
        db.close()


def recover_stale_archives(stale_minutes: int = 10) -> int:
    """启动恢复：重启后重入队 status=archiving 的孤儿项目。

    run_archive_embed_standalone 自带幂等（非 archiving 跳过）。
    """
    from app.core.background import spawn_background_task
    from app.core.database import SessionLocal

    db = SessionLocal()
    count = 0
    try:
        projects = list(db.scalars(
            select(Project).where(Project.status == "archiving")
        ))
        for p in projects:
            spawn_background_task(run_archive_embed_standalone, str(p.id))
            count += 1
    finally:
        db.close()
    return count


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
