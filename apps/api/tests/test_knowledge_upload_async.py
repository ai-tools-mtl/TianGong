"""知识库上传异步化测试（plan async-knowledge-upload + async-parsing）。

核心验证：
1. upload_external/upload_to_global 落库后 status=pending/stage=uploaded（不解析、不分块、不 embed）
2. run_embed_job_standalone 状态流转：
   pending→processing(parsing)→processing(embedding)→ready(done)，幂等（ready 跳过）
3. 解析分流：external_web 走 decode；external_pdf/external_docx 走 extract_text
4. 失败兜底：解析/embed 异常 → status=failed + error_message

SQLite 测试库无 knowledge_chunks 表（_write_chunks_unembedded 被 mock 跳过：
其内部 to_tsvector 是 PG 专用），extract_text 和 embed_chunks_for_file 也被 mock，
专注验证状态机与解析分流。chunk 真实写入由 PG 集成验证。
"""

import uuid
from unittest.mock import MagicMock

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
    """跳过 chunk 写入（SQLite 无 knowledge_chunks 表；且 _write_chunks_unembedded 内
    的 to_tsvector 是 PG 专用，SQLite 跑会报 no such function）。chunk 真实写入由
    PG 集成验证。这里只验证状态机与解析分流。"""
    monkeypatch.setattr(ks, "_write_chunks_unembedded", lambda *a, **kw: [])


# ── 落库阶段：status=pending / stage=uploaded（不解析、不分块）──


def test_upload_external_leaves_pending_status(db_session, normal_user):
    """upload_external 落库后 status=pending, stage=uploaded（未解析、未向量化）。"""
    storage = MagicMock()
    kf = ks.upload_external(
        db_session, storage=storage, user=normal_user,
        filename="ref.docx", content=b"x", mime="application/docx",
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
        filename="case.pdf", content=b"%PDF unique", mime="application/pdf",
    )
    db_session.refresh(kf)
    assert kf.status == "pending"
    assert kf.stage == "uploaded"


# ── run_embed_job_standalone 状态流转（解析+分块+向量化统一后台）──


def _bind_standalone_session(monkeypatch, engine):
    """standalone 自开 session，必须指向测试 engine，不能复用 db_session。

    否则 finally close 会关掉测试 session（详见设计 P0 #6）。
    """
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))


@pytest.fixture
def _mock_extract_and_embed(monkeypatch):
    """桩掉解析与向量化（真实分块走 SQLite 兼容表）。

    extract_text 默认返回固定文本；可被单测用 monkeypatch 二次覆盖。
    返回一个 calls 字典，记录 extract_text 被调用时的 filename。
    """
    calls = {"extract": [], "embed": []}
    import app.parsing.dispatcher as dispatcher
    monkeypatch.setattr(
        dispatcher, "extract_text",
        lambda filename, content, db=None: (calls["extract"].append(filename) or "解析后的文本"),
    )
    monkeypatch.setattr(ks, "embed_chunks_for_file", lambda db, *, file_id: (calls["embed"].append(1) or 3))
    return calls


def test_standalone_marks_ready_through_parsing_and_embedding(
    db_session, admin_user, engine, monkeypatch, _mock_extract_and_embed
):
    """run_embed_job_standalone 成功后 status=ready/stage=done/completed_at 填充。

    走完整链路：读回 content → 解析（parsing）→ 分块 → 向量化（embedding）→ ready。
    """
    storage = MagicMock()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="case.pdf", content=b"%PDF unique-ready", mime="application/pdf",
    )
    db_session.refresh(kf)
    assert kf.status == "pending"

    _bind_standalone_session(monkeypatch, engine)

    ks.run_embed_job_standalone(str(kf.id))

    # 解析被调用（pdf/docx 走 extract_text）
    assert _mock_extract_and_embed["extract"] == ["case.pdf"]
    assert _mock_extract_and_embed["embed"] == [1]

    # standalone 用独立 session 提交，这里重新查验证状态
    db_session.expire_all()
    kf2 = db_session.get(KnowledgeFile, kf.id)
    assert kf2.status == "ready"
    assert kf2.stage == "done"
    assert kf2.completed_at is not None
    assert kf2.error_message is None


