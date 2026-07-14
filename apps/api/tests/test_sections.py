"""章节 API 测试（含创建项目自动生成章节）。"""


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })


def test_create_project_generates_sections(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    _login(client, registered_user)

    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]

    res = client.get(f"/api/v1/projects/{project_id}/sections")
    assert res.status_code == 200
    sections = res.json()
    assert len(sections) == 8
    assert sections[0]["key"] == "name"
    assert sections[0]["status"] == "empty"
    assert sections[0]["content"] is None


def test_update_section_content(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    _login(client, registered_user)

    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]
    sections = client.get(f"/api/v1/projects/{project_id}/sections").json()
    section_id = sections[0]["id"]

    res = client.patch(f"/api/v1/sections/{section_id}", json={
        "content": {"type": "doc", "content": [{"type": "paragraph"}]},
        "status": "drafting",
    })
    assert res.status_code == 200
    assert res.json()["status"] == "drafting"
    assert res.json()["content"] is not None


def test_update_section_invalid_status(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    _login(client, registered_user)

    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]
    sections = client.get(f"/api/v1/projects/{project_id}/sections").json()

    res = client.patch(f"/api/v1/sections/{sections[0]['id']}", json={"status": "bogus"})
    assert res.status_code == 422
