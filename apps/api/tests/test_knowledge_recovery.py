"""知识库孤儿任务恢复测试（plan async-knowledge-upload + async-parsing）。

验证 recover_stale_files：启动后重入队崩溃中断/超时 pending 的知识文件，
使其重新走"解析+分块+向量化"流水线。

- status=processing（上次崩溃中断）→ 重入队
- status=pending 且 created_at 超时（>stale_minutes）→ 重入队
- 新鲜 pending（未超时）→ 不动
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.models import KnowledgeFile, User
from app.services import knowledge_service as ks


def test_recover_stale_files_reenqueues_processing_and_stale_pending(
    db_session, monkeypatch
):
    """processing 直接重跑，pending 超时重跑，新 pending 不动。"""
    from app.core import database as db_module

    # 让 recover/run_embed_job_standalone 内部的 SessionLocal 指向测试库
    TestingSession = sessionmaker(bind=db_session.bind)
    monkeypatch.setattr(db_module, "SessionLocal", TestingSession)

    u = User(
        username="rec", email="rec@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="R", role="admin",
    )
    db_session.add(u)
    db_session.commit()

    now = datetime.now(timezone.utc)
    storage = MagicMock()

    # processing：崩溃中断
    kf_processing = ks.upload_to_global(
        db_session, storage=storage, uploader=u,
        filename="a.pdf", content=b"%PDF a", mime="application/pdf",
    )
    kf_processing.status = "processing"
    kf_processing.stage = "parsing"

    # 超时 pending：队列卡住（created_at 提前 20 分钟）
    kf_stale = ks.upload_to_global(
        db_session, storage=storage, uploader=u,
        filename="b.pdf", content=b"%PDF b-unique", mime="application/pdf",
    )
    kf_stale.created_at = now - timedelta(minutes=20)

    # 新鲜 pending：未超时，不应被重入队
    kf_fresh = ks.upload_to_global(
        db_session, storage=storage, uploader=u,
        filename="c.pdf", content=b"%PDF c-unique", mime="application/pdf",
    )
    db_session.commit()

    # 用 fake_run 记录被调度的 file_id，避免真去解析/embed
    reloaded: list[str] = []

    def fake_run(file_id: str) -> None:
        reloaded.append(file_id)

    monkeypatch.setattr(ks, "run_embed_job_standalone", fake_run)

    n = ks.recover_stale_files()
    assert n == 2  # processing + 超时 pending 被重入队
    assert str(kf_processing.id) in reloaded
    assert str(kf_stale.id) in reloaded
    assert str(kf_fresh.id) not in reloaded  # 新 pending 不动


def test_recover_stale_files_handles_empty(db_session, monkeypatch):
    """无孤儿文件时返回 0，不抛异常。"""
    from app.core import database as db_module

    TestingSession = sessionmaker(bind=db_session.bind)
    monkeypatch.setattr(db_module, "SessionLocal", TestingSession)

    n = ks.recover_stale_files()
    assert n == 0


def test_recover_stale_files_bad_existing_id():
    """recover 内部 run_embed_job_standalone 收到非法 id 静默忽略（不崩溃）。
    不依赖 db（非法 id 在开 session 前就返回）。"""
    # 直接调 standalone，非法 id 不应抛
    ks.run_embed_job_standalone("not-a-uuid")
    ks.run_embed_job_standalone(str(uuid.uuid4()))  # 不存在的文件也静默
