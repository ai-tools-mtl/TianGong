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


def test_create_memory_calls_refresh_after_commit(client, registered_user, monkeypatch):
    """C1 修复：POST /memories commit 后必须 db.refresh(mem)。

    expire_on_commit=False 下，读 server-default 时间戳需显式 refresh。
    SQLite 不执行 server_default，无法断言时间戳非空，故 spy refresh 调用验证修复存在。
    """
    from sqlalchemy.orm import Session
    _no_embed(monkeypatch)
    _login(client, registered_user)

    call_count = {"n": 0}
    orig_refresh = Session.refresh

    def spy_refresh(self, *args, **kwargs):
        call_count["n"] += 1
        return orig_refresh(self, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", spy_refresh)

    r = client.post("/api/v1/memories", json={"content": "偏好简洁风格"})
    assert r.status_code == 200, r.text
    assert call_count["n"] >= 1, "POST /memories commit 后必须调用 db.refresh（C1 修复）"


def test_update_memory_calls_refresh_after_commit(client, registered_user, monkeypatch):
    """C1 修复：PATCH /memories/{id} commit 后必须 db.refresh(mem)。"""
    from sqlalchemy.orm import Session
    _no_embed(monkeypatch)
    _login(client, registered_user)

    # 先创建一条记忆（创建路径也会调 refresh，但我们只关心 update 的 refresh）
    created = client.post("/api/v1/memories", json={"content": "原文"}).json()

    # 重置计数，只统计 update 的 refresh
    call_count = {"n": 0}
    orig_refresh = Session.refresh

    def spy_refresh(self, *args, **kwargs):
        call_count["n"] += 1
        return orig_refresh(self, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", spy_refresh)

    r = client.patch(f"/api/v1/memories/{created['id']}", json={"content": "新偏好"})
    assert r.status_code == 200, r.text
    assert call_count["n"] >= 1, "PATCH /memories commit 后必须调用 db.refresh（C1 修复）"
