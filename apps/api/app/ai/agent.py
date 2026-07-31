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
- Task 8 create_agent_tools：作为 agent 的工具集合（rag_search + save_memory）注入，
  user_id 与 db 由闭包绑定，LLM 只需生成 query/content（修复旧 rag_search 参数注入缺陷）。
- get_llm：解析后的自定义/global/env 配置 → ChatOpenAI 实例。

注意：create_deep_agent / StoreBackend 必须在模块顶层 import，
测试用 monkeypatch.setattr(agent_mod, "create_deep_agent", ...) 装配断言时
替换的是模块属性。
"""
import logging

from langgraph.graph.state import CompiledStateGraph

from app.ai.context_assembler import SYSTEM_PROMPT
from app.ai.llm_client import get_llm
from app.ai.tools import create_agent_tools
from app.ai.tool_support import ToolSupportError, check_tool_support
from app.services.llm_config_service import ResolvedChatConfig
from app.skills.storage import MinIOSkillStore
from app.skills.visibility import build_agent_skill_sources

# 模块顶层 import：测试通过 monkeypatch agent_mod.create_deep_agent 替换装配。
from deepagents import create_deep_agent
from deepagents.backends import StoreBackend

logger = logging.getLogger("tiangong.ai")

__all__ = ["build_agent"]


async def build_agent(
    db, *, llm_config: ResolvedChatConfig, user_id,
    section=None, user_input: str | None = None, intent: str | None = None,
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
        section: 当前要撰写/对话的 Section。非 None 时调 build_system_prompt 装配
            动态 system prompt（含项目标题、已写章节、章节策略）。None 时用
            静态 SYSTEM_PROMPT 兜底（向后兼容，本 spec 范围内 chat/generate 都会传 section）。

    Returns:
        CompiledStateGraph：具备 ainvoke / astream_events。

    Raises:
        ToolSupportError: 模型不支持 tool calling（Q14-α fail-fast）。
    """
    # 1. 自定义配置降级检测——第一道闸，不支持立即拒绝
    check_tool_support(model=llm_config.model)
    logger.debug("build_agent: tool support ok for %s", llm_config.model)

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
    logger.debug("build_agent: skill_sources=%s", skill_sources)

    # 4. LLM + 工具
    llm = get_llm(llm_config, streaming=True)
    logger.info("build_agent: LLM 实例已构造，开始装配 system prompt + tools")

    # [L1][L4][前文直注入] section 非 None 时装配动态 system prompt（spec §3.2）
    # user_input 透传给记忆检索（用户当前输入是最强检索信号，spec §5.3 升级）
    # intent（S2-2）透传给意图行为指令注入（draft/edit/info/guide）
    if section is not None:
        from app.ai.context_assembler import _retrieve_knowledge_for_section, build_system_prompt
        # 预检索知识库：据章节上下文自动检索历史案例，失败静默降级
        knowledge_context = _retrieve_knowledge_for_section(
            db, user_id, section, user_input=user_input,
        )
        system_prompt = build_system_prompt(
            db, section, user_input=user_input, intent=intent,
            knowledge_context=knowledge_context,
        )
    else:
        system_prompt = SYSTEM_PROMPT  # 向后兼容兜底

    # 5. 组装 deepagents agent
    #
    # [Task 9 / 设计 §9 V1 限制] deepagents 0.6.12 的 create_deep_agent 会无条件自动
    # 注入一个 SummarizationMiddleware（库内置黑盒压缩，create_summarization_middleware）。
    # 该中间件没有 per-call 的 excluded_middleware / disable_default_middleware 形参
    # （create_deep_agent 的形参已核实：model/tools/system_prompt/middleware/subagents/
    # skills/memory/permissions/backend/interrupt_on/response_format/state_schema/context_schema/
    # checkpointer/store/debug/name/cache —— 无任何排除开关）。
    # 唯一的排除路径是 beta 全局注册表 register_harness_profile(key, HarnessProfile(
    # excluded_middleware={"SummarizationMiddleware"}))，但它是进程级全局状态 + beta API，
    # 且 profile 未匹配时只打 WARNING 不报错（静默失败风险），故 V1 不采用。
    #
    # 采纳的兜底策略（与天工 compress_history 并存）：
    # orchestrator 的 compress_history 已在 build_agent 之前把历史预压缩成更短版本，
    # 库 SummarizationMiddleware 看到的是已压缩的较短历史，其 ~170k token 阈值几乎不会
    # 再触发——相当于一个极少生效的后备保险，而非活跃的第二套压缩。
    # 唯一代价：库的黑盒行为作为后备保留，可观测性略差；对正确性无损害。
    # （路径 B 的 §9 V1 明确接受此并存。）
    agent_tools = await create_agent_tools(db, user_id)
    logger.info("build_agent: 调用 create_deep_agent（tools=%d skills=%d）",
                len(agent_tools),
                len(skill_sources) if skill_sources else 0)
    agent = create_deep_agent(
        model=llm,  # I1：不预绑定。deepagents 内部调 bind_tools，预绑定会让 RunnableBinding 无 bind_tools 方法。
        system_prompt=system_prompt,
        tools=agent_tools,
        skills=skill_sources if skill_sources else None,
        backend=backend,
        store=store,
    )
    logger.info("build_agent: agent 组装完成")
    return agent


# 静态导入友好：避免 ToolSupportError 未导出导致 from app.ai.agent import 时缺符号。
_ = ToolSupportError
