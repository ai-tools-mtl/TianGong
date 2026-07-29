"""知识库三域 CRUD + 上报(计划 T9)。

三域(关键约束 1):
- upload_to_global: admin 直传,scope=global,bucket=global,全员可检索
- upload_external: user 上传外部素材,scope=personal,bucket=personal
- (归档流由 archive_service 写 scope=personal,此处不涉及)

上报(关键约束 2):submit_for_review 建 KnowledgeReview(pending),
  admin 审核在 review_service(T10)处理。

异步向量化(plan async-knowledge-upload):
- upload_external / upload_to_global 只做落库(写空 embedding 的 chunk),立即返回
  (file.status=pending)。向量化交给后台 run_embed_job_standalone(自开 session)。
- 调用方(文件上传端点 / web_ingestion)负责 spawn 后台任务。
- chunk 写入复用 chunker + embedding。注意:SQLite 测试库跳过
  knowledge_chunks 表,本模块的 chunk 写入在 PG 集成验证。
"""

import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.core.database import is_postgres
from app.core.exceptions import NotFoundError, ValidationError
from app.core.storage import Storage
from app.models import KnowledgeChunk, KnowledgeFile, KnowledgeReview
from app.rag.chunker import chunk_sections
from app.rag.embedding import embed_texts
from app.services.llm_config_service import resolve_embedding_config
from app.services.llm_log_helper import log_embed_call


def upload_to_global(
    db: Session, *, storage: Storage, uploader, filename: str,
    content: bytes, mime: str, text: str,
    url: str | None = None,
    source_type_override: str | None = None,
) -> KnowledgeFile:
    """admin 直传全局库。落库 file + 空 embedding 的 chunk(scope=global)。

    异步向量化:本函数只落库(status=pending, stage=uploaded),不调 embed_texts。
    调用方负责 spawn run_embed_job_standalone 做后台向量化。
    全局库去重:按 content_hash(SHA256)查重,已存在则返回已有记录,
    不重复存储/向量化(防 admin 反复上传同一文件导致检索结果重复)。
    """
    import hashlib

    source_type = source_type_override or _source_type_for(filename)
    content_hash = hashlib.sha256(content).hexdigest()

    # 去重:全局库已有同内容文件 → 直接返回
    existing = db.scalar(
        select(KnowledgeFile).where(
            (KnowledgeFile.scope == "global")
            & (KnowledgeFile.content_hash == content_hash)
        )
    )
    if existing is not None:
        return existing

    object_key = f"global/{uuid.uuid4()}.{_ext(filename)}"
    storage.put("global", object_key, content, mime)

    kf = KnowledgeFile(
        uploader_id=uploader.id, scope="global", bucket="global",
        object_key=object_key, filename=filename, mime_type=mime,
        size=len(content), source_type=source_type,
        content_hash=content_hash,
        url=url,
        status="pending", stage="uploaded",
    )
    db.add(kf)
    db.flush()  # 让 kf.id 就位
    _write_chunks_unembedded(
        db, scope="global", user_id=uploader.id, file_id=kf.id,
        source_type=source_type, text=text, title=filename,
    )
    db.commit()
    db.refresh(kf)
    return kf


def upload_external(
    db: Session, *, storage: Storage, user, filename: str,
    content: bytes, mime: str, text: str,
    url: str | None = None,
    source_type_override: str | None = None,
) -> KnowledgeFile:
    """user 上传外部素材进个人库。落库 file + 空 embedding 的 chunk(scope=personal)。

    异步向量化:本函数只落库(status=pending, stage=uploaded),不调 embed_texts。
    调用方负责 spawn run_embed_job_standalone 做后台向量化。
    """
    source_type = source_type_override or _source_type_for(filename)
    object_key = f"personal/{user.id}/{uuid.uuid4()}.{_ext(filename)}"
    storage.put("personal", object_key, content, mime)

    import hashlib

    kf = KnowledgeFile(
        uploader_id=user.id, scope="personal", bucket="personal",
        object_key=object_key, filename=filename, mime_type=mime,
        size=len(content), source_type=source_type,
        content_hash=hashlib.sha256(content).hexdigest(),
        url=url,
        status="pending", stage="uploaded",
    )
    db.add(kf)
    db.flush()
    _write_chunks_unembedded(
        db, scope="personal", user_id=user.id, file_id=kf.id,
        source_type=source_type, text=text, title=filename,
    )
    db.commit()
    db.refresh(kf)
    return kf


