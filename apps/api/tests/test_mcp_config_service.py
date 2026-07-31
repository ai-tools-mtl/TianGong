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


def test_test_mcp_server_empty_error_message_falls_back_to_type(db_session, monkeypatch):
    """异常 str(e) 为空时（如某些底层超时/连接异常），error 仍要有可诊断信息。"""
    from app.services import mcp_config_service as svc

    svc.create_mcp_server(
        db_session, name="empty", transport="http", url="https://x/sse", enabled=True,
    )
    server = svc.list_mcp_servers(db_session)[0]

    class _EmptyMsgError(Exception):
        pass  # str(e) == ""

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def get_tools(self): raise _EmptyMsgError()

    import app.services.mcp_config_service as mod
    monkeypatch.setattr(mod, "MultiServerMCPClient", _FakeClient)

    result = svc.test_mcp_server(db_session, server_id=server.id)
    assert result.ok is False
    # str(e) 为空时回退到 type 名，绝不返回空字符串
    assert result.error
    assert "_EmptyMsgError" in result.error


import pytest

from app.core.exceptions import ValidationError


def test_parse_json_standard_format():
    """标准 {"mcpServers": {...}} 格式 → 正确解析。"""
    from app.services import mcp_config_service as svc
    raw = {
        "mcpServers": {
            "feishu": {"command": "npx", "args": ["-y", "pkg"]},
        }
    }
    parsed = svc.parse_mcp_json(raw)
    assert len(parsed) == 1
    s = parsed[0]
    assert s["name"] == "feishu"
    assert s["transport"] == "stdio"
    assert s["command"] == "npx"
    assert s["args"] == ["-y", "pkg"]


def test_parse_json_bare_dict_format():
    """裸字典格式（省略 mcpServers 包裹）→ 正确解析。"""
    from app.services import mcp_config_service as svc
    raw = {
        "feishu": {"command": "cmd", "args": ["/c", "npx"]},
    }
    parsed = svc.parse_mcp_json(raw)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "feishu"
    assert parsed[0]["command"] == "cmd"


def test_parse_json_stdio_with_env():
    """stdio 形态读 env。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "s": {"command": "npx", "args": [], "env": {"API_KEY": "x"}},
    }})
    assert parsed[0]["env"] == {"API_KEY": "x"}
    assert parsed[0]["transport"] == "stdio"


def test_parse_json_http_default_transport():
    """有 url → 默认 transport=http，读 headers。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "w": {"url": "https://x/mcp", "headers": {"Authorization": "Bearer t"}},
    }})
    assert parsed[0]["transport"] == "http"
    assert parsed[0]["url"] == "https://x/mcp"
    assert parsed[0]["headers"] == {"Authorization": "Bearer t"}


def test_parse_json_sse_explicit_transport():
    """显式 transport: sse → transport=sse。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "w": {"transport": "sse", "url": "https://x/sse"},
    }})
    assert parsed[0]["transport"] == "sse"


def test_parse_json_url_ending_with_sse_auto_detects_sse():
    """URL 末尾是 /sse（无显式 transport）→ 自动按 sse 处理。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "w": {"url": "https://mcp.api-inference.modelscope.net/abc/sse"},
    }})
    assert parsed[0]["transport"] == "sse"


def test_parse_json_explicit_http_overrides_url_sse_suffix():
    """显式 transport: http 优先于 URL /sse 后缀推断。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "w": {"transport": "http", "url": "https://x/sse"},
    }})
    assert parsed[0]["transport"] == "http"


def test_parse_json_missing_command_and_url():
    """既无 command 又无 url → ValidationError，信息含 name。"""
    from app.services import mcp_config_service as svc
    with pytest.raises(ValidationError) as ei:
        svc.parse_mcp_json({"mcpServers": {"bad": {"foo": "bar"}}})
    assert "bad" in str(ei.value)


def test_parse_json_args_not_list():
    """args 非 list → ValidationError。"""
    from app.services import mcp_config_service as svc
    with pytest.raises(ValidationError):
        svc.parse_mcp_json({"mcpServers": {"s": {"command": "npx", "args": "not-a-list"}}})


def test_parse_json_value_not_dict():
    """server value 非 dict → ValidationError。"""
    from app.services import mcp_config_service as svc
    with pytest.raises(ValidationError) as ei:
        svc.parse_mcp_json({"mcpServers": {"s": "just-a-string"}})
    assert "s" in str(ei.value)


def test_parse_json_ignores_unknown_fields():
    """未知字段（type/disabled 等）忽略。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "s": {"command": "npx", "args": [], "type": "stdio", "disabled": False},
    }})
    assert parsed[0]["command"] == "npx"
    assert "type" not in parsed[0]
    assert "disabled" not in parsed[0]


def test_parse_json_empty():
    """空 mcpServers → 返回空列表（不报错）。"""
    from app.services import mcp_config_service as svc
    assert svc.parse_mcp_json({"mcpServers": {}}) == []
    assert svc.parse_mcp_json({}) == []
