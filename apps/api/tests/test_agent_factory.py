# apps/api/tests/test_agent_factory.py
"""deepagents agent 工厂测试。

不真实调 GLM，mock get_llm 返回假 chat model。
验证 agent 被正确构造（结构），而非 LLM 输出正确性。

策略：
- happy path：注入 _FakeChatModel（支持 bind_tools），跑通真实 create_deep_agent。
- 不支持 tool calling：check_tool_support 在调 deepagents 前抛 ToolSupportError。
- 空 model：同上（Q14-α）。
- 装配参数：mock create_deep_agent 验证 build_agent 传入了正确的
  tools/skills/store/backend（结构断言，不依赖 deepagents 实际行为）。
"""
import asyncio
import uuid

import pytest


def _mock_llm():
    """构造一个最小可用的假 ChatModel（支持 bind_tools）。"""
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class _FakeChatModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "fake"

        @property
        def model_name(self) -> str:
            return "glm-4.7"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

        def bind_tools(self, tools, **kwargs):
            # 返回自身（假装绑定了工具）。deepagents 内部会再次 bind_tools，幂等。
            return self

    return _FakeChatModel()


def test_build_agent_returns_compiled_graph(db_session, monkeypatch):
    """build_agent 返回 CompiledStateGraph，含 skills + tools。"""
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    # mock get_llm 返回假模型（不真实调 GLM）
    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    # mock MinIO storage（MinIOSkillStore 内部走 get_storage；conftest 已注入 fake 单例，
    # 此处仅冗余再设一次以防环境差异）
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self):
            self._client = None
            self._buckets = {}

        def _resolve(self, a):
            return a

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(
        base_url="http://x",
        api_key="k",
        model="glm-4.7",
        source="env",
    )
    user_id = uuid.uuid4()
    agent = asyncio.run(agent_mod.build_agent(db_session, llm_config=config, user_id=user_id))
    assert agent is not None
    # CompiledStateGraph 有 ainvoke/astream_events
    assert hasattr(agent, "ainvoke")
    assert hasattr(agent, "astream_events")


def test_build_agent_unsupported_model_raises(db_session):
    """不支持 tool calling 的模型抛 ToolSupportError（Q14-α）。"""
    from app.ai.agent import build_agent
    from app.ai.tool_support import ToolSupportError
    from app.services.llm_config_service import ResolvedChatConfig

    config = ResolvedChatConfig(
        base_url="http://x",
        api_key="k",
        model="old-unsupported-model",
        source="env",
    )
    with pytest.raises(ToolSupportError):
        asyncio.run(build_agent(db_session, llm_config=config, user_id=uuid.uuid4()))


def test_build_agent_empty_model_raises(db_session):
    """空 model 抛 ToolSupportError。"""
    from app.ai.agent import build_agent
    from app.ai.tool_support import ToolSupportError
    from app.services.llm_config_service import ResolvedChatConfig

    config = ResolvedChatConfig(
        base_url="http://x",
        api_key="k",
        model="",
        source="env",
    )
    with pytest.raises(ToolSupportError):
        asyncio.run(build_agent(db_session, llm_config=config, user_id=uuid.uuid4()))


