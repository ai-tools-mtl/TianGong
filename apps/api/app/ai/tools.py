# apps/api/app/ai/tools.py
"""agent 工具：rag_search / save_memory 等 @tool。

工具通过工厂函数 create_agent_tools(db, user_id) 装配，
user_id 与 db 由闭包绑定——LLM 无需（也无法）生成这些参数。

修复旧设计缺陷：旧 rag_search_tool(query, user_id, db_session) 让 LLM
生成 user_id/db_session，但 LLM 根本不知道这些值。闭包工厂在 build_agent
时用已知 user_id + db 绑定，LLM 只需生成 query/content。
"""
import asyncio
import logging
import uuid as _uuid
from typing import Any

from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.rag.nli import judge_relation

logger = logging.getLogger(__name__)


# ── 工具可见性白名单（按 agent 场景）──
# init: 项目初始化对话，rag_search + save_memory 全保留——用户聊想法时参考
#       历史案例/已有交底书完全合理（知识库的核心价值之一），且 init 助手也参与
#       后续正文生成，检索能力不应缺失。（曾一度以「项目未建立、拖慢首屏」为由砍掉，
#       后纠正：见 commit 021300f → 后续 revert）
# section: 章节撰写/对话，全部内置工具可见（默认）
#
# 仅 BUILTIN_TOOLS 内的工具受白名单控制；MCP 工具（外部插件，按 server 启用）
# 不受 scope 限制——启用即生效，与 agent 场景无关。
BUILTIN_TOOLS: frozenset[str] = frozenset({"rag_search", "save_memory", "generate_figure"})
TOOL_WHITELIST: dict[str, frozenset[str] | None] = {
    # init 阶段项目章节刚建/未成型，画图价值低；figure 仅 section 场景可见
    "init": frozenset({"rag_search", "save_memory"}),
    "section": None,  # None = 不过滤，全部内置工具可见
}


async def create_agent_tools(db: Any, user_id, *, scope: str = "section", section: Any = None):
    """构造绑定到当前用户的 agent 工具集合。

    Args:
        db: SQLAlchemy Session（由 build_agent 传入，agent 生命周期内有效）。
        user_id: 当前用户 ID（限定检索/写入范围到本人）。
        scope: agent 场景，控制内置工具白名单。"init" / "section"（默认）。
            generate_figure 仅 section 场景可见（init 阶段项目未成型，画图价值低）。
            MCP 工具不受 scope 限制。未知 scope 宽放（不过滤）。
        section: 当前 Section（章节 agent 场景传入）。generate_figure 工具据此
            定位当前 project 的 drawings 章节；None 时该工具不装配（init 场景）。

    Returns:
        工具列表（含按 scope 过滤后的内置工具 + 全部 MCP 工具）——
        供 create_deep_agent(tools=...) 使用。
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
            create_memory, delete_memory, find_similar_memory, update_memory,
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
                # 【v1.1】矛盾判别：NLI 判断新旧是否冲突
                relation = judge_relation(content, similar.content)
                if relation == "contradiction":
                    # 矛盾：用户认知更新，新覆盖旧（全自动纠错）
                    delete_memory(db, memory_id=similar.id, user_id=user_id)
                    create_memory(db, user_id=user_id, content=content, source=source)
                    db.commit()
                    return "已更新（检测到与旧记忆冲突，已替换）"
                # entailment / neutral / 服务降级：走原合并逻辑
                update_memory(db, memory_id=similar.id, user_id=user_id, content=content)
                db.commit()
                return f"已合并更新已有记忆（原：「{similar.content[:50]}...」）"

            create_memory(db, user_id=user_id, content=content, source=source)
            db.commit()
            return "已保存"
        except Exception:
            db.rollback()
            return "未保存：写入失败，请稍后重试"

    @tool("generate_figure")
    def generate_figure(prompt: str, diagram_type: str = "general") -> str:
        """为专利交底书生成一张附图（流程图/架构图/框图等），自动存入「附图说明」章节。

        何时调用：
        - 用户明确要求画图：「画一下这个发明的系统框图」「帮我生成一张流程图」
        - 撰写过程中需要配图说明结构：「这里配一张架构图更清楚」

        何时不要调用：
        - 用户只要文字说明、没要图
        - 纯文字修改/重写（用普通对话即可）

        Args:
            prompt: 要画的图的内容描述，如「一种基于大模型的专利撰写流程：客户端→API网关→Agent→数据库」。
                尽量具体列出关键部件和它们之间的关系。
            diagram_type: 图类型。flowchart（流程图）/ architecture（系统架构图）/
                sequence（时序图）/ block（模块框图）/ state（状态图）/ general（通用，默认）。

        Returns:
            操作结果（已生成并附图说明/生成失败原因）。生成的图会出现在
            「附图说明」章节，用户可在那里预览并插入正文。
        """
        from app.core.storage import get_storage
        from app.services import figure_service, section_service

        # section 由闭包绑定（章节 agent 场景）；无 section（init）时工具不应被装配，
        # 但防御性兜底：返回提示而非崩溃
        if section is None:
            return "未生成：当前会话无章节上下文，无法确定附图归属项目"

        try:
            # 从当前 section 取 project，再查该 project 的 drawings 章节——
            # 无论 agent 当前在哪个章节对话，图都归到 drawings（与产品定位一致）
            sections = section_service.list_sections(db, user_id=user_id, project_id=str(section.project_id))
            drawings = next((s for s in sections if s.key == "drawings"), None)
            if drawings is None:
                return "未生成：当前项目无「附图说明」章节"

            fig = figure_service.generate_figure(
                db, storage=get_storage(), user_id=user_id,
                section_id=str(drawings.id),
                prompt=prompt, diagram_type=diagram_type, chat_source=None,
            )
            return f"已生成附图（id={fig.id}），已存入「附图说明」章节，用户可预览后插入正文"
        except Exception as e:
            # 工具是事务边界：DB/渲染失败必须 rollback，避免毒化 agent loop 后续查询
            db.rollback()
            msg = str(e)[:120]
            return f"未生成：{msg}（可稍后重试）"

    builtin = [rag_search, save_memory]
    # generate_figure 仅在有 section 上下文时装配（init 场景 section=None 跳过）
    if section is not None:
        builtin.append(generate_figure)
    tools = list(builtin)
    # 加载已启用的 MCP server 工具（逐 server try/except，失败跳过不阻塞 agent 构建）
    try:
        tools.extend(await load_mcp_tools(db))
    except Exception as e:
        logger.warning("MCP 工具整体加载失败，跳过: %s", e)

    # 按 scope 过滤内置工具（MCP 工具放行：不在 BUILTIN_TOOLS 内的不受影响）
    allowed = TOOL_WHITELIST.get(scope)
    if allowed is not None:
        tools = [t for t in tools if t.name not in BUILTIN_TOOLS or t.name in allowed]
    elif scope not in TOOL_WHITELIST:
        logger.debug("create_agent_tools: 未知 scope=%s，宽放（不过滤）", scope)
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
            # 工具发现阶段超时（层 2）：单个 server 拉工具列表最多等 15s，
            # 慢/挂的 server 不阻塞 agent 构建（与层 1 工具执行超时正交）
            server_tools = await asyncio.wait_for(client.get_tools(), timeout=15.0)
            tools.extend(server_tools)
        except asyncio.TimeoutError:
            logger.warning("MCP server %s 工具发现超时（15s），跳过", s["name"])
            continue
        except Exception as e:
            logger.warning("MCP server %s 加载失败，跳过: %s", s["name"], e)
            continue
    return tools
