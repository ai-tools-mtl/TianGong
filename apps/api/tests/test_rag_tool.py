# apps/api/tests/test_rag_tool.py
"""RAG 工具测试：rag_search 作为 @tool，通过闭包工厂装配。"""


def test_rag_search_tool_is_registered():
    """工厂产出的 rag_search 是 langchain @tool，有 name/description。"""
    from app.ai.tools import create_agent_tools
    tools = create_agent_tools(db=None, user_id="00000000-0000-0000-0000-000000000001")
    rag = tools[0]
    assert rag.name == "rag_search"
    assert "知识库" in rag.description or "检索" in rag.description


def test_save_memory_tool_is_registered():
    """工厂产出 save_memory 工具。"""
    from app.ai.tools import create_agent_tools
    tools = create_agent_tools(db=None, user_id="00000000-0000-0000-0000-000000000001")
    save_mem = tools[1]
    assert save_mem.name == "save_memory"
    assert "记忆" in save_mem.description


def test_rag_search_tool_returns_results(db_session, monkeypatch):
    """工具调用返回检索结果列表。"""
    from app.ai.tools import create_agent_tools
    from app.rag import retriever as retriever_mod

    uid = "00000000-0000-0000-0000-000000000001"

    class _FakeResult:
        content = "相关技术内容"
        score = 0.9
        source_section_key = "solution"
        project_title = "案例A"

    original = retriever_mod.retrieve
    retriever_mod.retrieve = lambda db, *, user_id, query, top_k=3: [_FakeResult()]
    try:
        tools = create_agent_tools(db=db_session, user_id=uid)
        results = tools[0].invoke({"query": "技术方案"})
    finally:
        retriever_mod.retrieve = original

    assert len(results) == 1
    assert results[0]["content"] == "相关技术内容"
    assert results[0]["section_key"] == "solution"
    assert results[0]["project_title"] == "案例A"


def test_rag_search_tool_invalid_user_id_returns_empty():
    """非法 user_id 返回空列表（不抛异常）。"""
    from app.ai.tools import create_agent_tools
    tools = create_agent_tools(db=None, user_id="not-a-uuid")
    results = tools[0].invoke({"query": "x"})
    assert results == []
