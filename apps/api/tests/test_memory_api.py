"""用户长期记忆 API 测试。"""


def _login(client, registered_user):
    """helper：登录拿 cookie。

    login 端点接收 JSON body（LoginRequest），故用 json=（非 form data）。
    """
    r = client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert r.status_code == 200


def _no_embed(monkeypatch):
    """mock embedding，避免依赖外部 API（与 service 测试一致）。"""
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)


def test_list_memories_empty(client, registered_user):
    """空列表。"""
    _login(client, registered_user)
    r = client.get("/api/v1/memories")
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_list_memory(client, registered_user, monkeypatch):
    """创建后能列出。"""
    _login(client, registered_user)
    _no_embed(monkeypatch)

    r = client.post("/api/v1/memories", json={"content": "偏好简洁风格"})
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "偏好简洁风格"
    assert data["source"] == "manual"

    r2 = client.get("/api/v1/memories")
    assert len(r2.json()) == 1


def test_update_memory(client, registered_user, monkeypatch):
    """修改记忆。"""
    _login(client, registered_user)
    _no_embed(monkeypatch)

    created = client.post("/api/v1/memories", json={"content": "原文"}).json()
    r = client.patch(f"/api/v1/memories/{created['id']}", json={"content": "改后"})
    assert r.status_code == 200
    assert r.json()["content"] == "改后"


def test_delete_memory(client, registered_user, monkeypatch):
    """删除记忆。"""
    _login(client, registered_user)
    _no_embed(monkeypatch)

    created = client.post("/api/v1/memories", json={"content": "待删"}).json()
    r = client.delete(f"/api/v1/memories/{created['id']}")
    assert r.status_code == 200
    assert client.get("/api/v1/memories").json() == []


def test_content_too_long_rejected(client, registered_user):
    """超 500 字被 Pydantic 拒绝。"""
    _login(client, registered_user)
    r = client.post("/api/v1/memories", json={"content": "x" * 501})
    assert r.status_code == 422
