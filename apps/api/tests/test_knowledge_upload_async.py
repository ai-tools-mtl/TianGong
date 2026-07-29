"""知识库上传异步化测试（plan async-knowledge-upload）。

核心验证：
1. upload_external/upload_to_global 落库后 status=pending/stage=uploaded（不 embed）
2. run_embed_job_standalone 状态流转：pending→processing→ready，幂等（ready 跳过）
3. 失败兜底：embed 异常 → status=failed + error_message

SQLite 测试库无 knowledge_chunks 表，_write_chunks_unembedded 被 mock 跳过 chunk 写入，
embed_chunks_for_file 也被 mock，专注验证状态机。
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.models import KnowledgeFile, User
from app.services import knowledge_service as ks


@pytest.fixture
def admin_user(db_session):
    u = User(
        username="admin", email="admin@tiangong.dev",
        password_hash=hash_password("P1!"), name="admin", role="admin",
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


@pytest.fixture
def normal_user(db_session, registered_user):
    return db_session.get(User, uuid.UUID(registered_user["id"]))


@pytest.fixture(autouse=True)
def _skip_chunk_write(monkeypatch):
    """跳过 chunk 写入（SQLite 无 knowledge_chunks 表）。"""
    monkeypatch.setattr(ks, "_write_chunks_unembedded", lambda *a, **kw: [])


# ── 落库阶段：status=pending / stage=uploaded ──


def test_upload_external_leaves_pending_status(db_session, normal_user):
    """upload_external 落库后 status=pending, stage=uploaded（未向量化）。"""
    storage = MagicMock()
    kf = ks.upload_external(
        db_session, storage=storage, user=normal_user,
        filename="ref.docx", content=b"x", mime="application/docx", text="内容",
    )
    db_session.refresh(kf)
    assert kf.status == "pending"
    assert kf.stage == "uploaded"
    assert kf.completed_at is None
    assert kf.error_message is None


def test_upload_to_global_leaves_pending_status(db_session, admin_user):
    """upload_to_global 落库后 status=pending, stage=uploaded。"""
    storage = MagicMock()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="case.pdf", content=b"%PDF unique", mime="application/pdf", text="案例",
    )
    db_session.refresh(kf)
    assert kf.status == "pending"
    assert kf.stage == "uploaded"


# ── run_embed_job_standalone 状态流转 ──


def test_run_embed_job_standalone_marks_ready(db_session, admin_user, engine, monkeypatch):
    """run_embed_job_standalone 成功后 status=ready/stage=done/completed_at 填充。"""
    storage = MagicMock()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="case.pdf", content=b"%PDF unique-ready", mime="application/pdf", text="案例",
    )
    db_session.refresh(kf)
    assert kf.status == "pending"

    # mock SessionLocal 返回绑定测试 engine 的独立 session（standalone 自开 session，
    # 不能复用 db_session，否则 finally close 会关掉测试 session）
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(ks, "embed_chunks_for_file", lambda db, *, file_id: 3)

    ks.run_embed_job_standalone(str(kf.id))

    # standalone 用独立 session 提交，这里重新查验证状态
    db_session.expire_all()
    kf2 = db_session.get(KnowledgeFile, kf.id)
    assert kf2.status == "ready"
    assert kf2.stage == "done"
    assert kf2.completed_at is not None
    assert kf2.error_message is None


def test_run_embed_job_standalone_idempotent_ready(db_session, admin_user, engine, monkeypatch):
    """已是 ready 的文件，再次 run 直接跳过（幂等），不重复 embed。"""
    storage = MagicMock()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="case.pdf", content=b"%PDF unique-idem", mime="application/pdf", text="案例",
    )
    kf.status = "ready"; kf.stage = "done"
    db_session.commit()

    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    called = []
    monkeypatch.setattr(ks, "embed_chunks_for_file", lambda *a, **kw: called.append(1) or 0)

    ks.run_embed_job_standalone(str(kf.id))

    db_session.expire_all()
    kf2 = db_session.get(KnowledgeFile, kf.id)
    assert kf2.status == "ready"  # 未变
    assert called == []  # embed 未被调用（幂等跳过）


def test_run_embed_job_standalone_failed_marks_error(db_session, admin_user, engine, monkeypatch):
    """embed 异常 → status=failed + error_message 填充。"""
    storage = MagicMock()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="case.pdf", content=b"%PDF unique-fail", mime="application/pdf", text="案例",
    )
    db_session.refresh(kf)

    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(ks, "embed_chunks_for_file", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("embedding 服务连接失败")))

    ks.run_embed_job_standalone(str(kf.id))

    db_session.expire_all()
    kf2 = db_session.get(KnowledgeFile, kf.id)
    assert kf2.status == "failed"
    assert kf2.error_message is not None
    assert "连接失败" in kf2.error_message


def test_run_embed_job_standalone_ignores_bad_id(monkeypatch):
    """非法 file_id 不抛异常，静默忽略（后台任务不能因坏输入崩溃）。"""
    # 不应抛异常
    ks.run_embed_job_standalone("not-a-uuid")
    ks.run_embed_job_standalone(str(uuid.uuid4()))  # 不存在的文件也静默
