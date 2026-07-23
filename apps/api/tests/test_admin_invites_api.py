"""admin 邀请码管理 API 测试 + admin 创建用户端点测试。"""
import pytest

from app.core.security import hash_password
from app.models import User


@pytest.fixture
def admin_and_login(client, db_session):
    """创建管理员并登录。"""
    admin = User(
        username="admin",
        email="admin@tiangong.dev",
        password_hash=hash_password("Admin1234!"),
        name="管理员",
        role="admin",
        status="active",
    )
    db_session.add(admin)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "Admin1234!",
    })
    return admin


@pytest.fixture
def normal_user_logged_in(client, db_session):
    """普通用户登录(用于权限测试)。"""
    u = User(
        username="normal",
        email="normal@tiangong.dev",
        password_hash=hash_password("Normal123!"),
        name="普通",
        role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "username": "normal", "password": "Normal123!",
    })
    return u


# ── 邀请码管理 ──

def test_admin_generate_invite_code(client, admin_and_login):
    """admin 生成邀请码。"""
    res = client.post("/api/v1/admin/invites", json={"max_uses": 1, "expires_in_days": 7})
    assert res.status_code == 200
    data = res.json()
    assert len(data["code"]) == 8
    assert data["max_uses"] == 1
    assert data["used_count"] == 0
    assert data["status"] == "active"


def test_admin_generate_invite_no_expiry(client, admin_and_login):
    """expires_in_days=None 生成不过期的码。"""
    res = client.post("/api/v1/admin/invites", json={"max_uses": 1, "expires_in_days": None})
    assert res.status_code == 200
    assert res.json()["expires_at"] is None


def test_admin_list_invites(client, admin_and_login):
    """admin 列出邀请码。"""
    client.post("/api/v1/admin/invites", json={"max_uses": 1, "expires_in_days": 7})
    client.post("/api/v1/admin/invites", json={"max_uses": 3, "expires_in_days": None})
    res = client.get("/api/v1/admin/invites")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    assert all("code" in item for item in data)


def test_admin_revoke_invite(client, admin_and_login):
    """admin 吊销邀请码。"""
    gen = client.post("/api/v1/admin/invites", json={"max_uses": 1, "expires_in_days": 7})
    invite_id = gen.json()["id"]
    res = client.delete(f"/api/v1/admin/invites/{invite_id}")
    assert res.status_code == 200
    # 列表里状态应为 revoked
    codes = client.get("/api/v1/admin/invites").json()
    assert codes[0]["status"] == "revoked"


def test_normal_user_cannot_manage_invites(client, normal_user_logged_in):
    """普通用户无权管理邀请码。"""
    assert client.post("/api/v1/admin/invites", json={}).status_code == 403
    assert client.get("/api/v1/admin/invites").status_code == 403


def test_unauthenticated_cannot_manage_invites(client):
    """未登录无权管理邀请码。"""
    assert client.post("/api/v1/admin/invites", json={}).status_code == 401
    assert client.get("/api/v1/admin/invites").status_code == 401


# ── admin 创建用户 ──

def test_admin_create_user_success(client, admin_and_login):
    """admin 直接创建用户,无需邀请码。"""
    res = client.post("/api/v1/admin/users", json={
        "username": "newcolleague",
        "password": "NewPass123!",
        "name": "新同事",
        "email": "new@tiangong.dev",
        "role": "user",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "newcolleague"
    assert data["role"] == "user"
    assert data["status"] == "active"


def test_admin_create_user_default_role(client, admin_and_login):
    """不传 role 默认 user。"""
    res = client.post("/api/v1/admin/users", json={
        "username": "defaultrole",
        "password": "NewPass123!",
        "name": "默认角色",
    })
    assert res.status_code == 200
    assert res.json()["role"] == "user"


def test_admin_create_admin_user(client, admin_and_login, db_session):
    """admin 可创建另一个 admin。"""
    res = client.post("/api/v1/admin/users", json={
        "username": "admin2",
        "password": "NewPass123!",
        "name": "二号管理员",
        "role": "admin",
    })
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_admin_create_duplicate_user_409(client, admin_and_login):
    """重复用户名返回 409。"""
    client.post("/api/v1/admin/users", json={
        "username": "dupe",
        "password": "NewPass123!",
        "name": "一",
    })
    res = client.post("/api/v1/admin/users", json={
        "username": "dupe",
        "password": "NewPass123!",
        "name": "二",
    })
    assert res.status_code == 409


def test_admin_create_user_can_login(client, admin_and_login):
    """admin 创建的用户能立即登录(密码正确)。"""
    client.post("/api/v1/admin/users", json={
        "username": "loginable",
        "password": "Login1234!",
        "name": "可登录",
    })
    # 登出
    client.post("/api/v1/auth/logout")
    # 新用户登录
    res = client.post("/api/v1/auth/login", json={
        "username": "loginable",
        "password": "Login1234!",
    })
    assert res.status_code == 200


def test_normal_user_cannot_create_user(client, normal_user_logged_in):
    """普通用户无权创建用户。"""
    res = client.post("/api/v1/admin/users", json={
        "username": "hacker",
        "password": "NewPass123!",
        "name": "黑客",
    })
    assert res.status_code == 403
