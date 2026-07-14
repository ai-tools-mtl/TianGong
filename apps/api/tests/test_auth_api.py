def test_register_success(client):
    res = client.post("/api/v1/auth/register", json={
        "email": "new@example.com",
        "password": "Pass1234!",
        "name": "新用户",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "new@example.com"
    assert data["role"] == "user"
    assert "id" in data


def test_register_duplicate(client, registered_user):
    res = client.post("/api/v1/auth/register", json={
        "email": registered_user["email"],
        "password": "Pass1234!",
        "name": "重复",
    })
    assert res.status_code == 409


def test_login_success_sets_cookie(client, registered_user):
    res = client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    assert res.status_code == 200
    assert "access_token" in res.cookies
    assert "refresh_token" in res.cookies


def test_login_wrong_password(client, registered_user):
    res = client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": "wrongpass",
    })
    assert res.status_code == 401


def test_me_requires_auth(client):
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_me_returns_user(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200
    assert res.json()["email"] == registered_user["email"]


def test_logout_clears_cookies(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 200
    assert res.cookies.get("access_token") in (None, "")
