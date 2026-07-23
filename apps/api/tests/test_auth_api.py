import pytest

from tests.conftest import make_invite_code


def test_register_success(client, db_session):
    """凭有效邀请码注册成功。"""
    code = make_invite_code(db_session)
    res = client.post("/api/v1/auth/register", json={
        "username": "newuser",
        "password": "Pass1234!",
        "name": "新用户",
        "invite_code": code,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "newuser"
    assert data["role"] == "user"
    assert "id" in data


def test_register_without_invite_code_rejected(client):
    """内部产品化:无邀请码注册被拒(422)。"""
    res = client.post("/api/v1/auth/register", json={
        "username": "newuser",
        "password": "Pass1234!",
        "name": "新用户",
    })
    assert res.status_code == 422


def test_register_with_invalid_invite_code_rejected(client, db_session):
    """无效邀请码注册被拒(403,统一报「无效或已失效」防探测)。"""
    res = client.post("/api/v1/auth/register", json={
        "username": "newuser",
        "password": "Pass1234!",
        "name": "新用户",
        "invite_code": "NOTACODE",
    })
    assert res.status_code == 403


def test_register_consumes_invite_code(client, db_session):
    """单次邀请码核销后不能再用。"""
    code = make_invite_code(db_session, max_uses=1)
    # 第一次注册成功
    res1 = client.post("/api/v1/auth/register", json={
        "username": "user1",
        "password": "Pass1234!",
        "name": "一",
        "invite_code": code,
    })
    assert res1.status_code == 200
    # 同一码再注册(换用户名)应失败
    res2 = client.post("/api/v1/auth/register", json={
        "username": "user2",
        "password": "Pass1234!",
        "name": "二",
        "invite_code": code,
    })
    assert res2.status_code == 403


def test_register_duplicate(client, registered_user, db_session):
    """重复用户名:用 max_uses=2 邀请码,确保失败原因是 409 而非码用尽。"""
    code = make_invite_code(db_session, max_uses=2)
    res = client.post("/api/v1/auth/register", json={
        "username": registered_user["username"],
        "password": "Pass1234!",
        "name": "重复",
        "invite_code": code,
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


# ── username-specific：格式校验(schema 层 422,不需要有效邀请码)──

@pytest.mark.parametrize("bad_username", [
    "中文用户",      # 中文
    "has space",     # 空格
    "user@name",     # 特殊字符
    "ab",            # 太短（<3）
    "x" * 33,        # 太长（>32）
])
def test_register_invalid_username_rejected(client, bad_username):
    """username 仅允许字母数字下划线连字符，长度 3-32。

    schema 层校验在 body 解析阶段,先于邀请码核销,故无需有效码。
    """
    res = client.post("/api/v1/auth/register", json={
        "username": bad_username,
        "password": "Pass1234!",
        "name": "X",
        "invite_code": "ANYCODE",
    })
    assert res.status_code == 422


def test_register_without_email_succeeds(client, db_session):
    """email 可选：不带 email 也能注册。"""
    code = make_invite_code(db_session)
    res = client.post("/api/v1/auth/register", json={
        "username": "noemail",
        "password": "Pass1234!",
        "name": "无邮箱",
        "invite_code": code,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "noemail"
    assert data["email"] is None


def test_register_duplicate_username_409(client, registered_user, db_session):
    """重复用户名注册返回 409。"""
    code = make_invite_code(db_session, max_uses=2)
    res = client.post("/api/v1/auth/register", json={
        "username": registered_user["username"],
        "password": "Pass1234!",
        "name": "重复",
        "invite_code": code,
    })
    assert res.status_code == 409
