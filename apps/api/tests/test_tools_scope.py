"""create_agent_tools 的 scope 白名单单元测试。

直接测工厂函数（不走 build_agent / deepagents），隔离地验证工具可见性策略：
- scope="init"：rag_search + save_memory 全保留（init 助手参与正文生成，需检索能力）
- scope="section"（默认）：rag_search + save_memory 全保留
- 未知 scope：宽放（不过滤，等同 section）

MCP 工具不在 BUILTIN_TOOLS 内，不受 scope 影响——本测试 mock 掉 load_mcp_tools
返回空，聚焦白名单逻辑本身。
"""
import asyncio
import uuid


def _mock_mcp_empty(monkeypatch):
    """mock load_mcp_tools 返回空列表，隔离白名单逻辑。"""
    from app.ai import tools as tools_mod

    async def _empty(_db):
        return []

    monkeypatch.setattr(tools_mod, "load_mcp_tools", _empty)


def _tool_names(tools) -> set[str]:
    return {getattr(t, "name", None) for t in tools}


def test_create_agent_tools_init_scope(monkeypatch, db_session):
    """scope='init' 返回 rag_search + save_memory（全保留，与 section 一致）。"""
    _mock_mcp_empty(monkeypatch)
    from app.ai.tools import create_agent_tools

    tools = asyncio.run(create_agent_tools(db_session, uuid.uuid4(), scope="init"))
    names = _tool_names(tools)
    assert "save_memory" in names
    assert "rag_search" in names


def test_create_agent_tools_section_scope_default(monkeypatch, db_session):
    """默认 scope（section）返回 rag_search + save_memory（全保留）。"""
    _mock_mcp_empty(monkeypatch)
    from app.ai.tools import create_agent_tools

    # 不传 scope，走默认值 "section"
    tools = asyncio.run(create_agent_tools(db_session, uuid.uuid4()))
    names = _tool_names(tools)
    assert "rag_search" in names
    assert "save_memory" in names

    # 显式传 section 同样全保留
    tools2 = asyncio.run(create_agent_tools(db_session, uuid.uuid4(), scope="section"))
    assert _tool_names(tools2) == names


def test_create_agent_tools_unknown_scope_passthrough(monkeypatch, db_session):
    """未知 scope 宽放（不过滤），等同 section。"""
    _mock_mcp_empty(monkeypatch)
    from app.ai.tools import create_agent_tools

    tools = asyncio.run(create_agent_tools(db_session, uuid.uuid4(), scope="whoami"))
    names = _tool_names(tools)
    assert "rag_search" in names
    assert "save_memory" in names


def test_create_agent_tools_mcp_not_filtered_by_scope(monkeypatch, db_session):
    """MCP 工具不在 BUILTIN_TOOLS 内，init scope 也不应过滤它。

    模拟一个假 MCP 工具，验证 init scope 下它仍保留——白名单只管内置工具。
    """
    from langchain_core.tools import tool as lc_tool
    from app.ai import tools as tools_mod

    @lc_tool("fake_mcp_tool")
    def _fake(query: str) -> str:
        """fake mcp tool."""
        return "ok"

    async def _fake_mcp(_db):
        return [_fake]

    monkeypatch.setattr(tools_mod, "load_mcp_tools", _fake_mcp)

    tools = asyncio.run(tools_mod.create_agent_tools(db_session, uuid.uuid4(), scope="init"))
    names = _tool_names(tools)
    # init 现保留全部内置工具 + MCP 工具
    assert "save_memory" in names
    assert "rag_search" in names
    assert "fake_mcp_tool" in names
