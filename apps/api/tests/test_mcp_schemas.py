# apps/api/tests/test_mcp_schemas.py
"""McpServer schemas 单元测试（masking + transport 校验 + partial update）。"""
import pytest

from app.schemas.mcp import (
    McpGlobalEnabled, McpServerCreate, McpServerOut, McpServerUpdate, McpTestResult,
)


def test_create_stdio_ok():
    s = McpServerCreate(name="fs", transport="stdio", command="npx", args=["-y", "x"])
    assert s.transport == "stdio"
    assert s.enabled is True  # 默认


def test_create_rejects_bad_transport():
    with pytest.raises(Exception):
        McpServerCreate(name="x", transport="websocket")  # type: ignore[arg-type]


def test_update_all_optional():
    u = McpServerUpdate()
    assert u.name is None
    assert u.enabled is None


def test_test_result_shape():
    r = McpTestResult(ok=True, tool_count=2, tool_names=["a", "b"], error=None)
    assert r.ok is True and r.tool_count == 2


def test_global_enabled():
    assert McpGlobalEnabled(enabled=True).enabled is True
