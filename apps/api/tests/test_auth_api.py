import pytest


def test_register_success(client):
    res = client.post("/api/v1/auth/register", json={
        "username": "newuser",
        "password": "Pass1234!",
        "name": "新用户",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "newuser"
    assert data["role"] == "user"
    assert "id" in data


def test_register_duplicate(client, registered_user):
    res = client.post("/api/v1/auth/register", json={
        "username": registered_user["username"],
        "password": "Pass1234!",
        "name": "重复",
    })
    assert res.status_code == 409


def test_login_success_sets_cookie(client, registered_user):
    res = client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert res.status_code == 200
    assert "access_token" in res.cookies
    assert "refresh_token" in res.cookies


def test_login_wrong_password(client, registered_user):
    res = client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": "wrongpass",
    })
    assert res.status_code == 401


def test_me_requires_auth(client):
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_me_returns_user(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200
    assert res.json()["username"] == registered_user["username"]


def test_logout_clears_cookies(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 200
    assert res.cookies.get("access_token") in (None, "")


# ── username-specific：格式校验 + email 可选 + 重复用户名 ──

@pytest.mark.parametrize("bad_username", [
    "中文用户",      # 中文
    "has space",     # 空格
    "user@name",     # 特殊字符
    "ab",            # 太短（<3）
    "x" * 33,        # 太长（>32）
])
def test_register_invalid_username_rejected(client, bad_username):
    """username 仅允许字母数字下划线连字符，长度 3-32。"""
    res = client.post("/api/v1/auth/register", json={
        "username": bad_username,
        "password": "Pass1234!",
        "name": "X",
    })
    assert res.status_code == 422


def test_register_without_email_succeeds(client):
    """email 可选：不带 email 也能注册。"""
    res = client.post("/api/v1/auth/register", json={
        "username": "noemail",
        "password": "Pass1234!",
        "name": "无邮箱",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "noemail"
    assert data["email"] is None


def test_register_duplicate_username_409(client, registered_user):
    """重复用户名注册返回 409。"""
    res = client.post("/api/v1/auth/register", json={
        "username": registered_user["username"],
        "password": "Pass1234!",
        "name": "重复",
    })
    assert res.status_code == 409

