"""run_job / _poll_and_ingest / _ingest_crawl_pages 测试。"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import WebIngestionJob
from app.services.firecrawl_client import CrawlStatus, ResolvedFirecrawlConfig, ScrapeResult
from app.services import web_ingestion_service
from app.services.web_ingestion_service import run_job


@pytest.fixture(autouse=True)
def _patch_session_local(engine, monkeypatch):
    """让 run_job 内部 lazy import 的 SessionLocal 指向测试 sqlite 引擎。

    run_job 是 BackgroundTask 入口,自开独立 Session(对称 run_parse_job_standalone),
    默认 SessionLocal 绑定生产 Postgres 引擎。不 patch 的话 run_job 写不到测试库,
    db_session.refresh(job) 读不到变更。模式同 tests/test_parse_recovery.py。
    """
    from app.core import database as db_module
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine))


def _make_page(i: int = 1) -> ScrapeResult:
    return ScrapeResult(
        url=f"https://example.com/p{i}", title=f"页{i}",
        markdown=f"专利正文{i}" * 50, status_code=200, fetch_failed=False,
    )


@pytest.fixture
def fake_config():
    return ResolvedFirecrawlConfig(api_key="x", base_url="x", source="global")


def _create_running_job(db_session, user_id=None):
    """建一个 running 的 WebIngestionJob。"""
    job = WebIngestionJob(
        user_id=user_id or uuid.uuid4(),
        scope="global", url="https://example.com",
        mode="crawl", max_pages=50, firecrawl_job_id="fc-job-1",
        status="running",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@patch("app.services.web_ingestion_service.time.sleep")  # 跳过真实 sleep
@patch("app.services.web_ingestion_service.get_storage")
@patch("app.services.web_ingestion_service.knowledge_service.upload_to_global")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_run_job_polls_until_completed(
    mock_client_cls, mock_resolve, mock_upload, mock_storage, mock_sleep,
    db_session, fake_config,
):
    """前两次进行中,第三次完成 → job.completed + file_ids 填充。"""
    # 建一个真 User 供 job.user_id FK
    from app.models import User
    user = User(username="test_run1", name="t1", password_hash="x",
                email="test_run1@tiangong.dev")
    db_session.add(user)
    db_session.flush()
    job = _create_running_job(db_session, user_id=user.id)

    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.check_crawl.side_effect = [
        CrawlStatus(status="scraping", completed=5, total=50, pages=[], credits_used=0),
        CrawlStatus(status="scraping", completed=20, total=50, pages=[], credits_used=0),
        CrawlStatus(status="completed", completed=2, total=2,
                    pages=[_make_page(1), _make_page(2)], credits_used=2),
    ]
    mock_storage.return_value = MagicMock()
    mock_kf = MagicMock()
    mock_kf.id = uuid.uuid4()
    mock_upload.return_value = mock_kf

    run_job(str(job.id))

    db_session.refresh(job)
    assert job.status == "completed"
    assert job.pages_fetched == 2
    assert len(job.file_ids) == 2


@patch("app.services.web_ingestion_service.time.sleep")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_run_job_marks_failed_on_firecrawl_failure(
    mock_client_cls, mock_resolve, mock_sleep, db_session, fake_config,
):
    """Firecrawl 远端失败 → job.failed。"""
    from app.models import User
    user = User(username="test_run2", name="t2", password_hash="x",
                email="test_run2@tiangong.dev")
    db_session.add(user)
    db_session.flush()
    job = _create_running_job(db_session, user_id=user.id)

    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.check_crawl.return_value = CrawlStatus(
        status="failed", completed=10, total=50, pages=[], credits_used=10,
    )

    run_job(str(job.id))

    db_session.refresh(job)
    assert job.status == "failed"
    assert "Firecrawl 任务失败" in (job.error_message or "")


def test_run_job_idempotent_on_completed(db_session, fake_config):
    """已 completed 的 job 重跑无副作用。"""
    from app.models import User
    user = User(username="test_run3", name="t3", password_hash="x",
                email="test_run3@tiangong.dev")
    db_session.add(user)
    db_session.flush()
    job = _create_running_job(db_session, user_id=user.id)
    job.status = "completed"
    db_session.commit()

    with patch("app.services.web_ingestion_service.FirecrawlClient") as mock_cls:
        run_job(str(job.id))  # 不应抛,不应调 client
        mock_cls.assert_not_called()

    db_session.refresh(job)
    assert job.status == "completed"


@patch("app.services.web_ingestion_service.time.sleep")
@patch("app.services.web_ingestion_service.get_storage")
@patch("app.services.web_ingestion_service.knowledge_service.upload_to_global")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_run_job_filters_garbage_pages(
    mock_client_cls, mock_resolve, mock_upload, mock_storage, mock_sleep,
    db_session, fake_config,
):
    """垃圾页被过滤,pages_filtered 计数,只入库合格的。"""
    from app.models import User
    user = User(username="test_run4", name="t4", password_hash="x",
                email="test_run4@tiangong.dev")
    db_session.add(user)
    db_session.flush()
    job = _create_running_job(db_session, user_id=user.id)

    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    garbage = ScrapeResult(
        url="https://x/garbage", title="x", markdown="太短",
        status_code=200, fetch_failed=False,
    )
    good = _make_page()
    client.check_crawl.return_value = CrawlStatus(
        status="completed", completed=2, total=2,
        pages=[garbage, good], credits_used=2,
    )
    mock_storage.return_value = MagicMock()
    mock_kf = MagicMock()
    mock_kf.id = uuid.uuid4()
    mock_upload.return_value = mock_kf

    run_job(str(job.id))

    db_session.refresh(job)
    assert job.status == "completed"
    assert job.pages_fetched == 2
    assert job.pages_filtered == 1  # 一个被过滤
    assert len(job.file_ids) == 1   # 只入了一个


def test_run_job_marks_failed_on_unconfigured(db_session):
    """Firecrawl 配置丢失 → job.failed。"""
    from app.models import User
    user = User(username="test_run5", name="t5", password_hash="x",
                email="test_run5@tiangong.dev")
    db_session.add(user)
    db_session.flush()
    job = _create_running_job(db_session, user_id=user.id)

    with patch("app.services.web_ingestion_service.resolve_firecrawl_config",
               return_value=None):
        run_job(str(job.id))

    db_session.refresh(job)
    assert job.status == "failed"
    assert "配置丢失" in (job.error_message or "")
