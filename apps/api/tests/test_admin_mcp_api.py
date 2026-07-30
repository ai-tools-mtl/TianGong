# apps/api/tests/test_admin_mcp_api.py
"""admin MCP API 测试：CRUD + 全局开关 + 测试连接 + 权限。"""


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })


def _make_admin(client, registered_user, db_session):
    from uuid import UUID
    from app.models import User
    user = db_session.query(User).filter_by(id=UUID(registered_user["id"])).first()
    user.role = "admin"
    db_session.commit()


def test_create_list_get_update_delete(client, registered_user, db_session):
    """admin 全流程 CRUD。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    # create
    resp = client.post("/api/v1/admin/mcp/servers", json={
        "name": "weather", "transport": "http", "url": "https://x/sse",
        "headers": {"Authorization": "Bearer secret"},
    })
    assert resp.status_code == 200, resp.text
    sid = resp.json()["id"]
    # 凭据 masking：不回明文
    assert resp.json()["headers"]["Authorization"] == {"has_value": True}

    # list
    resp = client.get("/api/v1/admin/mcp/servers")
    assert resp.status_code == 200
    assert any(s["id"] == sid for s in resp.json())

    # get
    resp = client.get(f"/api/v1/admin/mcp/servers/{sid}")
    assert resp.json()["name"] == "weather"

    # update（不传 headers → 保留旧值，仍 has_value）
    resp = client.put(f"/api/v1/admin/mcp/servers/{sid}", json={
        "name": "weather", "transport": "http", "url": "https://y/sse", "enabled": False,
    })
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    assert resp.json()["headers"]["Authorization"] == {"has_value": True}

    # delete
    resp = client.delete(f"/api/v1/admin/mcp/servers/{sid}")
    assert resp.json() == {"ok": True}


def test_global_enabled_roundtrip(client, registered_user, db_session):
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    resp = client.get("/api/v1/admin/mcp/enabled")
    assert resp.json()["enabled"] is True  # 默认

    resp = client.put("/api/v1/admin/mcp/enabled", json={"enabled": False})
    assert resp.status_code == 200

    resp = client.get("/api/v1/admin/mcp/enabled")
    assert resp.json()["enabled"] is False


def test_non_admin_forbidden(client, registered_user):
    """普通用户 → 403。"""
    _login(client, registered_user)
    resp = client.get("/api/v1/admin/mcp/servers")
    assert resp.status_code == 403


def test_test_endpoint(client, registered_user, db_session, monkeypatch):
    """/test 端点：monkeypatch service.test_mcp_server。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    # 先建一个 server
    r = client.post("/api/v1/admin/mcp/servers", json={
        "name": "fs", "transport": "http", "url": "https://x/sse",
    })
    sid = r.json()["id"]

    from app.services import mcp_config_service as svc
    from app.schemas.mcp import McpTestResult
    monkeypatch.setattr(
        svc, "test_mcp_server",
        lambda db, *, server_id: McpTestResult(ok=True, tool_count=1, tool_names=["search"], error=None),
    )

    resp = client.post(f"/api/v1/admin/mcp/servers/{sid}/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["tool_names"] == ["search"]
