def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })


def _make_project_with_section(client, db_session):
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    res = client.post("/api/v1/projects", json={"title": "版本测试"})
    pid = res.json()["id"]
    sections = client.get(f"/api/v1/projects/{pid}/sections").json()
    return sections[0]["id"]


def test_create_version(client, registered_user, db_session):
    _login(client, registered_user)
    sid = _make_project_with_section(client, db_session)
    res = client.post(f"/api/v1/sections/{sid}/versions", json={"note": "手动快照"})
    assert res.status_code == 201
    assert res.json()["note"] == "手动快照"


def test_list_versions(client, registered_user, db_session):
    _login(client, registered_user)
    sid = _make_project_with_section(client, db_session)
    client.post(f"/api/v1/sections/{sid}/versions", json={"note": "v1"})
    client.post(f"/api/v1/sections/{sid}/versions", json={"note": "v2"})
    res = client.get(f"/api/v1/sections/{sid}/versions")
    assert res.status_code == 200
    assert len(res.json()) == 2
