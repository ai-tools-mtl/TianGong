"""ToolTimeoutMiddleware 单元测试（层 1：工具级超时）。

直接测 middleware 的 awrap_tool_call 钩子，不走 deepagents / agent loop：
- 正常调用：透传不干预
- 慢工具：超时返回 ToolMessage(status="error")
- GraphBubbleUp：控制流信号必须透传，不被超时吞掉
- 分类超时：rag_search/save_memory/MCP 工具分别返回不同阈值
"""
import asyncio

import pytest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest


def _make_request(tool_name: str, tool_call_id: str = "call_1") -> ToolCallRequest:
    """构造最小 ToolCallRequest（tool=None，tool_call 带 name/args/id）。

    state/runtime middleware 不读，传 None 占位（dataclass 要求位置填齐）。
    """
    return ToolCallRequest(
        tool_call={"name": tool_name, "args": {}, "id": tool_call_id, "type": "tool_call"},
        tool=None,
        state=None,
        runtime=None,
    )


def test_timeout_middleware_normal_call_passthrough():
    """工具正常返回时，middleware 透传 handler 结果，不干预。"""
    from app.ai.tool_timeout import ToolTimeoutMiddleware

    mw = ToolTimeoutMiddleware()

    async def handler(_req):
        return ToolMessage(content="ok", tool_call_id="call_1", name="rag_search")

    result = asyncio.run(mw.awrap_tool_call(_make_request("rag_search"), handler))
    assert isinstance(result, ToolMessage)
    assert result.content == "ok"


def test_timeout_middleware_triggers_on_slow_tool():
    """慢工具超时后返回 ToolMessage(status="error")，content 含「超时」。

    用极小的 TOOL_TIMEOUTS 值 + 长 sleep 模拟挂起，验证不阻塞、返回 error。
    """
    from app.ai.tool_timeout import ToolTimeoutMiddleware

    mw = ToolTimeoutMiddleware()
    # 注入一个极短超时，模拟 rag_search 挂起（不真等 15s）
    mw.TOOL_TIMEOUTS = {"rag_search": 0.05}

    async def slow_handler(_req):
        await asyncio.sleep(10)  # 模拟工具挂起
        return ToolMessage(content="never", tool_call_id="call_1", name="rag_search")

    result = asyncio.run(mw.awrap_tool_call(_make_request("rag_search"), slow_handler))
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "超时" in result.content
    assert result.tool_call_id == "call_1"
    assert result.name == "rag_search"


def test_timeout_middleware_preserves_graph_bubbleup():
    """handler 抛 GraphBubbleUp（interrupt 等控制流信号）时必须透传，不被超时吞掉。"""
    from app.ai.tool_timeout import ToolTimeoutMiddleware

    mw = ToolTimeoutMiddleware()

    async def handler(_req):
        raise GraphBubbleUp("interrupt")

    with pytest.raises(GraphBubbleUp):
        asyncio.run(mw.awrap_tool_call(_make_request("rag_search"), handler))


def test_timeout_middleware_classifies_timeout_by_tool_name():
    """_resolve_timeout 按工具来源分类：内置查表、MCP 宽松、其它内置兜底。"""
    from app.ai.tool_timeout import ToolTimeoutMiddleware

    mw = ToolTimeoutMiddleware()
    # 内置工具查表
    assert mw._resolve_timeout("rag_search") == 15.0
    assert mw._resolve_timeout("save_memory") == 10.0
    # MCP / 外部工具（不在 BUILTIN_TOOLS 内）用宽松默认
    assert mw._resolve_timeout("firecrawl_scrape") == mw.MCP_DEFAULT_TIMEOUT
    # 未在 TOOL_TIMEOUTS 但属于内置的——目前无此情况，兜底值验证
    # （BUILTIN_TOOLS = {rag_search, save_memory}，两者都在 TOOL_TIMEOUTS，
    #  此分支为防御性兜底，用 monkeypatch 临时加一个内置名测试）
    import app.ai.tools as tools_mod
    orig = tools_mod.BUILTIN_TOOLS
    tools_mod.BUILTIN_TOOLS = frozenset({"rag_search", "save_memory", "future_tool"})
    try:
        assert mw._resolve_timeout("future_tool") == mw.BUILTIN_FALLBACK_TIMEOUT
    finally:
        tools_mod.BUILTIN_TOOLS = orig
