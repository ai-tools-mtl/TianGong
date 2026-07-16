"""GET /admin/audit-logs 端点测试。"""

import pytest
import sqlalchemy

from app.core.security import hash_password
from app.models import AuditLog, User


@pytest.fixture
def admin_and_login(client, db_session):
    admin = User(
        username="admin",
        email="admin@example.com", password_hash=hash_password("Admin1234!"),
        name="管理员", role="admin", status="active",
    )
    db_session.add(admin)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "Admin1234!",
    })
    return admin


def _seed_logs(db_session, admin, n=5):
    """插 n 条审计日志（created_at 递增，手动设置确保倒序可验证）。"""
    from datetime import datetime, timedelta, timezone
    base = datetime.now(timezone.utc) - timedelta(minutes=n)
    for i in range(n):
        db_session.add(AuditLog(
            actor_id=admin.id, actor_email=admin.email,
            action="ban_user", target_type="user", target_id=f"user-{i}",
            detail={"status": "disabled"},
        ))
    db_session.commit()
    # 手动调 created_at 确保倒序可验证
    logs = list(db_session.scalars(sqlalchemy.select(AuditLog)))
    for i, log in enumerate(logs):
        log.created_at = base + timedelta(minutes=i)
    db_session.commit()


def test_audit_logs_paginated_newest_first(client, admin_and_login, db_session):
    _seed_logs(db_session, admin_and_login, n=5)

    res = client.get("/api/v1/admin/audit-logs?page=1&size=2")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert data["page"] == 1
    assert data["size"] == 2
    assert len(data["items"]) == 2
    # 倒序：第一条应是最后插入（最新 created_at）
    assert data["items"][0]["target_id"] == "user-4"
    assert data["items"][1]["target_id"] == "user-3"


def test_audit_logs_page2(client, admin_and_login, db_session):
    _seed_logs(db_session, admin_and_login, n=5)

    res = client.get("/api/v1/admin/audit-logs?page=2&size=2")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 2
    assert data["items"][0]["target_id"] == "user-2"


def test_audit_logs_default_pagination(client, admin_and_login, db_session):
    """不传 page/size 用默认值。"""
    _seed_logs(db_session, admin_and_login, n=3)
    res = client.get("/api/v1/admin/audit-logs")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_audit_logs_normal_user_forbidden(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.get("/api/v1/admin/audit-logs")
    assert res.status_code == 403


def test_audit_logs_redacted_detail_no_api_key(client, admin_and_login, db_session):
    """审计响应的 detail 绝不含 api_key（即便历史数据混入也应过滤）。"""
    db_session.add(AuditLog(
        actor_id=admin_and_login.id, actor_email=admin_and_login.email,
        action="set_global_llm", target_type="system_setting", target_id="llm_global_config",
        detail={"model": "glm-4-flash", "base_url": "https://x", "enabled": True},
    ))
    db_session.commit()

    res = client.get("/api/v1/admin/audit-logs")
    assert res.status_code == 200
    item = res.json()["items"][0]
    detail = item["detail"]
    assert "api_key" not in detail
    assert "api_key_encrypted" not in detail