def submit_for_review(
    db: Session, *, submitter_id: str, file_id: str,
    source_type: str = "external",
) -> KnowledgeReview:
    """user 上报个人素材进全局审核。建 pending 工单(幂等)。

    越权(非 owner)返回 404,不暴露文件存在性(关键约束 7)。
    """
    try:
        fid = uuid.UUID(file_id)
        sid = uuid.UUID(submitter_id)
    except ValueError:
        raise NotFoundError("文件不存在")

    kf = db.get(KnowledgeFile, fid)
    if kf is None or kf.uploader_id != sid:
        raise NotFoundError("文件不存在")

    # 幂等:已有 pending 工单则返回旧的
    existing = db.scalar(
        select(KnowledgeReview).where(
            (KnowledgeReview.file_id == fid)
            & (KnowledgeReview.status == "pending")
        )
    )
    if existing is not None:
        return existing

    review = KnowledgeReview(
        submitter_id=sid, file_id=fid,
        source_type=source_type, status="pending",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def list_personal_files(db: Session, *, user_id) -> list[KnowledgeFile]:
    """列出 user 的个人库文件。"""
    return list(db.scalars(
        select(KnowledgeFile).where(
            (KnowledgeFile.uploader_id == user_id)
            & (KnowledgeFile.scope == "personal")
        ).order_by(KnowledgeFile.created_at.desc())
    ))


def list_global_files(db: Session) -> list[KnowledgeFile]:
    """列出全局库文件(所有登录 user 可见)。"""
    return list(db.scalars(
        select(KnowledgeFile).where(KnowledgeFile.scope == "global")
        .order_by(KnowledgeFile.created_at.desc())
    ))


def delete_global_file(db: Session, *, storage: Storage, file_id: str) -> None:
    """admin 删除全局库文件。

    删除三件套:KnowledgeFile 记录 + minio 对象 + 关联 KnowledgeChunk。
    仅限 scope=global 的文件(防误删 personal)。
    硬删除,不可恢复——前端必须带确认 Dialog。
    """
    try:
        fid = uuid.UUID(file_id)
    except ValueError:
        raise NotFoundError("文件不存在")

    kf = db.get(KnowledgeFile, fid)
    if kf is None:
        raise NotFoundError("文件不存在")
    if kf.scope != "global":
        raise ValidationError("仅可删除全局库文件")

    # 1. 删关联 chunk(file_id FK 是 SET NULL,不会级联,需手动)
    from sqlalchemy import delete as sa_delete
    db.execute(
        sa_delete(KnowledgeChunk).where(KnowledgeChunk.file_id == fid)
    )

    # 2. 删 minio 对象(失败不阻塞 DB 删除)
    try:
        storage.delete(kf.bucket, kf.object_key)
    except Exception:
        pass

    # 3. 删 KnowledgeFile 记录
    db.delete(kf)
    db.commit()


def submit_disclosure_for_review(
    db: Session, *, storage: Storage, submitter, project,
) -> KnowledgeReview:
    """归档交底书上报进全局(审核流 A)。

    关键约束 4:归档交底书无源文件,上报时生成导出 docx 存 minio。
    断链修复:建 KnowledgeFile 后,把该项目的 disclosure chunk 的 file_id
    关联到它——这样 approve 的 _update_chunks_scope(file_id=kf.id) 才能命中
    归档 chunk 并把它们升 global。否则归档 chunk file_id 永远为 NULL,审核通过也升不了。

    幂等:该 project 已有 pending 工单(disclosure_export)则返回旧的,不重复生成 docx。
    """
    from sqlalchemy import update

    from app.models import KnowledgeChunk as KC
    from app.services.export_service import export_docx

    # 幂等:已有 pending 的 disclosure_export 工单(关联此 project 的 chunk)→ 返回旧的
    existing = db.scalar(
        select(KnowledgeReview).where(
            (KnowledgeReview.source_type == "disclosure_export")
            & (KnowledgeReview.status == "pending")
            & (KnowledgeReview.submitter_id == submitter.id)
        )
    )
    # 进一步确认工单的 file 是否关联本 project(通过 chunk 的 source_id == project.id)
    if existing is not None:
        linked = db.scalar(
            select(KnowledgeFile).where(KnowledgeFile.id == existing.file_id)
        )
        if linked is not None:
            cnt = db.scalar(
                select(KC).where(
                    (KC.file_id == linked.id)
                    & (KC.source_id == project.id)
                    & (KC.source_type == "disclosure")
                )
            )
            if cnt is not None:
                return existing

    docx_bytes = export_docx(db, project=project)
    object_key = f"global/{uuid.uuid4()}.docx"
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    storage.put("global", object_key, docx_bytes, mime)

    import hashlib

    kf = KnowledgeFile(
        uploader_id=submitter.id,
        scope="global",  # 文件已在 global bucket(归档流特点)
        bucket="global",
        object_key=object_key,
        filename=f"{project.title}.docx",
        mime_type=mime, size=len(docx_bytes),
        source_type="disclosure_export",
        content_hash=hashlib.sha256(docx_bytes).hexdigest(),
    )
    db.add(kf)
    db.flush()

    # ★ 断链修复:把该 project 的归档 chunk 关联到新建的 kf
    # (之前 file_id 为 NULL,approve 按 file_id 改 scope 改不到它们)
    db.execute(
        update(KC).where(
            (KC.source_id == project.id)
            & (KC.source_type == "disclosure")
            & (KC.user_id == submitter.id)
        ).values(file_id=kf.id)
    )

    review = KnowledgeReview(
        submitter_id=submitter.id, file_id=kf.id,
        source_type="disclosure_export", status="pending",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def list_chunks_by_file(db: Session, *, file_id) -> list[KnowledgeChunk]:
    """列出某文件的所有 chunk（按 chunk_index 排序）。

    file_id 可以是 UUID 或 str（admin 端点路径参数是 str，转成 UUID 查询）。
    """
    fid = uuid.UUID(str(file_id)) if not isinstance(file_id, uuid.UUID) else file_id
    return db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.source_id == fid)
        .order_by(KnowledgeChunk.chunk_index)
    ).scalars().all()


