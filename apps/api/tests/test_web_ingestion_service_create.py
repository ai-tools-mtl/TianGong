"""create_job / _scrape_sync / _crawl_async 测试。"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, ValidationError
from app.models import KnowledgeFile, WebIngestionJob
from app.services.firecrawl_client import (
    CrawlJobHandle, ResolvedFirecrawlConfig, ScrapeResult,
)
from app.services import web_ingestion_service
from app.services.web_ingestion_service import create_job


@pytest.fixture
def mock_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.role = "user"
    return u


@pytest.fixture
def mock_admin():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.role = "admin"
    return u


@pytest.fixture
def fake_config():
    return ResolvedFirecrawlConfig(
        api_key="fc-test", base_url="https://x",
    )


@pytest.fixture(autouse=True)
def mock_firecrawl_health():
    """默认 mock firecrawl 连通性探活为 True(服务可达),避免 happy-path 测试真打 localhost:3002。

    需要测试「服务不可达」的场景(test_rejects_service_unavailable)在用例内本地 patch 为 False。
    """
    with patch("app.services.web_ingestion_service.check_firecrawl_health", return_value=True):
        yield


# ── 入口校验 ─────────────────────────────────────────────────

def test_rejects_invalid_url(db_session, mock_user, fake_config):
    """非法 URL 报错。"""
    with patch("app.services.web_ingestion_service.resolve_firecrawl_config",
               return_value=fake_config):
        with pytest.raises(ValidationError):
            create_job(db_session, user=mock_user, url="ftp://x",
                       mode="scrape", scope="personal")


def test_rejects_service_unavailable(db_session, mock_user, fake_config):
    """Firecrawl 服务不可达报错(启动时已告警,此处给用户清晰报错)。"""
    with patch("app.services.web_ingestion_service.resolve_firecrawl_config",
               return_value=fake_config), \
         patch("app.services.web_ingestion_service.check_firecrawl_health",
               return_value=False):
        with pytest.raises(ValidationError, match="不可用"):
            create_job(db_session, user=mock_user, url="https://x.com",
                       mode="scrape", scope="personal")


def test_rejects_non_admin_to_global(db_session, mock_user, fake_config):
    """非 admin 入 global 报错。"""
    with patch("app.services.web_ingestion_service.resolve_firecrawl_config",
               return_value=fake_config):
        with pytest.raises(AuthorizationError):
            create_job(db_session, user=mock_user, url="https://x.com",
                       mode="scrape", scope="global")


def test_rejects_crawl_over_cap(db_session, mock_user, fake_config):
    """crawl max_pages 超过硬上限报错。"""
    with patch("app.services.web_ingestion_service.resolve_firecrawl_config",
               return_value=fake_config):
        with pytest.raises(ValidationError):
            create_job(db_session, user=mock_user, url="https://x.com",
                       mode="crawl", scope="personal",
                       max_pages=web_ingestion_service.MAX_CRAWL_PAGES_HARD_CAP + 1)


# ── scrape 同步流 ────────────────────────────────────────────

@patch("app.services.web_ingestion_service.get_storage")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_scrape_returns_knowledgefile(
    mock_client_cls, mock_resolve, mock_storage, db_session, mock_user, fake_config,
):
    """scrape 同步返回 KnowledgeFile。"""
    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.scrape.return_value = ScrapeResult(
        url="https://example.com/p", title="测试页",
        markdown="专利正文" * 100, status_code=200, fetch_failed=False,
    )
    # mock knowledge_service.upload_external 避免真入库(依赖 chunk/embedding)
    with patch("app.services.web_ingestion_service.knowledge_service.upload_external") as mock_upload:
        mock_kf = MagicMock(spec=KnowledgeFile)
        mock_kf.url = "https://example.com/p"
        mock_kf.scope = "personal"
        mock_kf.source_type = "external_web"
        mock_upload.return_value = mock_kf
        kf = create_job(
            db_session, user=mock_user, url="https://example.com/p",
            mode="scrape", scope="personal",
        )
    assert kf is mock_kf


@patch("app.services.web_ingestion_service.get_storage")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_scrape_filtered_refunds_quota(
    mock_client_cls, mock_resolve, mock_storage, db_session, mock_user, fake_config,
):
    """scrape 内容被过滤时退款并报错。"""
    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.scrape.return_value = ScrapeResult(
        url="https://x", title="x", markdown="太短",  # 触发长度过滤
        status_code=200, fetch_failed=False,
    )
    with patch("app.services.web_ingestion_service.knowledge_service.upload_external"):
        with pytest.raises(ValidationError, match="质量过滤"):
            create_job(db_session, user=mock_user, url="https://x",
                       mode="scrape", scope="personal")
    used = web_ingestion_service._used_pages_today(db_session, mock_user.id)
    assert used == 0


@patch("app.services.web_ingestion_service.get_storage")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_scrape_fetch_failed_refunds(
    mock_client_cls, mock_resolve, mock_storage, db_session, mock_user, fake_config,
):
    """scrape 抓取失败(fetch_failed=True)退款并报错。"""
    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.scrape.return_value = ScrapeResult(
        url="https://x", title="", markdown="", status_code=0, fetch_failed=True,
    )
    with pytest.raises(ValidationError):
        create_job(db_session, user=mock_user, url="https://x",
                   mode="scrape", scope="personal")
    used = web_ingestion_service._used_pages_today(db_session, mock_user.id)
    assert used == 0


# ── crawl 异步流 ─────────────────────────────────────────────

@patch("app.services.web_ingestion_service.spawn_background_task")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_crawl_creates_job_and_spawns_task(
    mock_client_cls, mock_resolve, mock_spawn, db_session, mock_admin, fake_config,
):
    """crawl 建 job 并 spawn 后台任务。"""
    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.start_crawl.return_value = CrawlJobHandle(firecrawl_job_id="fc-job-1")

    job = create_job(
        db_session, user=mock_admin, url="https://example.com",
        mode="crawl", scope="global", max_pages=50,
    )
    assert isinstance(job, WebIngestionJob)
    assert job.status == "running"
    assert job.firecrawl_job_id == "fc-job-1"
    assert job.scope == "global"
    assert job.max_pages == 50
    mock_spawn.assert_called_once()
    # spawn 的第一个参数应是 run_job 函数
    assert mock_spawn.call_args[0][0].__name__ == "run_job"