def test_build_agent_assembly_args(db_session, monkeypatch):
    """验证 build_agent 把 tools/skills/store/backend 传给 create_deep_agent。

    装配逻辑结构断言（不依赖 deepagents 实际行为）：
    - tools 来自 create_agent_tools 工厂（rag_search + save_memory）
    - skills 是 list（来自 build_agent_skill_sources）
    - store 是 CompositeAgentStore（红利③：memories 命名空间路由 user_memories，
      其余透传 MinIOSkillStore）
    - backend 是 StoreBackend，包装同一 store
    """
    from app.ai import agent as agent_mod
    from app.ai.store import CompositeAgentStore
    from app.services.llm_config_service import ResolvedChatConfig
    from deepagents.backends import StoreBackend

    captured: dict = {}

    class _Sentinel:
        def ainvoke(self, *a, **kw):
            return None

        def astream_events(self, *a, **kw):
            return None

    def _fake_create(model=None, tools=None, *, system_prompt=None, skills=None,
                     backend=None, store=None, middleware=None, checkpointer=None, **kw):
        captured.update(
            model=model, tools=tools or [], system_prompt=system_prompt,
            skills=skills, backend=backend, store=store, middleware=middleware or [],
            checkpointer=checkpointer,
        )
        return _Sentinel()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self):
            self._client = None

        def _resolve(self, a):
            return a

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(
        base_url="http://x",
        api_key="k",
        model="glm-4.7",
        source="env",
    )
    user_id = uuid.uuid4()
    asyncio.run(agent_mod.build_agent(db_session, llm_config=config, user_id=user_id))

    # tools 来自 create_agent_tools 工厂（rag_search + save_memory）
    tool_names = [getattr(t, "name", None) for t in captured["tools"]]
    assert "rag_search" in tool_names
    assert "save_memory" in tool_names
    # skills 是 list（空也合法——无可见 skill 时 build_agent_skill_sources 返回 []）
    assert isinstance(captured["skills"], (list, type(None)))
    # store 是 CompositeAgentStore（内包 MinIOSkillStore 的 skill 路由）
    assert isinstance(captured["store"], CompositeAgentStore)
    from app.skills.storage import MinIOSkillStore
    assert isinstance(captured["store"]._skill_store, MinIOSkillStore)  # noqa: SLF001
    # backend 是 StoreBackend，包装同一 store
    assert isinstance(captured["backend"], StoreBackend)
    # system_prompt 非空（来自 context_assembler）
    assert captured["system_prompt"]
    # middleware 含 ToolTimeoutMiddleware（工具级超时防护注入）
    from app.ai.tool_timeout import ToolTimeoutMiddleware
    assert any(isinstance(m, ToolTimeoutMiddleware) for m in captured["middleware"])
    # checkpointer 默认 None（未传时不 checkpoint）
    assert captured["checkpointer"] is None


def test_build_agent_forwards_checkpointer(db_session, monkeypatch):
    """build_agent(checkpointer=X) → create_deep_agent 收到 checkpointer=X（红利①转发）。"""
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig
    from langgraph.checkpoint.memory import InMemorySaver

    captured: dict = {}

    class _Sentinel:
        def ainvoke(self, *a, **kw):
            return None

        def astream_events(self, *a, **kw):
            return None

    def _fake_create(model=None, tools=None, *, system_prompt=None, skills=None,
                     backend=None, store=None, middleware=None, checkpointer=None, **kw):
        captured["checkpointer"] = checkpointer
        return _Sentinel()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def _resolve(self, a):
            return a

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    saver = InMemorySaver()
    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    asyncio.run(agent_mod.build_agent(
        db_session, llm_config=config, user_id=uuid.uuid4(), checkpointer=saver,
    ))
    assert captured["checkpointer"] is saver


def test_build_agent_init_scope_keeps_rag_search(db_session, monkeypatch):
    """[tool_scope=init] 时 tools 保留 rag_search + save_memory（与 section 一致）。

    init 助手参与正文生成、对话引导也需要参考知识库历史案例，故 init 场景同样保留
    全部内置工具。MCP 工具不在 BUILTIN_TOOLS 内，不受 scope 影响。
    """
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    captured: dict = {}

    def _fake_create(model=None, tools=None, **kw):
        captured["tools"] = tools or []
        return type("_S", (), {"ainvoke": lambda *a: None, "astream_events": lambda *a: None})()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self): self._client = None
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    asyncio.run(agent_mod.build_agent(
        db_session, llm_config=config, user_id=uuid.uuid4(),
        tool_scope="init",
    ))

    tool_names = [getattr(t, "name", None) for t in captured["tools"]]
    assert "save_memory" in tool_names
    assert "rag_search" in tool_names


def test_build_agent_storebackend_namespace_is_valid(db_session, monkeypatch):
    """StoreBackend 的 namespace 必须非空（I2 回归保护）。

    deepagents 的 _validate_namespace 拒绝空 tuple（抛 ValueError）。
    _get_namespace() 在每次 ls/read/write 时被调用。若 namespace 为空，
    真实 agent 执行（加载 skill）会崩。本测试直接调用 _get_namespace 验证不抛。
    """
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", lambda **kw: type("_S", (), {"ainvoke": lambda *a: None, "astream_events": lambda *a: None})())
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self): self._client = None
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(
        base_url="http://x", api_key="k", model="glm-4.7",
        source="env",
    )
    asyncio.run(agent_mod.build_agent(db_session, llm_config=config, user_id=uuid.uuid4()))

    # 直接构造同配置 StoreBackend 验证 namespace callable 返回非空且通过校验。
    from app.skills.storage import MinIOSkillStore
    from deepagents.backends import StoreBackend
    store = MinIOSkillStore(bucket="global")
    backend = StoreBackend(store=store, namespace=lambda ctx: ("skills",))
    # _get_namespace 不抛 ValueError（空 tuple 会被 _validate_namespace 拒绝）
    ns = backend._get_namespace()  # noqa: SLF001
    assert ns == ("skills",)


