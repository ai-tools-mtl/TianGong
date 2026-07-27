"""log_firecrawl_call helper 测试。"""

import uuid

from app.models import LLMCallLog
from app.services.llm_log_helper import log_firecrawl_call


def test_log_firecrawl_call_writes_record(db_session):
    """写一条 action=firecrawl 的日志,pages 进 token_completion。"""
    uid = uuid.uuid4()
    log_firecrawl_call(
        db_session, user_id=uid, mode="crawl", pages=50, source="global",
    )
    record = db_session.query(LLMCallLog).filter_by(action="firecrawl").one()
    assert record.user_id == uid
    assert record.model == "firecrawl-crawl"
    assert record.provider == "global"
    assert record.token_completion == 50
    assert record.status == "success"


def test_log_firecrawl_call_negative_pages(db_session):
    """负 pages(退款/校正)正常写入。"""
    uid = uuid.uuid4()
    log_firecrawl_call(
        db_session, user_id=uid, mode="scrape", pages=-1, source="global",
        status="refund",
    )
    record = db_session.query(LLMCallLog).filter_by(action="firecrawl").one()
    assert record.token_completion == -1
    assert record.status == "refund"


def test_log_firecrawl_call_swallows_exception(db_session, monkeypatch):
    """DB 写失败时不抛(日志不阻塞主流程)。"""
    def boom(*args, **kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(db_session, "commit", boom)

    uid = uuid.uuid4()
    # 不应抛
    log_firecrawl_call(
        db_session, user_id=uid, mode="scrape", pages=1, source="global",
    )
