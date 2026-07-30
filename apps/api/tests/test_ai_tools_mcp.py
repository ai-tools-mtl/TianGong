# apps/api/tests/test_ai_tools_mcp.py
"""load_mcp_tools 测试：全局开关关闭→空；无 server→空；server 加载成功→append；失败→跳过。"""


def test_load_mcp_tools_disabled_returns_empty(db_session):
    from app.services import mcp_config_service as svc
    svc.set_mcp_enabled(db_session, enabled=False)

    import asyncio
    from app.ai.tools import load_mcp_tools
    tools = asyncio.run(load_mcp_tools(db_session))
    assert tools == []


def test_load_mcp_tools_no_servers_returns_empty(db_session):
    from app.services import mcp_config_service as svc
    svc.set_mcp_enabled(db_session, enabled=True)
    # 无 server
    import asyncio
    from app.ai.tools import load_mcp_tools
    assert asyncio.run(load_mcp_tools(db_session)) == []


def test_load_mcp_tools_appends_and_skips_failures(db_session, monkeypatch):
    """两个 server：一个成功一个失败，只返回成功的工具，整体不抛。"""
    from app.services import mcp_config_service as svc
    svc.set_mcp_enabled(db_session, enabled=True)
    svc.create_mcp_server(db_session, name="ok", transport="http", url="https://a/sse", enabled=True)
    svc.create_mcp_server(db_session, name="bad", transport="http", url="https://b/sse", enabled=True)

    class _FakeTool:
        def __init__(self, n): self.name = n

    class _OkClient:
        def __init__(self, *a, **kw): pass
        async def get_tools(self): return [_FakeTool("search")]

    class _BadClient:
        def __init__(self, *a, **kw): pass
        async def get_tools(self): raise ConnectionError("down")

    # 按 server.name 路由不同 client
    import app.ai.tools as tools_mod

    def _fake_factory(connections, **kw):
        # connections 是 {name: cfg}，只有一个
        name = next(iter(connections))
        return _OkClient() if name == "ok" else _BadClient()

    monkeypatch.setattr(tools_mod, "MultiServerMCPClient", _fake_factory)

    import asyncio
    tools = asyncio.run(tools_mod.load_mcp_tools(db_session))
    assert len(tools) == 1  # 只成功 server 的 1 个工具，失败的被跳过
    assert tools[0].name == "search"


def test_create_agent_tools_is_async():
    """create_agent_tools 改成 async def（可被 await）。"""
    import inspect
    from app.ai.tools import create_agent_tools
    assert inspect.iscoroutinefunction(create_agent_tools)
