"""admin 用户运营 API 测试。"""

import uuid

import pytest

from app.core.security import hash_password, verify_password
from app.models import User


@pytest.fixture
def admin_and_login(client, db_session):
    """创建管理员并登录，返回 admin user。"""
    admin = User(
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
        "email": "admin@example.com", "password": "Admin1234!",
    })
    return admin


@pytest.fixture
def target_user(db_session):
    u = User(
        email="target@example.com",
        password_hash=hash_password("OldPass1!"),
        name="目标用户",
        role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _patch_status(client, user_id, status):
    return client.patch(f"/api/v1/admin/users/{user_id}/status", json={"status": status})


def _reset_password(client, user_id, new_password):
    return client.post(f"/api/v1/admin/users/{user_id}/reset-password", json={"new_password": new_password})


def test_patch_status_ban_user(client, db_session, admin_and_login, target_user):
    res = _patch_status(client, target_user.id, "disabled")
    assert res.status_code == 200
    assert res.json()["status"] == "disabled"
    db_session.expire_all()
    u = db_session.get(User, target_user.id)
    assert u.status == "disabled"


def test_patch_status_unban_user(client, db_session, admin_and_login, target_user):
    target_user.status = "disabled"
    db_session.commit()
    res = _patch_status(client, target_user.id, "active")
    assert res.status_code == 200
    assert res.json()["status"] == "active"


def test_reset_password_endpoint(client, db_session, admin_and_login, target_user):
    res = _reset_password(client, target_user.id, "BrandNew9!")
    assert res.status_code == 200
    db_session.expire_all()
    u = db_session.get(User, target_user.id)
    assert verify_password("BrandNew9!", u.password_hash)


def test_cannot_ban_self_returns_403(client, admin_and_login):
    res = _patch_status(client, admin_and_login.id, "disabled")
    assert res.status_code == 403
    assert res.json()["code"] == "forbidden"


def test_cannot_reset_self_returns_403(client, admin_and_login):
    res = _reset_password(client, admin_and_login.id, "AnyPass1!")
    assert res.status_code == 403


def test_cannot_ban_superuser_returns_403(client, admin_and_login, db_session):
    superadmin = User(
        email="root@example.com",
        password_hash="x",
        name="超管",
        role="admin",
        status="active",
        is_superuser=True,
    )
    db_session.add(superadmin)
    db_session.commit()
    res = _patch_status(client, superadmin.id, "disabled")
    assert res.status_code == 403


def test_cannot_ban_other_admin_returns_403(client, admin_and_login, db_session):
    other_admin = User(
        email="admin2@example.com",
        password_hash="x",
        name="管理员2",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(other_admin)
    db_session.commit()
    res = _patch_status(client, other_admin.id, "disabled")
    assert res.status_code == 403


def test_patch_status_user_not_found_404(client, admin_and_login):
    res = _patch_status(client, uuid.uuid4(), "disabled")
    assert res.status_code == 404


def test_normal_user_cannot_access_ban(client, registered_user, target_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = _patch_status(client, target_user.id, "disabled")
    assert res.status_code == 403
