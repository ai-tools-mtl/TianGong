def test_not_found_returns_404(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    res = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404
    data = res.json()
    assert data["code"] == "not_found"


def test_unauthorized_returns_401_without_detail(client):
    res = client.get("/api/v1/projects")
    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"


def test_validation_error_returns_422(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    # 空标题违反 min_length
    res = client.post("/api/v1/projects", json={"title": ""})
    assert res.status_code == 422
