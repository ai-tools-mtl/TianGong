"""专利检索 API 测试。

Mock 桩模式：无 PATENTSNAP_API_KEY 时 patent_client 返回 3 条样例专利。
"""


def _login(client, registered_user):
    r = client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert r.status_code == 200


def _create_project(db_session, registered_user):
    from app.models import Project
    import uuid

    uid = uuid.UUID(registered_user["id"])
    p = Project(user_id=uid, title="测试专利项目")
    db_session.add(p)
    db_session.commit()
    return str(p.id)


def test_search_returns_mock(client, registered_user, db_session):
    """无 key 时检索返回 Mock 桩数据，source 标记 mock（前端提示示例数据）。"""
    _login(client, registered_user)
    pid = _create_project(db_session, registered_user)

    r = client.post(f"/api/v1/projects/{pid}/patents/search", json={"query": "图像识别"})
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "图像识别"
    assert data["saved_to"] == pid
    assert data["source"] == "mock"
    assert len(data["results"]) == 3
    # 验证字段结构
    p0 = data["results"][0]
    assert "title" in p0
    assert "patent_number" in p0
    assert "relevance" in p0


def test_search_persists_to_prior_art(client, registered_user, db_session):
    """检索结果（含 source 降级标记）持久化到 project.prior_art_refs。"""
    _login(client, registered_user)
    pid = _create_project(db_session, registered_user)

    client.post(f"/api/v1/projects/{pid}/patents/search", json={"query": "电池"})

    # GET 读回
    r = client.get(f"/api/v1/projects/{pid}/patents")
    assert r.status_code == 200
    data = r.json()
    assert data is not None
    assert data["query"] == "电池"
    assert data["source"] == "mock"
    assert len(data["results"]) > 0


def test_get_patents_empty(client, registered_user, db_session):
    """未检索过时 GET 返回 null。"""
    _login(client, registered_user)
    pid = _create_project(db_session, registered_user)

    r = client.get(f"/api/v1/projects/{pid}/patents")
    assert r.status_code == 200
    assert r.json() is None


def test_search_empty_query(client, registered_user, db_session):
    """纯空格关键词报错（service 层 ValidationError → 400）。"""
    _login(client, registered_user)
    pid = _create_project(db_session, registered_user)

    # "  " 通过 pydantic min_length=1（非空串），但在 service 层 strip() 为空 → 400
    r = client.post(f"/api/v1/projects/{pid}/patents/search", json={"query": "  "})
    assert r.status_code in (400, 422)


def test_search_not_found_project(client, registered_user):
    """不存在/越权的项目报 404。"""
    _login(client, registered_user)
    r = client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/patents/search",
        json={"query": "测试"},
    )
    assert r.status_code == 404