def test_standalone_idempotent_ready(db_session, admin_user, engine, monkeypatch, _mock_extract_and_embed):
    """已是 ready 的文件，再次 run 直接跳过（幂等），不重复解析/向量化。"""
    storage = MagicMock()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="case.pdf", content=b"%PDF unique-idem", mime="application/pdf",
    )
    kf.status = "ready"; kf.stage = "done"
    db_session.commit()

    _bind_standalone_session(monkeypatch, engine)

    ks.run_embed_job_standalone(str(kf.id))

    db_session.expire_all()
    kf2 = db_session.get(KnowledgeFile, kf.id)
    assert kf2.status == "ready"  # 未变
    assert _mock_extract_and_embed["extract"] == []  # 未解析（幂等跳过）
    assert _mock_extract_and_embed["embed"] == []  # 未向量化


def test_standalone_pdf_failure_marks_failed(db_session, admin_user, engine, monkeypatch):
    """解析异常 → status=failed + error_message 填充。"""
    storage = MagicMock()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="case.pdf", content=b"%PDF unique-parsefail", mime="application/pdf",
    )
    db_session.refresh(kf)

    _bind_standalone_session(monkeypatch, engine)
    import app.parsing.dispatcher as dispatcher
    monkeypatch.setattr(
        dispatcher, "extract_text",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("MinerU 服务连接失败")),
    )

    ks.run_embed_job_standalone(str(kf.id))

    db_session.expire_all()
    kf2 = db_session.get(KnowledgeFile, kf.id)
    assert kf2.status == "failed"
    assert kf2.error_message is not None
    assert "连接失败" in kf2.error_message


def test_standalone_embed_failure_marks_failed(db_session, admin_user, engine, monkeypatch):
    """向量化异常 → status=failed + error_message 填充。"""
    storage = MagicMock()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="case.pdf", content=b"%PDF unique-embedfail", mime="application/pdf",
    )
    db_session.refresh(kf)

    _bind_standalone_session(monkeypatch, engine)
    import app.parsing.dispatcher as dispatcher
    monkeypatch.setattr(dispatcher, "extract_text", lambda *a, **kw: "解析文本")
    monkeypatch.setattr(ks, "embed_chunks_for_file", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("embedding 超时")))

    ks.run_embed_job_standalone(str(kf.id))

    db_session.expire_all()
    kf2 = db_session.get(KnowledgeFile, kf.id)
    assert kf2.status == "failed"
    assert kf2.error_message is not None
    assert "超时" in kf2.error_message


def test_standalone_web_source_skips_extract_text(
    db_session, admin_user, engine, monkeypatch, _mock_extract_and_embed
):
    """external_web 文件：读回 content 后直接 decode，不走 extract_text。"""
    storage = MagicMock()
    kf = ks.upload_to_global(
        db_session, storage=storage, uploader=admin_user,
        filename="page.md", content="# 标题\n正文".encode("utf-8"),
        mime="text/markdown", source_type_override="external_web",
    )
    db_session.refresh(kf)

    _bind_standalone_session(monkeypatch, engine)

    ks.run_embed_job_standalone(str(kf.id))

    # web 文件不走 extract_text（走 decode）
    assert _mock_extract_and_embed["extract"] == []
    assert _mock_extract_and_embed["embed"] == [1]

    db_session.expire_all()
    kf2 = db_session.get(KnowledgeFile, kf.id)
    assert kf2.status == "ready"
    assert kf2.stage == "done"


def test_standalone_ignores_bad_id(monkeypatch):
    """非法 file_id 不抛异常，静默忽略（后台任务不能因坏输入崩溃）。"""
    # 不应抛异常
    ks.run_embed_job_standalone("not-a-uuid")
    ks.run_embed_job_standalone(str(uuid.uuid4()))  # 不存在的文件也静默
