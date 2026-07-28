# apps/api/app/ai/tools.py
"""agent 工具：rag_search / save_memory 等 @tool。

工具通过工厂函数 create_agent_tools(db, user_id) 装配，
user_id 与 db 由闭包绑定——LLM 无需（也无法）生成这些参数。

修复旧设计缺陷：旧 rag_search_tool(query, user_id, db_session) 让 LLM
生成 user_id/db_session，但 LLM 根本不知道这些值。闭包工厂在 build_agent
时用已知 user_id + db 绑定，LLM 只需生成 query/content。
"""
import uuid as _uuid
from typing import Any

from langchain_core.tools import tool


def create_agent_tools(db: Any, user_id):
    """构造绑定到当前用户的 agent 工具集合。

    Args:
        db: SQLAlchemy Session（由 build_agent 传入，agent 生命周期内有效）。
        user_id: 当前用户 ID（限定检索/写入范围到本人）。

    Returns:
        [rag_search, save_memory] —— 供 create_deep_agent(tools=...) 使用。
    """
    @tool("rag_search")
    def rag_search(query: str) -> list[dict]:
        """检索用户知识库（RAG）。当需要参考历史案例、已有交底书、知识库文档时调用。

        Args:
            query: 检索查询（技术关键词、问题描述）

        Returns:
            检索到的知识片段列表，每项含 content/section_key/project_title。
        """
        from app.rag.retriever import retrieve
        try:
            _uuid.UUID(str(user_id))  # 校验合法性
        except (ValueError, TypeError):
            return []
        results = retrieve(db, user_id=user_id, query=query)
        return [
            {
                "content": r.content,
                "section_key": r.source_section_key,
                "project_title": r.project_title,
            }
            for r in results
        ]

    @tool("save_memory")
    def save_memory(content: str) -> str:
        """当用户表达了值得长期记住的偏好、事实或领域约定时调用，将记忆保存到用户档案。

        何时调用：
        - 用户明确说「记住我喜欢...」「以后都用...」
        - 用户透露跨项目稳定的事实（如「我在某公司做新能源」）
        - 用户纠正你的写法并强调「应该这样写」

        何时不要调用：
        - 临时性信息（「我现在在写电池专利」）
        - 一次性任务细节、项目内具体决策（这些属于项目上下文，不存长期记忆）
        - 寒暄、简单问答、API key/密码（永不存）

        Args:
            content: 一条原子化记忆，建议一句话（≤200 字）。

        Returns:
            操作结果描述（已保存 / 已合并到已有记忆 / 未保存）。
        """
        from app.services.memory_service import (
            create_memory, find_similar_memory, update_memory, SOURCE_AGENT,
        )

        content = (content or "").strip()
        if not content:
            return "未保存：内容为空"

        # 去重：查找高度相似的已有记忆
        similar = find_similar_memory(db, user_id=user_id, content=content)
        if similar is not None:
            # 合并：相似度 ≥ 阈值，更新已有记忆
            update_memory(db, memory_id=similar.id, user_id=user_id, content=content)
            db.commit()
            return f"已合并更新已有记忆（原：「{similar.content[:50]}...」）"

        create_memory(db, user_id=user_id, content=content, source=SOURCE_AGENT)
        db.commit()
        return "已保存"

    return [rag_search, save_memory]
