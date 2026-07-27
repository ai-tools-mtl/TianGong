"""FirecrawlClient + resolve_firecrawl_config + admin get/set 测试。

客户端测试用 mock SDK,不真打 Firecrawl API。

SDK 探查结果(firecrawl-py 4.32.1,统一 Firecrawl 客户端 v2 推荐 API):
- Firecrawl(api_key=..., api_url=...)            # 注意是 api_url 不是 base_url
- scrape(url, formats=[...]) -> Document         # pydantic 模型,不是 dict
- start_crawl(url, limit=...) -> CrawlResponse   # 含 .id / .url
- get_crawl_status(job_id) -> CrawlJob           # status: scraping/completed/failed/cancelled
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import get_settings
from app.models import SystemSetting
from app.services.firecrawl_client import (
    CrawlJobHandle,
    CrawlStatus,
    FirecrawlClient,
    ResolvedFirecrawlConfig,
    ScrapeResult,
    get_firecrawl_settings,
    resolve_firecrawl_config,
    set_firecrawl_settings,
)


# ── dataclass ────────────────────────────────────────────────

def test_scrape_result_dataclass():
    r = ScrapeResult(url="x", title="t", markdown="md", status_code=200, fetch_failed=False)
    assert r.url == "x" and r.markdown == "md"


def test_crawl_status_dataclass():
    s = CrawlStatus(status="scraping", completed=5, total=50, pages=[], credits_used=0)
    assert s.status == "scraping" and s.completed == 5


def test_crawl_job_handle_dataclass():
    h = CrawlJobHandle(firecrawl_job_id="abc")
    assert h.firecrawl_job_id == "abc"


# ── FirecrawlClient(用 mock SDK)──────────────────────────────
# 关键:patch "app.services.firecrawl_client._FirecrawlSDK"(模块内 import 的 SDK 类)
# mock SDK 返回真实 v2 pydantic 对象(Document / CrawlResponse / CrawlJob)。

@pytest.fixture
def client_with_mock_sdk():
    """构造 FirecrawlClient,内部 _sdk 被 mock。"""
    with patch("app.services.firecrawl_client._FirecrawlSDK") as mock_sdk_class:
        mock_sdk = MagicMock()
        mock_sdk_class.return_value = mock_sdk
        client = FirecrawlClient(api_key="fc-test", base_url="https://x")
        # 校验初始化把 base_url 透传成 SDK 的 api_url 参数
        mock_sdk_class.assert_called_once_with(api_key="fc-test", api_url="https://x")
        yield client, mock_sdk


def _doc(*, markdown="md", title="T", source_url="https://x", status_code=200):
    """构造一个最小 Document-like 对象(用 MagicMock 模拟 pydantic 属性访问)。"""
    doc = MagicMock()
    doc.markdown = markdown
    meta = MagicMock()
    meta.title = title
    meta.source_url = source_url
    meta.status_code = status_code
    doc.metadata = meta
    return doc


def test_scrape_returns_scrape_result(client_with_mock_sdk):
    """scrape 返回结构化 dataclass,字段从 v2 Document 提取。"""
    client, mock_sdk = client_with_mock_sdk
    mock_sdk.scrape.return_value = _doc(markdown="# Title\n\nbody")
    result = client.scrape("https://x")
    assert result.markdown == "# Title\n\nbody"
    assert result.title == "T"
    assert result.url == "https://x"
    assert result.status_code == 200
    assert result.fetch_failed is False


def test_scrape_handles_failure(client_with_mock_sdk):
    """scrape 异常时返回 fetch_failed=True,不抛。"""
    client, mock_sdk = client_with_mock_sdk
    mock_sdk.scrape.side_effect = RuntimeError("network error")
    result = client.scrape("https://x")
    assert result.fetch_failed is True
    assert result.markdown == ""
    assert result.url == "https://x"


def test_start_crawl_returns_handle(client_with_mock_sdk):
    """start_crawl 返回 firecrawl_job_id 句柄。"""
    client, mock_sdk = client_with_mock_sdk
    resp = MagicMock()
    resp.id = "fc-job-123"
    mock_sdk.start_crawl.return_value = resp
    handle = client.start_crawl("https://x", limit=50)
    assert handle.firecrawl_job_id == "fc-job-123"
    # 确认把 limit 透传给 SDK
    _, kwargs = mock_sdk.start_crawl.call_args
    assert kwargs.get("limit") == 50


def test_check_crawl_in_progress(client_with_mock_sdk):
    """进行中状态返回 status='scraping',pages 为空。"""
    client, mock_sdk = client_with_mock_sdk
    job = MagicMock()
    job.status = "scraping"
    job.completed = 5
    job.total = 50
    job.credits_used = 0
    job.data = []
    mock_sdk.get_crawl_status.return_value = job
    status = client.check_crawl("fc-job-123")
    assert status.status == "scraping"
    assert status.completed == 5
    assert status.total == 50
    assert status.pages == []
    assert status.credits_used == 0


def test_check_crawl_completed(client_with_mock_sdk):
    """完成状态填充 pages(从 data: List[Document] 提取)。"""
    client, mock_sdk = client_with_mock_sdk
    job = MagicMock()
    job.status = "completed"
    job.completed = 2
    job.total = 2
    job.credits_used = 2
    job.data = [
        _doc(markdown="page1", title="P1", source_url="https://x/1", status_code=200),
        _doc(markdown="page2", title="P2", source_url="https://x/2", status_code=200),
    ]
    mock_sdk.get_crawl_status.return_value = job
    status = client.check_crawl("fc-job-123")
    assert status.status == "completed"
    assert len(status.pages) == 2
    assert status.pages[0].markdown == "page1"
    assert status.pages[0].url == "https://x/1"
    assert status.pages[0].title == "P1"
    assert status.credits_used == 2


def test_check_crawl_failed(client_with_mock_sdk):
    """失败状态。"""
    client, mock_sdk = client_with_mock_sdk
    job = MagicMock()
    job.status = "failed"
    job.completed = 1
    job.total = 50
    job.credits_used = 1
    job.data = []
    mock_sdk.get_crawl_status.return_value = job
    status = client.check_crawl("fc-job-123")
    assert status.status == "failed"


def test_sdk_import_resolves_to_v2_api():
    """真 import(不 mock),确保 SDK 结构没漂移。

    防止出现「from firecrawl import Firecrawl 只拿到 v1 parse 类」的 silent failure。
    """
    from app.services.firecrawl_client import _FirecrawlSDK
    # v2 FirecrawlClient 必须有这三个方法
    assert hasattr(_FirecrawlSDK, "scrape"), "_FirecrawlSDK 缺 scrape 方法(可能 import 错类)"
    assert hasattr(_FirecrawlSDK, "start_crawl"), "_FirecrawlSDK 缺 start_crawl 方法"
    assert hasattr(_FirecrawlSDK, "get_crawl_status"), "_FirecrawlSDK 缺 get_crawl_status 方法"


# ── resolve_firecrawl_config ─────────────────────────────────

def test_resolve_prefers_global(db_session, monkeypatch):
    """全局配置优先于 env。"""
    set_firecrawl_settings(db_session, enabled=True, api_key="fc-global",
                           base_url="https://fc.example", updated_by=uuid.uuid4())
    # get_settings 用 @lru_cache 缓存,直接 setattr 缓存对象的属性(不依赖 env)。
    settings = get_settings()
    monkeypatch.setattr(settings, "firecrawl_api_key", "fc-env")
    config = resolve_firecrawl_config(db_session)
    assert config.api_key == "fc-global"
    assert config.source == "global"
    assert config.base_url == "https://fc.example"


def test_resolve_falls_back_to_env(db_session, monkeypatch):
    """全局禁用时回落 env。"""
    set_firecrawl_settings(db_session, enabled=False, api_key="fc-x", updated_by=uuid.uuid4())
    settings = get_settings()
    monkeypatch.setattr(settings, "firecrawl_api_key", "fc-env")
    config = resolve_firecrawl_config(db_session)
    assert config.api_key == "fc-env"
    assert config.source == "env"


def test_resolve_returns_none_when_unconfigured(db_session, monkeypatch):
    """都没配置返回 None。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "firecrawl_api_key", "")
    assert resolve_firecrawl_config(db_session) is None


