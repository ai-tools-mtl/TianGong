# apps/api/app/ai/tools.py
"""agent 工具（spec 合规）：rag_search 等 @tool，agent 在 loop 中按需调用。

替代旧 orchestrator._retrieve_knowledge 的预检索布尔守卫（Task 3 临时返回 None）。
"""
import uuid as _uuid
from typing import Any

from langchain_core.tools import tool


@tool("rag_search")
def rag_search_tool(query: str, user_id: str, db_session: Any = None) -> list[dict]:
    """检索用户知识库（RAG）。当需要参考历史案例、已有交底书、知识库文档时调用。

    Args:
        query: 检索查询（技术关键词、问题描述）
        user_id: 用户 ID（限定检索范围到该用户的知识库）
        db_session: 数据库会话（由 agent runtime 注入）

    Returns:
        检索到的知识片段列表，每项含 content/section_key/project_title。
    """
    from app.rag.retriever import retrieve

    try:
        uid = _uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return []
    results = retrieve(db_session, user_id=uid, query=query)
    return [
        {
            "content": r.content,
            "section_key": r.source_section_key,
            "project_title": r.project_title,
        }
        for r in results
    ]
