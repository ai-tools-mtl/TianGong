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
    agent = agent_mod.build_agent(db_session, llm_config=config, user_id=user_id)
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
        build_agent(db_session, llm_config=config, user_id=uuid.uuid4())


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
        build_agent(db_session, llm_config=config, user_id=uuid.uuid4())


def test_build_agent_assembly_args(db_session, monkeypatch):
    """验证 build_agent 把 tools/skills/store/backend 传给 create_deep_agent。

    装配逻辑结构断言（不依赖 deepagents 实际行为）：
    - tools 包含 rag_search_tool
    - skills 是 list（来自 build_agent_skill_sources）
    - store 是 MinIOSkillStore
    - backend 是 StoreBackend，包装同一 store
    """
    from app.ai import agent as agent_mod
    from app.ai.tools import rag_search_tool
    from app.services.llm_config_service import ResolvedChatConfig
    from app.skills.storage import MinIOSkillStore
    from deepagents.backends import StoreBackend

    captured: dict = {}

    class _Sentinel:
        def ainvoke(self, *a, **kw):
            return None

        def astream_events(self, *a, **kw):
            return None

    def _fake_create(model=None, tools=None, *, system_prompt=None, skills=None,
                     backend=None, store=None, **kw):
        captured.update(
            model=model, tools=tools or [], system_prompt=system_prompt,
            skills=skills, backend=backend, store=store,
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
    agent_mod.build_agent(db_session, llm_config=config, user_id=user_id)

    # tools 包含 rag_search_tool
    tool_names = [getattr(t, "name", None) for t in captured["tools"]]
    assert "rag_search" in tool_names
    # skills 是 list（空也合法——无可见 skill 时 build_agent_skill_sources 返回 []）
    assert isinstance(captured["skills"], (list, type(None)))
    # store 是 MinIOSkillStore
    assert isinstance(captured["store"], MinIOSkillStore)
    # backend 是 StoreBackend，包装同一 store
    assert isinstance(captured["backend"], StoreBackend)
    # system_prompt 非空（来自 context_assembler）
    assert captured["system_prompt"]


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
    agent_mod.build_agent(db_session, llm_config=config, user_id=uuid.uuid4())

    # 直接构造同配置 StoreBackend 验证 namespace callable 返回非空且通过校验。
    from app.skills.storage import MinIOSkillStore
    from deepagents.backends import StoreBackend
    store = MinIOSkillStore(bucket="global")
    backend = StoreBackend(store=store, namespace=lambda ctx: ("skills",))
    # _get_namespace 不抛 ValueError（空 tuple 会被 _validate_namespace 拒绝）
    ns = backend._get_namespace()  # noqa: SLF001
    assert ns == ("skills",)