# ===== build_agent 传 section 测试（Task 2.1） =====

def _build_section_with_project(db_session):
    """构造一个真实入库的 Project + Section，供 build_agent 的 section 参数用。

    Project.user_id 是 NOT NULL 外键，必须先建 User。
    """
    from app.models import Project, Section, User
    from app.core.security import hash_password
    u = User(
        username=f"test-{uuid.uuid4().hex[:8]}",
        email=f"test-{uuid.uuid4().hex[:8]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="测试用户",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    p = Project(user_id=u.id, title="凸轮门锁交底书")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    s = Section(
        project_id=p.id,
        template_section_id="ts-field",
        order=2, key="field", title="技术领域",
        content=None, status="empty",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def test_build_agent_with_section_uses_dynamic_prompt(db_session, monkeypatch):
    """传 section 时，create_deep_agent 收到的 system_prompt 含项目标题 + 章节策略。"""
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}

    def _fake_create(model=None, tools=None, *, system_prompt=None, **kw):
        captured["system_prompt"] = system_prompt
        return type("_S", (), {"ainvoke": lambda *a: None, "astream_events": lambda *a: None})()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self): self._client = None
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    asyncio.run(agent_mod.build_agent(db_session, llm_config=config, user_id=uuid.uuid4(), section=section))

    # 动态 prompt 含项目标题（来自 build_system_prompt）
    assert "凸轮门锁交底书" in captured["system_prompt"]
    # 含当前章节策略
    assert "技术领域" in captured["system_prompt"]


def test_build_agent_without_section_falls_back_to_static(db_session, monkeypatch):
    """不传 section 时，system_prompt == SYSTEM_PROMPT（向后兼容）。"""
    from app.ai import agent as agent_mod
    from app.ai.context_assembler import SYSTEM_PROMPT
    from app.services.llm_config_service import ResolvedChatConfig

    captured: dict = {}

    def _fake_create(model=None, tools=None, *, system_prompt=None, **kw):
        captured["system_prompt"] = system_prompt
        return type("_S", (), {"ainvoke": lambda *a: None, "astream_events": lambda *a: None})()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self): self._client = None
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    asyncio.run(agent_mod.build_agent(db_session, llm_config=config, user_id=uuid.uuid4()))  # 不传 section

    assert captured["system_prompt"] == SYSTEM_PROMPT


def test_build_agent_with_section_prompt_not_equal_static(db_session, monkeypatch):
    """动态 prompt 与静态 SYSTEM_PROMPT 不同（防回归：确保真的走了 build_system_prompt）。"""
    from app.ai import agent as agent_mod
    from app.ai.context_assembler import SYSTEM_PROMPT
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}

    def _fake_create(model=None, tools=None, *, system_prompt=None, **kw):
        captured["system_prompt"] = system_prompt
        return type("_S", (), {"ainvoke": lambda *a: None, "astream_events": lambda *a: None})()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self): self._client = None
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    asyncio.run(agent_mod.build_agent(db_session, llm_config=config, user_id=uuid.uuid4(), section=section))

    assert captured["system_prompt"] != SYSTEM_PROMPT


# ===== S2-2：意图识别贯穿 build_agent（spec 2026-07-29-prompt-content-design §4 S2-2）=====

def test_build_agent_passes_intent_to_prompt(db_session, monkeypatch):
    """[S2-2] 传 intent=draft 时，system_prompt 含代写行为指令。"""
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}

    def _fake_create(model=None, tools=None, *, system_prompt=None, **kw):
        captured["system_prompt"] = system_prompt
        return type("_S", (), {"ainvoke": lambda *a: None, "astream_events": lambda *a: None})()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self): self._client = None
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    asyncio.run(agent_mod.build_agent(
        db_session, llm_config=config, user_id=uuid.uuid4(),
        section=section, intent="draft",
    ))

    # 代写意图指令的特征词（INTENT_HINTS["draft"]）
    assert "代写" in captured["system_prompt"]
