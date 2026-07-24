"""知识库三域 CRUD + 上报(计划 T9)。

三域(关键约束 1):
- upload_to_global: admin 直传,scope=global,bucket=global,全员可检索
- upload_external: user 上传外部素材,scope=personal,bucket=personal
- (归档流由 archive_service 写 scope=personal,此处不涉及)

上报(关键约束 2):submit_for_review 建 KnowledgeReview(pending),
  admin 审核在 review_service(T10)处理。

chunk 写入复用 chunker + embedding。注意:SQLite 测试库跳过
knowledge_chunks 表,本模块的 chunk 写入在 PG 集成验证。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.storage import Storage
from app.models import KnowledgeChunk, KnowledgeFile, KnowledgeReview
from app.rag.chunker import chunk_sections
from app.rag.embedding import embed_texts
from app.services.llm_config_service import resolve_embedding_config


def upload_to_global(
    db: Session, *, storage: Storage, uploader, filename: str,
    content: bytes, mime: str, text: str,
) -> KnowledgeFile:
    """admin 直传全局库。生成 file + chunk(scope=global),全员可检索。

    全局库去重:按 content_hash(SHA256)查重,已存在则返回已有记录,
    不重复存储/向量化(防 admin 反复上传同一文件导致检索结果重复)。
    """
    import hashlib

    source_type = _source_type_for(filename)
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
    )
    db.add(kf)
    db.flush()  # 让 kf.id 就位
    _ingest_chunks(
        db, scope="global", user_id=uploader.id, file_id=kf.id,
        source_type=source_type, text=text, title=filename,
    )
    db.commit()
    db.refresh(kf)
    return kf


def upload_external(
    db: Session, *, storage: Storage, user, filename: str,
    content: bytes, mime: str, text: str,
) -> KnowledgeFile:
    """user 上传外部素材进个人库。scope=personal,仅本人可检索。"""
    source_type = _source_type_for(filename)
    object_key = f"personal/{user.id}/{uuid.uuid4()}.{_ext(filename)}"
    storage.put("personal", object_key, content, mime)

    import hashlib

    kf = KnowledgeFile(
        uploader_id=user.id, scope="personal", bucket="personal",
        object_key=object_key, filename=filename, mime_type=mime,
        size=len(content), source_type=source_type,
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    db.add(kf)
    db.flush()
    _ingest_chunks(
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


# ────────────────────────── 内部辅助 ──────────────────────────


def _ingest_chunks(
    db: Session, *, scope: str, user_id, file_id, source_type: str,
    text: str, title: str,
) -> None:
    """分块 + 向量化 + 写 chunk(关联 file)。

    向量化配置由 user_id 内部解析（断链修复：embed 真用自定义/全局/env 配置）。
    无可用配置时跳过向量化但 chunk 仍写入（embedding=None），检索时该 chunk 不命中。
    """
    chunks = chunk_sections([{"key": None, "title": title, "content": text}])
    if not chunks:
        return
    embed_config = resolve_embedding_config(db, user_id=user_id)
    if embed_config is None:
        # 无 LLM 配置：chunk 仍入库（embedding=None），该 chunk 不参与向量检索
        vectors: list[list[float] | None] = [None] * len(chunks)
    else:
        vectors = embed_texts([c.content for c in chunks], embed_config=embed_config)
    for c, vec in zip(chunks, vectors, strict=False):
        db.add(KnowledgeChunk(
            user_id=user_id, scope=scope, file_id=file_id,
            source_type=source_type, source_id=file_id,
            source_section_key=c.section_key, chunk_index=c.chunk_index,
            content=c.content, embedding=vec,
            metadata_={"title": title},
        ))


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
