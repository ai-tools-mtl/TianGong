# apps/api/tests/test_mcp_config_service.py
"""mcp_config_service 测试：CRUD + 凭据加密 masking + 全局开关。"""


def test_create_then_read_masks_secrets(db_session):
    from app.services import mcp_config_service as svc

    s = svc.create_mcp_server(
        db_session, name="weather", transport="http", url="https://x/sse",
        headers={"Authorization": "Bearer secret123"},
    )
    # 落库：headers_encrypted 是加密后的 dict，不是明文
    assert s.headers_encrypted["Authorization"] != "Bearer secret123"

    out = svc.to_out(s)
    # 输出：只有 has_value，无明文
    assert out["headers"]["Authorization"] == {"has_value": True}


def test_update_blank_keeps_old_secret(db_session):
    from app.services import mcp_config_service as svc

    svc.create_mcp_server(
        db_session, name="fs", transport="stdio", command="npx",
        env={"API_KEY": "oldval"},
    )
    server_id = svc.list_mcp_servers(db_session)[0].id
    # 更新时所有可选字段传 None → env 保留旧值
    s = svc.update_mcp_server(db_session, server_id=server_id,
                              name="fs", transport="stdio", command="npx", args=None,
                              url=None, headers=None, env=None, enabled=True)
    # 旧 env 仍在
    assert s.env_encrypted is not None


def test_global_enabled_default_true(db_session):
    from app.services import mcp_config_service as svc

    assert svc.get_mcp_enabled(db_session) is True  # 未设置时默认开
    svc.set_mcp_enabled(db_session, enabled=False)
    assert svc.get_mcp_enabled(db_session) is False


def test_resolve_returns_plaintext(db_session):
    from app.services import mcp_config_service as svc

    svc.create_mcp_server(
        db_session, name="weather", transport="http", url="https://x/sse",
        headers={"Authorization": "Bearer secret123"}, enabled=True,
    )
    resolved = svc.resolve_mcp_servers(db_session)
    assert len(resolved) == 1
    assert resolved[0]["headers"]["Authorization"] == "Bearer secret123"  # 解密成明文
    assert resolved[0]["name"] == "weather"


def test_test_mcp_server_success(db_session, monkeypatch):
    """测试连接成功：monkeypatch MultiServerMCPClient 返回假工具。"""
    from app.services import mcp_config_service as svc

    svc.create_mcp_server(
        db_session, name="weather", transport="http", url="https://x/sse",
        headers={"Authorization": "Bearer t"}, enabled=True,
    )
    server = svc.list_mcp_servers(db_session)[0]

    class _FakeTool:
        def __init__(self, n): self.name = n

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def get_tools(self): return [_FakeTool("search"), _FakeTool("fetch")]

    # 懒 import，patch 模块属性
    import app.services.mcp_config_service as mod
    monkeypatch.setattr(mod, "MultiServerMCPClient", _FakeClient)

    result = svc.test_mcp_server(db_session, server_id=server.id)
    assert result.ok is True
    assert result.tool_count == 2
    assert result.tool_names == ["search", "fetch"]
    assert result.error is None


def test_test_mcp_server_failure(db_session, monkeypatch):
    """测试连接失败：返回 ok=False + error，不抛异常。"""
    from app.services import mcp_config_service as svc

    svc.create_mcp_server(
        db_session, name="dead", transport="http", url="https://dead/sse", enabled=True,
    )
    server = svc.list_mcp_servers(db_session)[0]

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def get_tools(self): raise ConnectionError("refused")

    import app.services.mcp_config_service as mod
    monkeypatch.setattr(mod, "MultiServerMCPClient", _FakeClient)

    result = svc.test_mcp_server(db_session, server_id=server.id)
    assert result.ok is False
    assert result.error is not None
    assert "refused" in result.error
