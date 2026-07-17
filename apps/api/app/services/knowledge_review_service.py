"""知识库审核流(计划 T10)。

注意:本模块是「知识库上报审核」,与 review_service.py(交底书质量 Rubric 评分)
是两个完全不同的子系统,勿混淆。

关键约束 2:双流共用 KnowledgeReview 表,靠 source_type 区分。
- 流 A(disclosure_export 归档):提交时文件已在 global bucket,approve 只改 scope
- 流 B(external 外部导入):提交时文件在 personal bucket,approve 时复制到 global

关键约束 3:拒绝不删文件,chunk/file 保留 personal,user 继续可用。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.storage import Storage
from app.models import KnowledgeChunk, KnowledgeFile, KnowledgeReview


def approve(
    db: Session, *, storage: Storage, reviewer, review_id: str,
) -> KnowledgeReview:
    """审核通过。

    流 B(personal 文件):copy 到 global bucket + 删旧 personal 对象 + 改 kf.bucket/key/scope。
    流 A(文件已在 global):仅改 scope。
    chunk 批量 scope→global, review_status→approved。
    """
    review = _get_pending(db, review_id)
    kf = db.get_one(KnowledgeFile, review.file_id)

    if kf.bucket == "personal":
        # 流 B:复制文件 personal → global,再删旧 personal 对象(防存储泄漏)
        old_key = kf.object_key
        new_key = _to_global_key(kf.object_key, kf.uploader_id)
        storage.copy("personal", old_key, "global", new_key)
        storage.delete("personal", old_key)  # 清理旧对象
        kf.bucket = "global"
        kf.object_key = new_key

    kf.scope = "global"
    # chunk 批量升 global(ORM 查询改,SQLite 兼容版表也能跑)
    _update_chunks_scope(db, file_id=kf.id, scope="global", review_status="approved")

    review.status = "approved"
    review.reviewer_id = reviewer.id
    review.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(review)
    return review


def reject(
    db: Session, *, reviewer, review_id: str, comment: str | None = None,
) -> KnowledgeReview:
    """审核拒绝。file/chunk 保留 personal(user 仍可用,关键约束 3)。"""
    review = _get_pending(db, review_id)
    kf = db.get_one(KnowledgeFile, review.file_id)

    # chunk 标 rejected 但 scope 不变(personal)
    _update_chunks_scope(db, file_id=kf.id, scope=None, review_status="rejected")

    review.status = "rejected"
    review.reviewer_id = reviewer.id
    review.review_comment = comment
    review.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(review)
    return review


def _update_chunks_scope(
    db: Session, *, file_id, scope: str | None, review_status: str,
) -> None:
    """批量更新某 file 的 chunk 的 scope/review_status。

    用 ORM 查询逐条改(而非 __table__.update 裸 SQL),
    兼容 SQLite 测试库的 knowledge_chunks 兼容版表。
    scope=None 时只改 review_status(拒绝流:scope 不变)。
    """
    chunks = list(db.scalars(
        select(KnowledgeChunk).where(KnowledgeChunk.file_id == file_id)
    ))
    for c in chunks:
        c.review_status = review_status
        if scope is not None:
            c.scope = scope


def list_pending(db: Session) -> list[KnowledgeReview]:
    """待审核工单列表(时间倒序)。"""
    return list(db.scalars(
        select(KnowledgeReview).where(KnowledgeReview.status == "pending")
        .order_by(KnowledgeReview.created_at.desc())
    ))


def list_all_reviews(db: Session) -> list[KnowledgeReview]:
    """全部工单(含历史,admin 工作台用)。"""
    return list(db.scalars(
        select(KnowledgeReview).order_by(KnowledgeReview.created_at.desc())
    ))


# ────────────────────────── 内部辅助 ──────────────────────────


def _get_pending(db: Session, review_id: str) -> KnowledgeReview:
    """取 pending 工单,不存在或已处理返回 404(防重复处理)。"""
    try:
        rid = uuid.UUID(review_id)
    except (ValueError, TypeError):
        raise NotFoundError("工单不存在")
    review = db.get(KnowledgeReview, rid)
    if review is None or review.status != "pending":
        raise NotFoundError("工单不存在或已处理")
    return review


def _to_global_key(personal_key: str, uploader_id) -> str:
    """personal key → global key:去掉 personal/{uid}/ 前缀,加 global/。

    例:personal/{uid}/{uuid}.pdf → global/{uuid}.pdf
    """
    prefix = f"personal/{uploader_id}/"
    if personal_key.startswith(prefix):
        return f"global/{personal_key[len(prefix):]}"
    # 兜底:已是 global 或未知格式,直接加 global/ 前缀
    return personal_key if personal_key.startswith("global/") else f"global/{personal_key}"
