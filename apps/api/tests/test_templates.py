"""模板 API 与章节 API 测试。"""


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })


def test_list_templates_includes_system(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    _login(client, registered_user)
    res = client.get("/api/v1/templates")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert any(t["is_system"] for t in data)


def test_get_template_detail(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    tpl = ensure_default_template(db_session)
    _login(client, registered_user)
    res = client.get(f"/api/v1/templates/{tpl.id}")
    assert res.status_code == 200
    assert len(res.json()["structure"]) == 8


def test_system_template_cannot_delete(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    tpl = ensure_default_template(db_session)
    _login(client, registered_user)
    res = client.delete(f"/api/v1/templates/{tpl.id}")
    assert res.status_code == 409
