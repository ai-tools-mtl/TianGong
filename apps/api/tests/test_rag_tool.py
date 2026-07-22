# apps/api/tests/test_rag_tool.py
"""RAG 工具测试：rag_search 作为 @tool，agent 可调用。"""


def test_rag_search_tool_is_registered():
    """rag_search 是 langchain @tool，有 name/description。"""
    from app.ai.tools import rag_search_tool
    assert rag_search_tool.name == "rag_search"
    assert "知识库" in rag_search_tool.description or "检索" in rag_search_tool.description


def test_rag_search_tool_returns_results(db_session, monkeypatch):
    """工具调用返回检索结果列表。"""
    from app.ai.tools import rag_search_tool
    from app.rag import retriever as retriever_mod

    class _FakeResult:
        content = "相关技术内容"
        score = 0.9
        source_section_key = "solution"
        project_title = "案例A"

    original = retriever_mod.retrieve
    retriever_mod.retrieve = lambda db, *, user_id, query, top_k=3: [_FakeResult()]
    try:
        results = rag_search_tool.invoke({
            "query": "技术方案",
            "user_id": "00000000-0000-0000-0000-000000000001",
            "db_session": db_session,
        })
    finally:
        retriever_mod.retrieve = original

    assert len(results) == 1
    assert results[0]["content"] == "相关技术内容"
    assert results[0]["section_key"] == "solution"
    assert results[0]["project_title"] == "案例A"


def test_rag_search_tool_invalid_user_id_returns_empty():
    """非法 user_id 返回空列表（不抛异常）。"""
    from app.ai.tools import rag_search_tool
    results = rag_search_tool.invoke({
        "query": "x",
        "user_id": "not-a-uuid",
        "db_session": None,
    })
    assert results == []
