"""recover_pending_jobs + get_job + list_jobs 测试。"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import NotFoundError
from app.models import User, WebIngestionJob
from app.services import web_ingestion_service


# autouse fixture:patch SessionLocal 让 recover_pending_jobs 用测试 engine。
# recover_pending_jobs 内部自开 SessionLocal(生产 PG 引擎),不 patch 写不到测试库。
# 模式同 tests/test_web_ingestion_service_run.py 的 _patch_session_local。
@pytest.fixture(autouse=True)
def _patch_session_local(engine, monkeypatch):
    """让 web_ingestion_service 内的 SessionLocal 返回测试 session。"""
    from app.core import database as db_module
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine))


@pytest.fixture
def mock_user(db_session):
    """真 User(供 FK + 权限判断)。"""
    u = User(username=f"test_{uuid.uuid4().hex[:8]}", name="t",
             password_hash="x", email=f"test_{uuid.uuid4().hex[:8]}@tiangong.dev")
    db_session.add(u)
    db_session.flush()
    return u


def _make_job(db_session, *, user_id, status, scope="personal", mode="crawl",
              updated_at=None, created_at=None):
    job = WebIngestionJob(
        user_id=user_id, scope=scope, url="https://x.com", mode=mode,
        max_pages=10, firecrawl_job_id="fc-x", status=status,
    )
    if updated_at:
        job.updated_at = updated_at
    if created_at:
        job.created_at = created_at
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


# ── recover_pending_jobs ─────────────────────────────────────

@patch("app.services.web_ingestion_service.spawn_background_task")
def test_recover_spawns_for_stale_running(mock_spawn, db_session, mock_user):
    """running 且超时 → spawn。"""
    old_time = datetime.now(timezone.utc) - timedelta(hours=1)
    _make_job(db_session, user_id=mock_user.id, status="running", updated_at=old_time)
    count = web_ingestion_service.recover_pending_jobs()
    assert count == 1
    assert mock_spawn.call_count == 1


@patch("app.services.web_ingestion_service.spawn_background_task")
def test_recover_ignores_recent_running(mock_spawn, db_session, mock_user):
    """running 但未超时 → 不 spawn。"""
    _make_job(db_session, user_id=mock_user.id, status="running",
              updated_at=datetime.now(timezone.utc))  # 刚建
    count = web_ingestion_service.recover_pending_jobs()
    assert count == 0
    mock_spawn.assert_not_called()


@patch("app.services.web_ingestion_service.spawn_background_task")
def test_recover_spawns_for_stale_pending(mock_spawn, db_session, mock_user):
    """pending 且超时 → spawn。"""
    old_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    _make_job(db_session, user_id=mock_user.id, status="pending", created_at=old_time)
    count = web_ingestion_service.recover_pending_jobs()
    assert count == 1


@patch("app.services.web_ingestion_service.spawn_background_task")
def test_recover_ignores_completed_failed(mock_spawn, db_session, mock_user):
    """completed/failed 不重入队。"""
    _make_job(db_session, user_id=mock_user.id, status="completed")
    _make_job(db_session, user_id=mock_user.id, status="failed")
    count = web_ingestion_service.recover_pending_jobs()
    assert count == 0


# ── get_job ──────────────────────────────────────────────────

def test_get_job_returns_own(db_session, mock_user):
    """owner 可查。"""
    job = _make_job(db_session, user_id=mock_user.id, status="running")
    got = web_ingestion_service.get_job(db_session, job_id=str(job.id), user=mock_user)
    assert got.id == job.id


def test_get_job_404_on_others(db_session, mock_user):
    """非 owner 查他人 job → 404(不暴露存在性)。"""
    other_uid = uuid.uuid4()
    job = _make_job(db_session, user_id=other_uid, status="running")
    with pytest.raises(NotFoundError):
        web_ingestion_service.get_job(db_session, job_id=str(job.id), user=mock_user)


def test_get_job_404_on_missing(db_session, mock_user):
    """不存在的 id → 404。"""
    with pytest.raises(NotFoundError):
        web_ingestion_service.get_job(db_session, job_id=str(uuid.uuid4()), user=mock_user)


def test_get_job_admin_can_see_others(db_session, mock_user):
    """admin 可查他人 job(运营审计)。"""
    admin = User(username="admin_test", name="a", password_hash="x",
                 email="admin_test@tiangong.dev", role="admin")
    db_session.add(admin)
    db_session.flush()
    job = _make_job(db_session, user_id=mock_user.id, status="running")
    got = web_ingestion_service.get_job(db_session, job_id=str(job.id), user=admin)
    assert got.id == job.id


# ── list_jobs ────────────────────────────────────────────────

def test_list_jobs_returns_own_only(db_session, mock_user):
    """只列本人的。"""
    other_uid = uuid.uuid4()
    _make_job(db_session, user_id=mock_user.id, status="running")
    _make_job(db_session, user_id=mock_user.id, status="completed")
    _make_job(db_session, user_id=other_uid, status="running")
    jobs = web_ingestion_service.list_jobs(db_session, user=mock_user)
    assert len(jobs) == 2
    assert all(j.user_id == mock_user.id for j in jobs)
