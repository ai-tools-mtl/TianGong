"""web_ingestion_service 的 helper 函数测试(URL 校验 + 配额)。"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import ValidationError
from app.services.web_ingestion_service import (
    MAX_CRAWL_PAGES_HARD_CAP,
    DEFAULT_QUOTA_PER_USER_PER_DAY,
    _validate_url,
    _used_pages_today,
    _reserve_quota,
    _refund_quota,
    _correct_quota,
)
from app.services.llm_log_helper import log_firecrawl_call


# ── _validate_url(SSRF 防护)──────────────────────────────────

@pytest.mark.parametrize("url,should_pass", [
    ("https://example.com", True),
    ("http://example.com/path/to/page", True),
    ("http://example.com:8080/x", True),
    ("ftp://example.com", False),                       # 协议错
    ("http://127.0.0.1/admin", False),                  # loopback
    ("http://10.0.0.1/internal", False),                # 内网 A
    ("http://172.16.0.1/x", False),                     # 内网 B
    ("http://192.168.1.1", False),                      # 内网 C
    ("http://169.254.169.254/latest/meta-data", False), # 云元数据
    ("http://metadata.google.internal", False),         # GCE 元数据
    ("http://[::1]", False),                            # IPv6 loopback
    ("not-a-url", False),                               # 非法格式
    ("", False),                                        # 空
])
def test_validate_url_ssrf_protection(url, should_pass):
    if should_pass:
        _validate_url(url)
    else:
        with pytest.raises(ValidationError):
            _validate_url(url)


def test_validate_url_rejects_too_long():
    """超长 URL 被拒。"""
    long_url = "https://example.com/" + "a" * 2100
    with pytest.raises(ValidationError):
        _validate_url(long_url)


# ── 配额 ─────────────────────────────────────────────────────

def test_used_pages_today_starts_at_zero(db_session):
    """新用户当日使用量为 0。"""
    assert _used_pages_today(db_session, uuid.uuid4()) == 0


def test_used_pages_today_sums_logs(db_session):
    """聚合当日 firecrawl 日志的页数。"""
    uid = uuid.uuid4()
    log_firecrawl_call(db_session, user_id=uid, mode="scrape", pages=5, source="global")
    log_firecrawl_call(db_session, user_id=uid, mode="crawl", pages=50, source="global")
    assert _used_pages_today(db_session, uid) == 55


def test_used_pages_today_excludes_other_users(db_session):
    """只算本人。"""
    uid1, uid2 = uuid.uuid4(), uuid.uuid4()
    log_firecrawl_call(db_session, user_id=uid1, mode="scrape", pages=5, source="global")
    log_firecrawl_call(db_session, user_id=uid2, mode="scrape", pages=50, source="global")
    assert _used_pages_today(db_session, uid1) == 5


def test_reserve_quota_allows_within_limit(db_session):
    """配额内允许。"""
    uid = uuid.uuid4()
    _reserve_quota(db_session, user=_mock_user(uid), mode="scrape", max_pages=1)
    assert _used_pages_today(db_session, uid) == 1


def test_reserve_quota_rejects_over_limit(db_session):
    """超额报错。"""
    uid = uuid.uuid4()
    log_firecrawl_call(
        db_session, user_id=uid, mode="crawl",
        pages=DEFAULT_QUOTA_PER_USER_PER_DAY, source="global",
    )
    with pytest.raises(ValidationError):
        _reserve_quota(db_session, user=_mock_user(uid), mode="scrape", max_pages=1)


def test_reserve_quota_crawl_uses_max_pages(db_session):
    """crawl 模式按 max_pages 预扣。"""
    uid = uuid.uuid4()
    _reserve_quota(db_session, user=_mock_user(uid), mode="crawl", max_pages=50)
    assert _used_pages_today(db_session, uid) == 50


def test_refund_quota_decrements(db_session):
    """退款减量。"""
    uid = uuid.uuid4()
    _reserve_quota(db_session, user=_mock_user(uid), mode="scrape", max_pages=1)
    _refund_quota(db_session, user=_mock_user(uid), pages=1)
    assert _used_pages_today(db_session, uid) == 0


def _mock_user(uid):
    from unittest.mock import MagicMock
    u = MagicMock()
    u.id = uid
    u.is_admin = False
    return u


# ── SSRF 补充(localhost + 非标准编码)─────────────────────────

@pytest.mark.parametrize("url", [
    "http://localhost",
    "http://LOCALHOST",
    "http://localhost:8080",
    "http://2130706433",           # decimal 127.0.0.1
    "http://0x7f000001",           # hex 127.0.0.1
    "http://0177.0.0.1",           # octal 127.0.0.1
    "http://3232235777",           # decimal 192.168.1.1
    "http://127.0.0.1.nip.io",     # DNS rebinding(尽力而为,可能放行—记录残留风险)
])
def test_validate_url_blocks_ssrf_bypasses(url):
    """SSRF 绕过向量被拦截(decimal/octal/hex/localhost)。

    nip.io 等 DNS rebinding 是残留风险(Firecrawl 服务端是第二道防线),
    本地尽力而为——如果某个用例放行,标记 xfail 而非让测试失败。
    """
    try:
        _validate_url(url)
        # 如果没抛(放行了),检查是否是已知的残留风险
        if "nip.io" in url:
            pytest.xfail("DNS rebinding 是已知残留风险,依赖 Firecrawl 服务端防护")
        else:
            pytest.fail(f"SSRF 漏洞:{url} 应被拦截但放行了")
    except ValidationError:
        pass  # 正确拦截


# ── _correct_quota ───────────────────────────────────────────

def _make_job(uid, *, pages_fetched, pages_filtered, max_pages=10):
    """构造一个已完成的 crawl job(测试 _correct_quota 用)。"""
    from app.models import WebIngestionJob
    return WebIngestionJob(
        user_id=uid, scope="personal", url="https://x.com", mode="crawl",
        max_pages=max_pages, firecrawl_job_id="x", status="completed",
        pages_fetched=pages_fetched, pages_filtered=pages_filtered,
    )


def test_correct_quota_no_delta(db_session):
    """实际页数 == 预扣,不校正。"""
    uid = uuid.uuid4()
    job = _make_job(uid, pages_fetched=10, pages_filtered=0)  # 实际 10,预扣 10
    _correct_quota(db_session, job=job)

    from app.models import LLMCallLog
    corrections = db_session.query(LLMCallLog).filter_by(
        action="firecrawl", user_id=uid, status="correction",
    ).all()
    assert len(corrections) == 0


def test_correct_quota_positive_delta(db_session):
    """实际 > 预扣,补扣(delta > 0)。"""
    uid = uuid.uuid4()
    job = _make_job(uid, pages_fetched=15, pages_filtered=0)  # 实际 15,预扣 10,delta=+5
    _correct_quota(db_session, job=job)

    from app.models import LLMCallLog
    corrections = db_session.query(LLMCallLog).filter_by(
        action="firecrawl", user_id=uid, status="correction",
    ).all()
    assert len(corrections) == 1
    assert corrections[0].token_completion == 5


def test_correct_quota_negative_delta(db_session):
    """实际 < 预扣,退款(delta < 0)。"""
    uid = uuid.uuid4()
    job = _make_job(uid, pages_fetched=8, pages_filtered=5)  # 实际 3,预扣 10,delta=-7
    _correct_quota(db_session, job=job)

    from app.models import LLMCallLog
    corrections = db_session.query(LLMCallLog).filter_by(
        action="firecrawl", user_id=uid, status="correction",
    ).all()
    assert len(corrections) == 1
    assert corrections[0].token_completion == -7