def update_chunk(
    db: Session, *, chunk_id, payload: dict, force_unlock: bool = False
) -> KnowledgeChunk:
    """admin 编辑 chunk（D8：edited_text 变更触发重 embed + tsv 重生成）。

    locked=True 的 chunk 不允许编辑 edited_text（除非 force_unlock）。
    payload 的 key 只认 keywords/questions/weight/edited_text/locked。
    """
    cid = uuid.UUID(str(chunk_id)) if not isinstance(chunk_id, uuid.UUID) else chunk_id
    chunk = db.get(KnowledgeChunk, cid)
    if not chunk:
        raise ValueError("chunk not found")
    if chunk.locked and not force_unlock and "edited_text" in payload:
        raise PermissionError("chunk locked")

    old_edited = chunk.edited_text
    if "keywords" in payload:
        chunk.keywords = payload["keywords"]
    if "questions" in payload:
        chunk.questions = payload["questions"]
    if "weight" in payload:
        chunk.weight = payload["weight"]
    if "edited_text" in payload:
        chunk.edited_text = payload["edited_text"] or None  # 空串归一化为 None（表示用原 content）
    if "locked" in payload:
        chunk.locked = payload["locked"]

    # D8：edited_text 变更触发重 embed + tsv 重生成
    needs_reembed = chunk.edited_text != old_edited
    needs_tsv_regen = needs_reembed or "keywords" in payload or "questions" in payload

    if needs_reembed and chunk.edited_text:
        embed_config = resolve_embedding_config(db, user_id=chunk.user_id)
        if embed_config:
            vec = embed_texts([chunk.edited_text], embed_config=embed_config)[0]
            chunk.embedding = vec

    db.commit()

    # tsv 重生成（仅 PG，edited_text + keywords + questions 都进 tsv）
    if is_postgres() and needs_tsv_regen:
        text_for_tsv = chunk.edited_text or chunk.content
        extra = " ".join((chunk.keywords or []) + (chunk.questions or []))
        db.execute(sa_text(
            "UPDATE knowledge_chunks SET tsv = to_tsvector('simple', :txt) WHERE id = :cid"
        ), {"txt": text_for_tsv + " " + extra, "cid": str(chunk.id)})
        db.commit()

    db.refresh(chunk)
    return chunk


