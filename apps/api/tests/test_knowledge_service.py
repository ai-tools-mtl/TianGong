"""knowledge_service 三域 CRUD + 上报测试(计划 T9)。

embedding 用 monkeypatch 返回固定零向量(关键约束 6),不真实调智谱。
SQLite 测试库跳过 knowledge_chunks 表(pgvector),所以这里只测
KnowledgeFile 创建 + KnowledgeReview 工单逻辑,chunk 写入走 PG 集成验证。
"""

import uuid

import pytest

from app.core.security import hash_password
from app.models import KnowledgeFile, KnowledgeReview, User
from app.services import knowledge_service as ks


@pytest.fixture
def fake_embed(monkeypatch):
    """embedding 返回固定 2048 维零向量,不真实调智谱。

    同时桩掉 knowledge_service._ingest_chunks:SQLite 测试库跳过
    knowledge_chunks 表(pgvector Vector 不支持),chunk 写入走 PG 集成验证。
    本测试套只验 KnowledgeFile/Review 的业务逻辑。
    """
    dim = 2048

    def _fake_texts(texts):
        return [[0.0] * dim for _ in texts]

    monkeypatch.setattr("app.rag.embedding.embed_texts", _fake_texts)
    # 桩掉 chunk 写入(表在 SQLite 不存在),仅记录调用参数供断言
    ingested: list[dict] = []

    def _fake_ingest(db, *, scope, user_id, file_id, source_type, text, title):
        ingested.append({
            "scope": scope, "file_id": file_id,
            "source_type": source_type, "text": text,
        })

    monkeypatch.setattr(ks, "_ingest_chunks", _fake_ingest)
    return {"ingested": ingested}


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
    """registered_user 返回 dict,这里取回 User 对象供 service 用。"""
    from app.models import User

    return db_session.get(User, uuid.UUID(registered_user["id"]))


def test_upload_to_global_creates_global_file(db_session, admin_user, fake_embed, _reset_storage):
    """admin 直传全局库:KnowledgeFile scope=global,文件存 global bucket,chunk 以 global 入库。"""
    from app.core.storage import get_storage

    storage = get_storage()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="case.pdf", content=b"%PDF-1.4 fake",
        mime="application/pdf", text="某专利技术方案详细描述",
    )
    db_session.refresh(kf)
    assert kf.scope == "global"
    assert kf.bucket == "global"
    assert kf.source_type == "external_pdf"
    assert kf.uploader_id == admin_user.id
    assert storage.stat("global", kf.object_key) is True
    # chunk 以 global scope 入库
    assert len(fake_embed["ingested"]) == 1
    assert fake_embed["ingested"][0]["scope"] == "global"


def test_upload_external_to_personal(db_session, normal_user, fake_embed, _reset_storage):
    """user 上传外部素材进个人库:scope=personal,文件存 personal bucket。"""
    from app.core.storage import get_storage

    storage = get_storage()
    kf = ks.upload_external(
        db_session, storage=storage, user=normal_user,
        filename="ref.docx", content=b"docx bytes",
        mime="application/docx", text="参考资料内容",
    )
    db_session.refresh(kf)
    assert kf.scope == "personal"
    assert kf.bucket == "personal"
    assert kf.source_type == "external_docx"
    assert kf.object_key.startswith(f"personal/{normal_user.id}/")
    assert storage.stat("personal", kf.object_key) is True


def test_submit_for_review_creates_pending(db_session, normal_user, fake_embed, _reset_storage):
    """user 上报个人素材,建 pending 工单。"""
    from app.core.storage import get_storage

    storage = get_storage()
    kf = ks.upload_external(
        db_session, storage=storage, user=normal_user,
        filename="ref.pdf", content=b"x", mime="application/pdf", text="案例",
    )
    review = ks.submit_for_review(
        db_session, submitter_id=str(normal_user.id), file_id=str(kf.id),
    )
    assert review.status == "pending"
    assert review.source_type == "external"
    assert review.submitter_id == normal_user.id
    assert review.file_id == kf.id


def test_submit_for_review_idempotent(db_session, normal_user, fake_embed, _reset_storage):
    """重复上报同一文件不建新工单,返回已有 pending 工单(幂等)。"""
    from app.core.storage import get_storage

    storage = get_storage()
    kf = ks.upload_external(
        db_session, storage=storage, user=normal_user,
        filename="ref.pdf", content=b"x", mime="application/pdf", text="案例",
    )
    r1 = ks.submit_for_review(
        db_session, submitter_id=str(normal_user.id), file_id=str(kf.id),
    )
    r2 = ks.submit_for_review(
        db_session, submitter_id=str(normal_user.id), file_id=str(kf.id),
    )
    assert r1.id == r2.id  # 同一工单

    # 库里只有一条 pending
    all_reviews = db_session.query(KnowledgeReview).filter_by(file_id=kf.id).all()
    assert len(all_reviews) == 1


def test_submit_for_review_rejects_not_owner(
    db_session, normal_user, fake_embed, _reset_storage
):
    """非文件 owner 上报 → 404(越权不暴露存在性,关键约束 7)。"""
    from app.core.exceptions import NotFoundError

    from app.core.storage import get_storage

    storage = get_storage()
    kf = ks.upload_external(
        db_session, storage=storage, user=normal_user,
        filename="ref.pdf", content=b"x", mime="application/pdf", text="案例",
    )
    # 造另一个用户
    other = User(username="other", email="other@test.com", password_hash=hash_password("P1!"), name="O")
    db_session.add(other)
    db_session.commit()

    with pytest.raises(NotFoundError):
        ks.submit_for_review(
            db_session, submitter_id=str(other.id), file_id=str(kf.id),
        )
