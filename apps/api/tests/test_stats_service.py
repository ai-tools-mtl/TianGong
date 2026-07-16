"""stats_service 测试：LLM 调用聚合统计。"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import LLMCallLog, User
from app.services import stats_service


@pytest.fixture
def admin_user(db_session):
    u = User(
        username="admin",
        email="admin@example.com", password_hash="x", name="管理员",
        role="admin", status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _make_log(db_session, *, user_id, action="chat", model="glm-4-flash",
              provider="global", status="success", duration_ms=100,
              token_prompt=None, token_completion=None, error=None, days_ago=0):
    log = LLMCallLog(
        user_id=user_id, project_id=None, action=action, model=model,
        provider=provider, token_prompt=token_prompt, token_completion=token_completion,
        duration_ms=duration_ms, status=status, error=error,
    )
    db_session.add(log)
    db_session.commit()
    # 回填 created_at（sqlite func.now() 用不了 days_ago，手动改）
    log.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.commit()
    return log


def test_get_llm_stats_aggregates(db_session, admin_user):
    """聚合：3 条 success + 1 条 failed，按 model 分组。"""
    _make_log(db_session, user_id=admin_user.id, model="glm-4-flash", status="success", duration_ms=100)
    _make_log(db_session, user_id=admin_user.id, model="glm-4-flash", status="success", duration_ms=200)
    _make_log(db_session, user_id=admin_user.id, model="glm-4-flash", status="failed", duration_ms=50, error="boom")
    _make_log(db_session, user_id=admin_user.id, model="glm-4-air", status="success", duration_ms=300)

    stats = stats_service.get_llm_stats(db_session, days=7)
    # 顶层汇总
    assert stats["total_calls"] == 4
    assert stats["total_success"] == 3
    assert stats["total_failed"] == 1
    assert stats["avg_duration_ms"] == 162.5  # (100+200+50+300)/4
    # 按 model 分组
    by_model = {m["model"]: m for m in stats["by_model"]}
    assert by_model["glm-4-flash"]["calls"] == 3
    assert by_model["glm-4-flash"]["failed"] == 1
    assert by_model["glm-4-air"]["calls"] == 1


def test_get_llm_stats_days_filter(db_session, admin_user):
    """days=7 只含近 7 天，老记录不计。"""
    _make_log(db_session, user_id=admin_user.id, status="success", days_ago=3)
    _make_log(db_session, user_id=admin_user.id, status="success", days_ago=30)  # 超出窗口

    stats = stats_service.get_llm_stats(db_session, days=7)
    assert stats["total_calls"] == 1


def test_get_llm_stats_by_user_shows_email_not_content(db_session, admin_user):
    """按用户聚合：显示 email + 计数，绝不返回 prompt/completion 内容字段。"""
    _make_log(db_session, user_id=admin_user.id, status="success")

    stats = stats_service.get_llm_stats(db_session, days=7)
    by_user = stats["by_user"]
    assert len(by_user) == 1
    row = by_user[0]
    assert row["email"] == "admin@example.com"
    assert row["calls"] == 1
    # 红线：返回结构里绝无 prompt/completion/content 字段
    for key in row:
        assert "prompt" not in key.lower()
        assert "completion" not in key.lower()
        assert "content" not in key.lower()


def test_get_llm_stats_empty(db_session):
    """无数据时返回零值结构，不报错。"""
    stats = stats_service.get_llm_stats(db_session, days=7)
    assert stats["total_calls"] == 0
    assert stats["total_success"] == 0
    assert stats["total_failed"] == 0
    assert stats["by_model"] == []
    assert stats["by_user"] == []