# ────────────────────────── 内部辅助(落库/embed 分离) ──────────────────────────


def _write_chunks_unembedded(
    db: Session, *, scope: str, user_id, file_id, source_type: str,
    text: str, title: str,
) -> list[KnowledgeChunk]:
    """分块 + 写 chunk(embedding=None)+ tsv。不调 embed_texts,同步快。

    异步向量化:向量化交给 embed_chunks_for_file / run_embed_job_standalone 后台做。
    返回写入的 chunk 列表(embedding 待填)。
    """
    chunks = chunk_sections([{"key": None, "title": title, "content": text}])
    if not chunks:
        return []
    written: list[KnowledgeChunk] = []
    for c in chunks:
        chunk = KnowledgeChunk(
            user_id=user_id, scope=scope, file_id=file_id,
            source_type=source_type, source_id=file_id,
            source_section_key=c.section_key, chunk_index=c.chunk_index,
            content=c.content, embedding=None,  # 待后台 embed 填充
            metadata_={"title": title},
        )
        db.add(chunk)
        written.append(chunk)

    # G3：生成 tsv（仅 PG）；embedding 此时为空，但 tsv 不依赖 embedding
    if is_postgres() and file_id:
        db.execute(sa_text(
            "UPDATE knowledge_chunks SET tsv = to_tsvector('simple', coalesce(content, '')) "
            "WHERE tsv IS NULL AND file_id = :fid"
        ), {"fid": str(file_id)})
    return written


def embed_chunks_for_file(db: Session, *, file_id) -> int:
    """对该 file 的所有 embedding 为 None 的 chunk 批量向量化并回填。

    长耗时操作，由 run_embed_job_standalone 在后台调用。返回已向量化的 chunk 数。
    向量化配置由 file.uploader_id 解析。无配置或 chunk 为空时返回 0。
    """
    fid = uuid.UUID(str(file_id)) if not isinstance(file_id, uuid.UUID) else file_id
    kf = db.get(KnowledgeFile, fid)
    if kf is None:
        raise NotFoundError("文件不存在")

    chunks = db.execute(
        select(KnowledgeChunk)
        .where((KnowledgeChunk.file_id == fid) & (KnowledgeChunk.embedding.is_(None)))
    ).scalars().all()
    if not chunks:
        return 0

    embed_config = resolve_embedding_config(db, user_id=kf.uploader_id)
    if embed_config is None:
        # 无配置：chunk 保持 embedding=None，不参与向量检索。视为完成（无可做的事）。
        return 0

    try:
        vectors = embed_texts([c.content for c in chunks], embed_config=embed_config)
    except Exception:
        # D7：embed 失败也记一条日志（仅元数据），再向上抛（由 standalone 兜底写 failed）
        log_embed_call(
            db, user_id=kf.uploader_id, model=embed_config.model,
            provider=embed_config.source, status="failed",
        )
        raise
    # D7：写 embedding 调用日志（让 admin 统计区分 chat/embedding）
    log_embed_call(
        db, user_id=kf.uploader_id, model=embed_config.model,
        provider=embed_config.source, status="success",
    )
    for c, vec in zip(chunks, vectors, strict=False):
        c.embedding = vec
    db.commit()
    return len(chunks)


