"""WebIngestionJob ORM 模型测试。"""

import uuid

from app.models import User, WebIngestionJob
from app.core.security import hash_password


def test_web_ingestion_job_fields(db_session):
    """模型字段齐全且默认值正确。

    SQLAlchemy 2.0 的 `default=` 只在 flush 时生效(非构造时)——
    抄现有 test_models.test_parse_job_defaults 的模式:flush 后再断言默认值。
    """
    # 一个真实 user 满足外键约束
    u = User(
        username="wj", email="wj@example.com",
        password_hash=hash_password("Pass1234!"), name="WJ",
    )
    db_session.add(u)
    db_session.flush()

    job = WebIngestionJob(
        user_id=u.id,
        scope="personal",
        url="https://example.com",
        mode="crawl",
        max_pages=50,
    )
    db_session.add(job)
    db_session.flush()

    # 显式传入的字段
    assert job.scope == "personal"
    assert job.mode == "crawl"
    assert job.max_pages == 50
    # 数据库层默认值(flush 后才填)
    assert job.status == "pending"
    assert job.pages_fetched == 0
    assert job.pages_filtered == 0
    # 可空字段
    assert job.firecrawl_job_id is None
    assert job.file_ids is None
    assert job.error_message is None
    assert job.completed_at is None


def test_web_ingestion_job_in_db(db_session):
    """可在 SQLite 测试库写入读取。"""
    uid = uuid.uuid4()
    job = WebIngestionJob(
        user_id=uid, scope="global", url="https://x.com",
        mode="scrape", max_pages=1, status="completed",
        pages_fetched=1, file_ids=[str(uuid.uuid4())],
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    fetched = db_session.get(WebIngestionJob, job.id)
    assert fetched is not None
    assert fetched.url == "https://x.com"
    assert fetched.file_ids == job.file_ids
