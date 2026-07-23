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
- get_llm：解析后的自定义/global/env 配置 → ChatOpenAI 实例。

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
    1. check_tool_support：自定义配置降级检测。不支持 tool calling 立即抛
       ToolSupportError（Q14-α，宁拒不降级），避免旧 orchestrator 那种
       晦涩的「调了一半才在 GLM 1214 报错」。
    2. MinIOSkillStore（BaseStore）+ StoreBackend 包装：供 SkillsMiddleware
       按 MinIO 前缀加载 skill 目录、FilesystemMiddleware 持久化文件。
    3. build_agent_skill_sources：运行时合并可见 skill 前缀
       （global 低优先，personal 高优先覆盖同名）。
    4. get_llm 取 ChatOpenAI，直接传给 create_deep_agent(model=...)。
       **不在此处预绑定 bind_tools**：deepagents 内部会调 model.bind_tools(tools)，
       若在此处先 bind 一次，真实 ChatOpenAI 会返回 RunnableBinding（无 bind_tools 方法），
       导致 deepagents 内部二次 bind 抛 AttributeError（I1）。
    5. create_deep_agent 组装返回 CompiledStateGraph。

    单 bucket 设计（C1）：所有 skill（global + personal）统一存 MinIO "global" bucket，
    仅靠 minio_prefix 区分 scope（skills/global/... vs skills/personal/{owner}/...）。
    故 MinIOSkillStore(bucket="global") 对两种 scope 都正确。
    注意：Task 16 的 skill CRUD 服务里 _bucket_for_scope 必须恒返回 "global"，
    不得按 scope 拆分 bucket——否则 personal skill 运行时不可见（本 store 只读 global bucket）。

    Args:
        db: SQLAlchemy Session（供 build_agent_skill_sources 查可见 skill）。
        llm_config: 已解析的生效配置（base_url/api_key/model）。
        user_id: 当前用户 ID（限定 personal skill 可见范围 + RAG 检索范围）。

    Returns:
        CompiledStateGraph：具备 ainvoke / astream_events。

    Raises:
        ToolSupportError: 模型不支持 tool calling（Q14-α fail-fast）。
    """
    # 1. 自定义配置降级检测——第一道闸，不支持立即拒绝
    check_tool_support(model=llm_config.model)

    # 2. MinIO BaseStore + StoreBackend
    # C1：所有 skill（global + personal）统一存 "global" bucket，仅靠 minio_prefix 区分 scope。
    store = MinIOSkillStore(bucket="global")
    # Task 15 v1 决定（spec §12 已知限制）：backend 只用 StoreBackend（skill 存储），
    # 不自动注入 Docker sandbox backend。脚本执行通过 sandbox.docker_runner.execute_script
    # 独立 API 暴露（Task 14）。agent 自动执行脚本（CompositeBackend 组合 sandbox）留 v2。
    # 这样 build_agent 不依赖 Docker daemon——Docker 不可用时 agent 仍能加载 skill。
    # I2：显式 namespace，避免 StoreBackend 回退到 legacy assistant_id 检测（每次 ls 抛 DeprecationWarning，
    # 0.7.0 会 break）。namespace 必须非空（deepagents 的 _validate_namespace 拒绝空 tuple），
    # 且应覆盖所有 skill 的前缀根——所有 minio_prefix 都以 "skills/" 开头，故用 ("skills",)。
    # StoreBackend.ls() 先按 namespace 从 MinIO 搜索对象，再用 source_path（绝对路径，如
    # "skills/global/<name>/"）做前缀过滤——过滤用的是 item.key 全路径，故不会双重前缀。
    backend = StoreBackend(
        store=store,
        namespace=lambda ctx: ("skills",),
    )

    # 3. 可见 skill sources（global ∪ personal）
    skill_sources = build_agent_skill_sources(db, user_id=user_id)

    # 4. LLM + 工具
    llm = get_llm(llm_config, streaming=True)

    # 5. 组装 deepagents agent
    agent = create_deep_agent(
        model=llm,  # I1：不预绑定。deepagents 内部调 bind_tools，预绑定会让 RunnableBinding 无 bind_tools 方法。
        system_prompt=SYSTEM_PROMPT,
        tools=[rag_search_tool],
        skills=skill_sources if skill_sources else None,
        backend=backend,
        store=store,
    )
    return agent


# 静态导入友好：避免 ToolSupportError 未导出导致 from app.ai.agent import 时缺符号。
_ = ToolSupportError
