"""全局 Key 授权 API 测试（Task 2.2）。

覆盖 /api/v1/admin/users/{user_id}/global-llm-grant 的 GET/POST/DELETE：
- grant 普通用户 → 200，GET → is_active=True
- grant 幂等（重复 grant 仍 200）
- revoke → 200，GET → is_active=False（revoked_at 非空）
- revoke 无记录的用户 → no-op 200
- 非 admin 调 grant → 403
- grant/revoke 自己（admin）→ 允许（无害）
- grant 其他 admin / 超管 → 403（admin 角色免授权，授权无意义）
- GET /admin/users 列表含 has_global_grant 字段
- 审计日志写入
"""

import uuid

import pytest

from app.core.security import hash_password
from app.models import AuditLog, User, UserGlobalLLMGrant
from sqlalchemy import select


@pytest.fixture
def admin_and_login(client, db_session):
    """创建管理员并登录。"""
    admin = User(
        username="admin",
        email="admin@example.com",
        password_hash=hash_password("Admin1234!"),
        name="管理员",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(admin)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "Admin1234!",
    })
    return admin


@pytest.fixture
def target_user(db_session):
    u = User(
        username="target",
        email="target@example.com",
        password_hash=hash_password("OldPass1!"),
        name="目标用户",
        role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _grant(client, user_id):
    return client.post(f"/api/v1/admin/users/{user_id}/global-llm-grant")


def _revoke(client, user_id):
    return client.delete(f"/api/v1/admin/users/{user_id}/global-llm-grant")


def _get_grant(client, user_id):
    return client.get(f"/api/v1/admin/users/{user_id}/global-llm-grant")


# ── 正常路径 ──

def test_get_grant_no_record_returns_inactive(client, admin_and_login, target_user):
    """无授权记录 → {is_active: False}。"""
    res = _get_grant(client, target_user.id)
    assert res.status_code == 200
    assert res.json() == {"is_active": False}


def test_grant_normal_user_then_active(client, admin_and_login, target_user):
    """grant 普通用户 → 200，再 GET → is_active=True。"""
    res = _grant(client, target_user.id)
    assert res.status_code == 200
    assert res.json()["message"] == "已授权"

    res = _get_grant(client, target_user.id)
    assert res.json()["is_active"] is True
    assert res.json()["revoked_at"] is None
    assert res.json()["granted_at"] is not None


def test_grant_idempotent(client, db_session, admin_and_login, target_user):
    """重复 grant → 仍 200，is_active=True（幂等：不新建第二条行）。"""
    _grant(client, target_user.id)
    res = _grant(client, target_user.id)
    assert res.status_code == 200

    count = db_session.query(UserGlobalLLMGrant).filter_by(user_id=target_user.id).count()
    assert count == 1  # user_id unique，幂等不新增
    assert res.json() == {"message": "已授权"}


def test_grant_reactivates_after_revoke(client, db_session, admin_and_login, target_user):
    """revoke 后再 grant → 清 revoked_at 重新激活（仍同一行）。"""
    _grant(client, target_user.id)
    _revoke(client, target_user.id)
    res = _grant(client, target_user.id)
    assert res.status_code == 200

    res = _get_grant(client, target_user.id)
    assert res.json()["is_active"] is True
    assert res.json()["revoked_at"] is None


def test_revoke_active_grant(client, admin_and_login, target_user):
    """revoke → 200，GET → is_active=False（revoked_at 非空）。"""
    _grant(client, target_user.id)
    res = _revoke(client, target_user.id)
    assert res.status_code == 200
    assert res.json()["message"] == "已撤销"

    res = _get_grant(client, target_user.id)
    assert res.json()["is_active"] is False
    assert res.json()["revoked_at"] is not None


def test_revoke_no_record_is_noop(client, admin_and_login, target_user):
    """revoke 无记录的用户 → no-op 200（目标存在，但无 grant 行）。"""
    res = _revoke(client, target_user.id)
    assert res.status_code == 200


def test_revoke_already_revoked_is_noop(client, admin_and_login, target_user):
    """revoke 已撤销的用户 → no-op 200（不重复写 revoked_at）。"""
    _grant(client, target_user.id)
    _revoke(client, target_user.id)
    res = _revoke(client, target_user.id)
    assert res.status_code == 200


# ── 权限 ──

def test_non_admin_grant_forbidden(client, registered_user, target_user):
    """非 admin 调 grant → 403。"""
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    res = _grant(client, target_user.id)
    assert res.status_code == 403


def test_non_admin_revoke_forbidden(client, registered_user, target_user):
    """非 admin 调 revoke → 403。"""
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    res = _revoke(client, target_user.id)
    assert res.status_code == 403


def test_non_admin_get_grant_forbidden(client, registered_user, target_user):
    """非 admin 调 GET → 403。"""
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    res = _get_grant(client, target_user.id)
    assert res.status_code == 403


# ── 自我保护：允许自己，禁止其他 admin/超管 ──

def test_grant_self_allowed(client, admin_and_login):
    """admin grant 自己 → 允许（无害；admin 本就免授权）。"""
    res = _grant(client, admin_and_login.id)
    assert res.status_code == 200


def test_grant_other_admin_forbidden(client, admin_and_login, db_session):
    """grant 其他 admin → 403（admin 角色免授权，授权无意义）。"""
    other_admin = User(
        username="admin2",
        email="admin2@example.com",
        password_hash="x",
        name="管理员2",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(other_admin)
    db_session.commit()
    res = _grant(client, other_admin.id)
    assert res.status_code == 403


def test_grant_superuser_forbidden(client, admin_and_login, db_session):
    """grant 超管 → 403（超管免授权）。"""
    superadmin = User(
        username="root",
        email="root@example.com",
        password_hash="x",
        name="超管",
        role="admin",
        status="active",
        is_superuser=True,
    )
    db_session.add(superadmin)
    db_session.commit()
    res = _grant(client, superadmin.id)
    assert res.status_code == 403


def test_grant_user_not_found_404(client, admin_and_login):
    """grant 不存在的用户 → 404。"""
    res = _grant(client, uuid.uuid4())
    assert res.status_code == 404


# ── 用户列表 has_global_grant ──

def test_list_users_includes_has_global_grant(client, admin_and_login, target_user, db_session):
    """GET /admin/users 每条含 has_global_grant 字段。"""
    # 未授权时 False
    res = client.get("/api/v1/admin/users")
    assert res.status_code == 200
    rows = {r["id"]: r for r in res.json()}
    assert "has_global_grant" in rows[str(target_user.id)]
    assert rows[str(target_user.id)]["has_global_grant"] is False

    # 授权后 True
    _grant(client, target_user.id)
    res = client.get("/api/v1/admin/users")
    rows = {r["id"]: r for r in res.json()}
    assert rows[str(target_user.id)]["has_global_grant"] is True

    # 撤销后 False
    _revoke(client, target_user.id)
    res = client.get("/api/v1/admin/users")
    rows = {r["id"]: r for r in res.json()}
    assert rows[str(target_user.id)]["has_global_grant"] is False


# ── 审计 ──

def test_grant_writes_audit(client, admin_and_login, target_user, db_session):
    """grant 写审计日志。"""
    _grant(client, target_user.id)
    logs = list(db_session.scalars(
        select(AuditLog).where(AuditLog.action == "grant_global_llm")
    ))
    assert len(logs) == 1
    log = logs[0]
    assert log.target_type == "user"
    assert log.target_id == str(target_user.id)
    assert log.actor_username == admin_and_login.username


def test_revoke_writes_audit(client, admin_and_login, target_user, db_session):
    """revoke 写审计日志。"""
    _grant(client, target_user.id)
    _revoke(client, target_user.id)
    logs = list(db_session.scalars(
        select(AuditLog).where(AuditLog.action == "revoke_global_llm")
    ))
    assert len(logs) == 1
    assert logs[0].target_id == str(target_user.id)
