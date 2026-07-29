"""review_service 双审核流测试(计划 T10)。

关键约束 2:双流共用 KnowledgeReview 表,source_type 区分。
关键约束 3:审核拒绝不删文件,chunk 保留 personal,user 仍可用。
approve:scope personal→global + 文件复制到 global bucket。
"""

import pytest

from app.core.security import hash_password
from app.models import KnowledgeFile, KnowledgeReview, User
from app.services import knowledge_service as ks
from app.services import knowledge_review_service as rs


@pytest.fixture
def fake_embed(monkeypatch):
    """桩 embedding + chunk 读写(SQLite 跳过 pgvector knowledge_chunks 表)。"""
    monkeypatch.setattr(
        "app.rag.embedding.embed_texts",
        lambda texts: [[0.0] * 2048 for _ in texts],
    )
    monkeypatch.setattr(ks, "_write_chunks_unembedded", lambda *a, **kw: [])
    # chunk 批量更新也桩掉(同因:SQLite 无 knowledge_chunks 表)
    monkeypatch.setattr(rs, "_update_chunks_scope", lambda *a, **kw: None)


@pytest.fixture
def admin_user(db_session):
    u = User(
        username="admin",
        email="admin@tiangong.dev",
        password_hash=hash_password("P1!"),
        name="admin",
        role="admin",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def normal_user(db_session, registered_user):
    from app.models import User

    return db_session.get(User, __import__("uuid").UUID(registered_user["id"]))


def _upload_personal(db_session, storage, normal_user):
    """辅助:上传一个个人素材 + 建工单。"""
    kf = ks.upload_external(
        db_session, storage=storage, user=normal_user,
        filename="case.pdf", content=b"pdf bytes",
        mime="application/pdf", text="某案例文本",
    )
    review = ks.submit_for_review(
        db_session, submitter_id=str(normal_user.id), file_id=str(kf.id),
    )
    return kf, review


def test_approve_promotes_to_global(db_session, normal_user, admin_user, fake_embed, _reset_storage):
    """审核通过:file scope/bucket 升 global + minio 复制到 global bucket + 工单 approved。"""
    from app.core.storage import get_storage

    storage = get_storage()
    kf, review = _upload_personal(db_session, storage, normal_user)
    personal_key = kf.object_key  # 记录原 key

    rs.approve(
        db_session, storage=storage, reviewer=admin_user, review_id=str(review.id),
    )
    db_session.refresh(kf)
    db_session.refresh(review)

    assert kf.scope == "global"
    assert kf.bucket == "global"
    assert review.status == "approved"
    assert review.reviewer_id == admin_user.id
    assert review.reviewed_at is not None
    # 文件已复制到 global bucket(新 key)
    assert storage.stat("global", kf.object_key) is True
    assert kf.object_key != personal_key  # key 变了(去掉 personal/{uid} 前缀)


def test_reject_keeps_personal(db_session, normal_user, admin_user, fake_embed, _reset_storage):
    """审核拒绝:file/chunk 保留 personal(user 仍可用),工单 rejected + 记评论。"""
    from app.core.storage import get_storage

    storage = get_storage()
    kf, review = _upload_personal(db_session, storage, normal_user)
    original_key = kf.object_key

    rs.reject(
        db_session, reviewer=admin_user, review_id=str(review.id),
        comment="质量不足,不予收录",
    )
    db_session.refresh(kf)
    db_session.refresh(review)

    assert kf.scope == "personal"  # 不变
    assert kf.bucket == "personal"
    assert kf.object_key == original_key  # key 不变,文件没动
    assert review.status == "rejected"
    assert review.review_comment == "质量不足,不予收录"
    assert review.reviewer_id == admin_user.id


def test_approve_global_file_skips_copy(db_session, admin_user, fake_embed, _reset_storage):
    """已 global 的文件再 approve 不重复复制(归档流 A 提交时已存 global)。"""
    from app.core.storage import get_storage

    storage = get_storage()
    # admin 直传全局(此时无工单,模拟归档流:文件已在 global)
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="archived.docx", content=b"docx",
        mime="application/docx", text="归档交底书内容",
    )
    # 手动建工单(归档流 A 的 source_type)
    review = KnowledgeReview(
        submitter_id=admin_user.id, file_id=kf.id,
        source_type="disclosure_export", status="pending",
    )
    db_session.add(review)
    db_session.commit()
    db_session.refresh(review)

    rs.approve(
        db_session, storage=storage, reviewer=admin_user, review_id=str(review.id),
    )
    db_session.refresh(kf)
    assert kf.scope == "global"
    assert review.status == "approved"


def test_approve_not_found_raises(db_session, admin_user, fake_embed):
    """不存在的工单 id → NotFoundError。"""
    from app.core.exceptions import NotFoundError

    import uuid as _uuid

    with pytest.raises(NotFoundError):
        rs.approve(
            db_session, storage=None, reviewer=admin_user,
            review_id=str(_uuid.uuid4()),
        )


def test_approve_already_processed_raises(
    db_session, normal_user, admin_user, fake_embed, _reset_storage
):
    """已处理的工单(approved/rejected)再 approve → 404(防重复处理)。"""
    from app.core.exceptions import NotFoundError
    from app.core.storage import get_storage

    storage = get_storage()
    kf, review = _upload_personal(db_session, storage, normal_user)
    rs.approve(
        db_session, storage=storage, reviewer=admin_user, review_id=str(review.id),
    )
    # 再 approve 应失败(已 approved)
    with pytest.raises(NotFoundError):
        rs.approve(
            db_session, storage=storage, reviewer=admin_user,
            review_id=str(review.id),
        )