# ── get/set_firecrawl_settings ───────────────────────────────

def test_set_then_get_roundtrip(db_session):
    """set 后 get 返回脱敏 key。"""
    set_firecrawl_settings(
        db_session, enabled=True, api_key="fc-1234567890",
        base_url="https://fc.x", updated_by=uuid.uuid4(),
    )
    result = get_firecrawl_settings(db_session)
    assert result["enabled"] is True
    assert result["base_url"] == "https://fc.x"
    assert "fc-1234567890" not in result["api_key_masked"]  # 脱敏
    assert "****" in result["api_key_masked"]


def test_set_preserves_key_when_empty(db_session):
    """api_key 空串时保留已有 key(不覆盖)。"""
    set_firecrawl_settings(
        db_session, enabled=True, api_key="fc-orig",
        base_url="https://x", updated_by=uuid.uuid4(),
    )
    set_firecrawl_settings(
        db_session, enabled=False, api_key="",  # 空,不改 key
        base_url="https://y", updated_by=uuid.uuid4(),
    )
    # key 应仍在 SystemSetting 里
    cfg_setting = db_session.query(SystemSetting).filter_by(key="firecrawl_config").one()
    assert cfg_setting.value.get("api_key_encrypted")  # key 还在


def test_get_returns_defaults_when_unconfigured(db_session):
    """未配置时 get 返回安全默认(enabled=False,空字符串)。"""
    result = get_firecrawl_settings(db_session)
    assert result["enabled"] is False
    assert result["api_key_masked"] == ""
    assert result["base_url"] == ""
