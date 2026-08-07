"""网页摄入 API 端点测试。

测试 3 个 user 端点:
- POST /knowledge/ingest/web       发起网页摄入(scrape 同步 / crawl 异步)
- GET  /knowledge/ingest/jobs/{id} 查 crawl 任务状态(越权 404)
- GET  /knowledge/ingest/jobs      列本人的任务

auth 模式:走真 cookie 登录(与 test_admin_api.py 一致),
通过 /api/v1/auth/login 建立会话后访问受保护端点。
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.security import hash_password
from app.models import User, WebIngestionJob


@pytest.fixture
def auth_user(db_session) -> User:
    """已登录的普通用户。"""
    u = User(
        username="ingester",
        email="ingest@example.com",
        password_hash=hash_password("Pass1234!"),
        name="摄入用户",
        role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def logged_in_client(client, auth_user):
    """登录后带 cookie 的 client。"""
    client.post("/api/v1/auth/login", json={
        "username": auth_user.username, "password": "Pass1234!",
    })
    return client


def test_post_ingest_web_scrape_returns_file(logged_in_client, auth_user, db_session):
    """POST /knowledge/ingest/web scrape 模式返回 {kind: file, file: {...}}。

    mock 掉 Firecrawl SDK / 配置解析 / 质量过滤 / chunk 写入:
    SQLite 测试库不支持 pgvector 的 knowledge_chunks 表,
    所以 chunk 写入必须桩掉(对齐 test_knowledge_service.py 的做法)。
    """
    with patch("app.services.web_ingestion_service.FirecrawlClient") as mock_cls, \
         patch("app.services.web_ingestion_service.resolve_firecrawl_config") as mock_res, \
         patch("app.services.web_ingestion_service.check_firecrawl_health", return_value=True), \
         patch("app.services.web_ingestion_service.filter_content") as mock_filter, \
         patch("app.services.knowledge_service._write_chunks_unembedded"):
        mock_res.return_value = MagicMock(api_key="x", base_url="x")
        client_inst = MagicMock()
        mock_cls.return_value = client_inst
        client_inst.scrape.return_value = MagicMock(
            url="https://example.com", title="测试页面",
            markdown="专利正文", status_code=200, fetch_failed=False,
        )
        # 质量过滤通过,返回 FilteredContent-like 对象
        mock_filter.return_value = MagicMock(
            markdown="专利正文", title="测试页面",
        )
        resp = logged_in_client.post("/api/v1/knowledge/ingest/web", json={
            "url": "https://example.com", "mode": "scrape", "scope": "personal",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "file"
    assert "file" in body
    assert body["file"]["scope"] == "personal"


def test_post_ingest_web_crawl_returns_job(logged_in_client, auth_user, db_session):
    """POST /knowledge/ingest/web crawl 模式返回 {kind: job, job: {status: running}}。"""
    with patch("app.services.web_ingestion_service.spawn_background_task"), \
         patch("app.services.web_ingestion_service.FirecrawlClient") as mock_cls, \
         patch("app.services.web_ingestion_service.resolve_firecrawl_config") as mock_res, \
         patch("app.services.web_ingestion_service.check_firecrawl_health", return_value=True):
        mock_res.return_value = MagicMock(api_key="x", base_url="x")
        client_inst = MagicMock()
        mock_cls.return_value = client_inst
        client_inst.start_crawl.return_value = MagicMock(firecrawl_job_id="fc-x")
        resp = logged_in_client.post("/api/v1/knowledge/ingest/web", json={
            "url": "https://example.com", "mode": "crawl",
            "scope": "personal", "max_pages": 10,
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "job"
    assert body["job"]["status"] == "running"
    assert body["job"]["firecrawl_job_id"] == "fc-x" or "fc-x" in str(body["job"])


def test_get_ingest_job_returns_status(logged_in_client, auth_user, db_session):
    """GET /knowledge/ingest/jobs/{id} 返回任务详情。"""
    job = WebIngestionJob(
        user_id=auth_user.id, scope="personal", url="https://x.com",
        mode="crawl", max_pages=10, firecrawl_job_id="fc-x", status="running",
    )
    db_session.add(job)
    db_session.commit()

    resp = logged_in_client.get(f"/api/v1/knowledge/ingest/jobs/{job.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(job.id)
    assert body["status"] == "running"
    assert body["url"] == "https://x.com"
    assert body["mode"] == "crawl"


def test_get_ingest_job_404_on_others(logged_in_client, auth_user, db_session):
    """查他人 job 返回 404(不暴露存在性)。"""
    other_job = WebIngestionJob(
        user_id=uuid.uuid4(), scope="personal", url="https://x.com",
        mode="crawl", max_pages=10, firecrawl_job_id="fc-y", status="running",
    )
    db_session.add(other_job)
    db_session.commit()

    resp = logged_in_client.get(f"/api/v1/knowledge/ingest/jobs/{other_job.id}")
    assert resp.status_code == 404


def test_list_ingest_jobs(logged_in_client, auth_user, db_session):
    """GET /knowledge/ingest/jobs 列本人的任务。"""
    for _ in range(2):
        db_session.add(WebIngestionJob(
            user_id=auth_user.id, scope="personal", url="https://x.com",
            mode="crawl", max_pages=10, firecrawl_job_id="fc-x", status="running",
        ))
    db_session.commit()

    resp = logged_in_client.get("/api/v1/knowledge/ingest/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_ingest_jobs_excludes_others(logged_in_client, auth_user, db_session):
    """GET /knowledge/ingest/jobs 只返回本人的,不含他人。"""
    db_session.add(WebIngestionJob(
        user_id=auth_user.id, scope="personal", url="https://x.com",
        mode="crawl", max_pages=10, firecrawl_job_id="fc-mine", status="running",
    ))
    db_session.add(WebIngestionJob(
        user_id=uuid.uuid4(), scope="personal", url="https://x.com",
        mode="crawl", max_pages=10, firecrawl_job_id="fc-others", status="running",
    ))
    db_session.commit()

    resp = logged_in_client.get("/api/v1/knowledge/ingest/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_ingest_web_requires_login(client):
    """未登录访问 ingest 端点 → 401。"""
    resp = client.post("/api/v1/knowledge/ingest/web", json={
        "url": "https://example.com", "mode": "scrape",
    })
    assert resp.status_code == 401
