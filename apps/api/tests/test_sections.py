"""章节 API 测试（含创建项目自动生成章节）。"""


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
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


def _make_section(db_session, registered_user):
    """建项目取第一个章节。返回 (section, user)。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from app.models import User
    from sqlalchemy import select

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    p = create_project(db_session, user=user, title="测试发明")
    section = list_sections(db_session, user_id=user.id, project_id=str(p.id))[0]
    return section, user


def test_update_section_version_mismatch_raises_conflict(db_session, registered_user):
    """乐观锁：expected_version 不匹配时抛 ConflictError。"""
    from app.core.exceptions import ConflictError
    from app.services.section_service import update_section

    section, user = _make_section(db_session, registered_user)
    assert section.version == 1

    import pytest
    with pytest.raises(ConflictError):
        update_section(
            db_session, user_id=user.id, section_id=str(section.id),
            content={"type": "doc"}, expected_version=999,
        )


def test_update_section_version_match_increments(db_session, registered_user):
    """乐观锁：expected_version 匹配时更新成功且 version +1。"""
    from app.services.section_service import update_section

    section, user = _make_section(db_session, registered_user)
    assert section.version == 1

    updated = update_section(
        db_session, user_id=user.id, section_id=str(section.id),
        content={"type": "doc"}, expected_version=1,
    )
    assert updated.version == 2


def test_update_section_without_expected_version_skips_lock(db_session, registered_user):
    """不传 expected_version 时跳过乐观锁（向后兼容旧客户端）。"""
    from app.services.section_service import update_section

    section, user = _make_section(db_session, registered_user)
    updated = update_section(
        db_session, user_id=user.id, section_id=str(section.id),
        content={"type": "doc"},
    )
    assert updated.version == 2


def test_api_update_section_optimistic_lock_409(client, registered_user, db_session):
    """API 层：expected_version 不匹配返回 409。"""
    section, _user = _make_section(db_session, registered_user)
    _login(client, registered_user)

    res = client.patch(f"/api/v1/sections/{section.id}", json={
        "content": {"type": "doc"},
        "expected_version": 999,
    })
    assert res.status_code == 409


def test_api_update_section_returns_version(client, registered_user, db_session):
    """API 层：成功更新时响应含 version 字段。"""
    section, _user = _make_section(db_session, registered_user)
    _login(client, registered_user)

    res = client.patch(f"/api/v1/sections/{section.id}", json={
        "content": {"type": "doc"},
        "expected_version": 1,
    })
    assert res.status_code == 200
    assert res.json()["version"] == 2
