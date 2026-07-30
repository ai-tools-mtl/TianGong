# apps/api/app/ai/tools.py
"""agent 工具：rag_search / save_memory 等 @tool。

工具通过工厂函数 create_agent_tools(db, user_id) 装配，
user_id 与 db 由闭包绑定——LLM 无需（也无法）生成这些参数。

修复旧设计缺陷：旧 rag_search_tool(query, user_id, db_session) 让 LLM
生成 user_id/db_session，但 LLM 根本不知道这些值。闭包工厂在 build_agent
时用已知 user_id + db 绑定，LLM 只需生成 query/content。
"""
import logging
import uuid as _uuid
from typing import Any

from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


async def create_agent_tools(db: Any, user_id):
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
        # 工具是事务边界：检索失败必须 rollback，避免毒化 agent loop 后续查询
        try:
            results = retrieve(db, user_id=user_id, query=query)
        except Exception:
            db.rollback()
            return []
        return [
            {
                "content": r.content,
                "section_key": r.source_section_key,
                "project_title": r.project_title,
            }
            for r in results
        ]

    @tool("save_memory")
    def save_memory(content: str, memory_type: str = "preference") -> str:
        """当用户表达了值得长期记住的偏好、事实或领域约定时调用，将记忆保存到用户档案。

        何时调用：
        - 用户明确说「记住我喜欢...」「以后都用...」
        - 用户透露跨项目稳定的事实（如「我在某公司做新能源」）
        - 用户纠正你的写法并强调「应该这样写」
        - [S2-3] 首次对话时识别到用户职业/专业水平（如「我是专利代理人」「我是机械工程师」），
          用 memory_type="profile" 保存，系统会据此调节表达密度

        何时不要调用：
        - 临时性信息（「我现在在写电池专利」）
        - 一次性任务细节、项目内具体决策（这些属于项目上下文，不存长期记忆）
        - 寒暄、简单问答、API key/密码（永不存）

        Args:
            content: 一条原子化记忆，建议一句话（≤200 字）。
            memory_type: 记忆类型，决定保存位置。
                - "preference"（默认）：用户偏好/事实类记忆（写作风格、领域约定等）
                - "profile"：用户画像（职业、专业水平），用于调节系统表达密度

        Returns:
            操作结果描述（已保存 / 已合并到已有记忆 / 未保存）。
        """
        from app.models.user_memory import SOURCE_AGENT, SOURCE_PROFILE
        from app.services.memory_service import (
            create_memory, find_similar_memory, update_memory,
        )

        content = (content or "").strip()
        if not content:
            return "未保存：内容为空"

        # [S2-3] memory_type → source 映射。未知值降级为 agent（偏好类）。
        source = SOURCE_PROFILE if memory_type == "profile" else SOURCE_AGENT

        # 工具是 agent loop 与主请求的事务边界：任何 DB 失败必须 rollback，
        # 否则 PG 事务进入 aborted 状态，毒化同一 session 的后续查询
        # （如对话 finally 里的 _log_llm_call 访问 current_user.id 触发 lazy load）。
        try:
            # 去重：查找高度相似的已有记忆
            similar = find_similar_memory(db, user_id=user_id, content=content)
            if similar is not None:
                # 合并：相似度 ≥ 阈值，更新已有记忆
                update_memory(db, memory_id=similar.id, user_id=user_id, content=content)
                db.commit()
                return f"已合并更新已有记忆（原：「{similar.content[:50]}...」）"

            create_memory(db, user_id=user_id, content=content, source=source)
            db.commit()
            return "已保存"
        except Exception:
            db.rollback()
            return "未保存：写入失败，请稍后重试"

    tools = [rag_search, save_memory]
    # 加载已启用的 MCP server 工具（逐 server try/except，失败跳过不阻塞 agent 构建）
    try:
        tools.extend(await load_mcp_tools(db))
    except Exception as e:
        db.rollback()
        logger.warning("MCP 工具整体加载失败，跳过: %s", e)
    return tools


async def load_mcp_tools(db: Any) -> list:
    """加载已启用的 MCP server 工具列表。

    - 全局开关关闭 / 无 server → 返回空列表。
    - 逐 server try/except：单个 server 连不上记日志、跳过，不阻塞其余 server。
    - tool_name_prefix=True：避免多 server 工具重名冲突。
    """
    from app.services.mcp_config_service import resolve_mcp_servers, _to_connection

    servers = resolve_mcp_servers(db)
    if not servers:
        return []
    tools: list = []
    for s in servers:
        try:
            conn = _to_connection(s)
            client = MultiServerMCPClient({s["name"]: conn}, tool_name_prefix=True)
            tools.extend(await client.get_tools())
        except Exception as e:
            logger.warning("MCP server %s 加载失败，跳过: %s", s["name"], e)
            continue
    return tools
