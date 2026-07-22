# apps/api/app/ai/agent.py
"""deepagents agent 工厂（spec 合规，路线 B 全量重写）。

把 LLM 配置 + 可见 skill + RAG 工具组装成 deepagents agent，
取代旧 orchestrator 的一次性 astream 流式调用（Q16-A 全量切 agent loop）。

集成点：
- Task 11 check_tool_support：第一道闸，不支持 tool calling 的模型立即拒绝（Q14-α），
  在任何 deepagents 构造前抛 ToolSupportError（fail-fast，避免晦涩的下游报错）。
- Task 7 MinIOSkillStore：作为 BaseStore 传入，StoreBackend 包装它供
  SkillsMiddleware/FilesystemMiddleware 持久化 skill 与文件。
- Task 9 build_agent_skill_sources：运行时计算可见 skill 前缀列表（global ∪ personal）。
- Task 10 rag_search_tool：作为 agent 的检索工具注入。
- get_llm：解析后的 BYOK/global/env 配置 → ChatOpenAI 实例。

注意：create_deep_agent / StoreBackend 必须在模块顶层 import，
测试用 monkeypatch.setattr(agent_mod, "create_deep_agent", ...) 装配断言时
替换的是模块属性。
"""
from langgraph.graph.state import CompiledStateGraph

from app.ai.context_assembler import SYSTEM_PROMPT
from app.ai.llm_client import get_llm
from app.ai.tools import rag_search_tool
from app.ai.tool_support import ToolSupportError, check_tool_support
from app.services.llm_config_service import ResolvedLLMConfig
from app.skills.storage import MinIOSkillStore
from app.skills.visibility import build_agent_skill_sources

# 模块顶层 import：测试通过 monkeypatch agent_mod.create_deep_agent 替换装配。
from deepagents import create_deep_agent
from deepagents.backends import StoreBackend

__all__ = ["build_agent"]


def build_agent(
    db, *, llm_config: ResolvedLLMConfig, user_id,
) -> CompiledStateGraph:
    """构造 deepagents agent（路线 B 的装配入口）。

    顺序（关键）：
    1. check_tool_support：BYOK 降级检测。不支持 tool calling 立即抛
       ToolSupportError（Q14-α，宁拒不降级），避免旧 orchestrator 那种
       晦涩的「调了一半才在 GLM 1214 报错」。
    2. MinIOSkillStore（BaseStore）+ StoreBackend 包装：供 SkillsMiddleware
       按 MinIO 前缀加载 skill 目录、FilesystemMiddleware 持久化文件。
    3. build_agent_skill_sources：运行时合并可见 skill 前缀
       （global 低优先，personal 高优先覆盖同名）。
    4. get_llm 取 ChatOpenAI，bind_tools 注入 RAG 工具。
       注：deepagents 内部会对传入的 model 再调一次 bind_tools，与这里的预绑定
       幂等叠加（fake model 返回自身；ChatOpenAI 产生 bound chain，均无害）。
    5. create_deep_agent 组装返回 CompiledStateGraph。

    Args:
        db: SQLAlchemy Session（供 build_agent_skill_sources 查可见 skill）。
        llm_config: 已解析的生效配置（base_url/api_key/model）。
        user_id: 当前用户 ID（限定 personal skill 可见范围 + RAG 检索范围）。

    Returns:
        CompiledStateGraph：具备 ainvoke / astream_events。

    Raises:
        ToolSupportError: 模型不支持 tool calling（Q14-α fail-fast）。
    """
    # 1. BYOK 降级检测——第一道闸，不支持立即拒绝
    check_tool_support(model=llm_config.model)

    # 2. MinIO BaseStore + StoreBackend
    store = MinIOSkillStore(bucket="global")
    backend = StoreBackend(store=store)

    # 3. 可见 skill sources（global ∪ personal）
    skill_sources = build_agent_skill_sources(db, user_id=user_id)

    # 4. LLM + 工具
    llm = get_llm(llm_config, streaming=True)
    llm_with_tools = llm.bind_tools([rag_search_tool])

    # 5. 组装 deepagents agent
    agent = create_deep_agent(
        model=llm_with_tools,
        system_prompt=SYSTEM_PROMPT,
        tools=[rag_search_tool],
        skills=skill_sources if skill_sources else None,
        backend=backend,
        store=store,
    )
    return agent


# 静态导入友好：避免 ToolSupportError 未导出导致 from app.ai.agent import 时缺符号。
_ = ToolSupportError