# ── 异步向量化后台任务(standalone session 模式，镜像 parse_service)──


def run_embed_job_standalone(file_id: str) -> None:
    """供 BackgroundTasks / spawn_background_task 调用：自开 session 执行向量化。

    BackgroundTasks 在响应返回后才执行，此时请求作用域的 session 已关闭，
    因此必须自己开一个独立 session（详见设计 P0 #6，与 parse_service 同模式）。
    状态流转：置 processing/stage=embedding → embed → ready/stage=done/completed_at；
              异常 → failed/error_message。幂等：已是 ready 则跳过。
    """
    try:
        fid = uuid.UUID(file_id)
    except (ValueError, TypeError):
        logger.warning(f"run_embed_job_standalone 收到非法 file_id={file_id!r}，忽略")
        return

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        kf = db.get(KnowledgeFile, fid)
        if kf is None:
            logger.warning(f"run_embed_job_standalone: 文件 {file_id} 不存在，忽略")
            return
        if kf.status == "ready":
            logger.info(f"向量化任务 {file_id[:8]}... 已是 ready，跳过")
            return

        kf.status = "processing"
        kf.stage = "embedding"
        db.commit()

        n = embed_chunks_for_file(db, file_id=fid)
        logger.info(f"向量化任务 {file_id[:8]}... 完成，{n} 个 chunk 已向量化")

        kf.status = "ready"
        kf.stage = "done"
        kf.error_message = None
        kf.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        logger.exception(f"向量化任务 {file_id[:8]}... 失败：{e}")
        try:
            # 失败也回写状态（重新查，避免 session 脏）
            kf = db.get(KnowledgeFile, fid)
            if kf is not None:
                kf.status = "failed"
                kf.error_message = str(e)[:500]
                db.commit()
        except Exception:
            logger.exception(f"向量化任务 {file_id[:8]}... 写 failed 状态也失败")
    finally:
        db.close()


def recover_stale_files(stale_minutes: int = 10) -> int:
    """启动恢复扫描：重启后重入队孤儿知识文件。

    1) status="processing" —— 上次崩溃中断（崩溃时正在跑）。
    2) status="pending" 且 created_at 早于 stale_minutes 分钟前 —— 队列卡住。

    run_embed_job_standalone 自带幂等：已是 ready 则跳过。
    返回重新入队的文件数。
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_, select

    from app.core.background import spawn_background_task
    from app.core.database import SessionLocal

    db = SessionLocal()
    count = 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        stmt = select(KnowledgeFile).where(
            or_(
                KnowledgeFile.status == "processing",
                (KnowledgeFile.status == "pending") & (KnowledgeFile.created_at < cutoff),
            )
        )
        files = list(db.scalars(stmt))
        for kf in files:
            spawn_background_task(run_embed_job_standalone, str(kf.id))
            count += 1
    finally:
        db.close()
    return count


def _source_type_for(filename: str) -> str:
    """根据扩展名定 source_type。"""
    ext = _ext(filename)
    if ext == "pdf":
        return "external_pdf"
    if ext == "docx":
        return "external_docx"
    return f"external_{ext or 'unknown'}"


def _ext(filename: str) -> str:
    """取小写扩展名(无点)。"""
    return filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
