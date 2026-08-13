# apps/api/tests/test_orchestrator.py
"""astream_generate / astream_chat 透传 section + history 测试（跨章节上下文 L1+L2）。

策略：mock build_agent 返回 fake agent，用 captured 捕获 build_agent 收到的参数
和 agent.astream_events 收到的 messages。不真实调 LLM、不真实建 agent。
参考 test_llm_config_e2e.py 的 _fake_agent_factory 模式。

项目无 async 测试先例，故用 asyncio.run() 在同步测试里消费 async generator，
避免引入 @pytest.mark.asyncio 新模式（保持测试风格统一）。
"""
import asyncio
import uuid


def _build_section_with_project(db_session):
    """构造真实入库的 Project + Section（user_id NOT NULL，先建 User）。"""
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
    p = Project(user_id=u.id, title="透传测试项目")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    s = Section(
        project_id=p.id,
        template_section_id="ts-solution",
        order=5, key="solution", title="技术方案",
        content=None, status="empty",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def _make_fake_build_agent(captured: dict):
    """返回一个 fake build_agent：捕获调用参数，返回假 agent。

    假 agent 的 astream_events 捕获收到的 messages，然后立即结束（空 async generator）。
    """

    class _FakeAgent:
        async def astream_events(self, input_, *, version="v2", config=None):
            captured["astream_input"] = input_
            captured["config"] = config
            return
            yield  # 让它成为 async generator（永远不会执行到这）

    async def _build_agent(db, *, llm_config, user_id, section=None, **kw):
        captured["build_args"] = {"section": section, "user_id": user_id, "llm_config": llm_config}
        return _FakeAgent()

    return _build_agent


def _consume(async_gen):
    """同步消费一个 async generator 到空（触发内部 capture）。"""
    async def _drain():
        async for _ in async_gen:
            pass
    asyncio.run(_drain())


def test_astream_chat_passes_thread_id_to_config(db_session, monkeypatch):
    """thread_id 透传到 agent.astream_events 的 config（红利①）。"""
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}
    monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    _consume(orch_mod.astream_chat(db_session, section, [], "hi", llm_config=config, thread_id="T1"))

    assert captured["config"] == {"configurable": {"thread_id": "T1"}}


def test_astream_generate_without_thread_id_config_none(db_session, monkeypatch):
    """generate 默认不传 thread_id → config=None（MVP 不 checkpoint generate）。"""
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}
    monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    _consume(orch_mod.astream_generate(db_session, section, [], llm_config=config))

    assert captured["config"] is None


def test_astream_generate_passes_section_to_build_agent(db_session, monkeypatch):
    """[L1] build_agent 收到 section 参数。"""
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}
    monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    _consume(orch_mod.astream_generate(db_session, section, [], llm_config=config))

    assert captured["build_args"]["section"] is section  # 同一对象


def test_astream_generate_passes_history_to_agent_messages(db_session, monkeypatch):
    """[L2] agent.astream_events 收到 history + instruction。"""
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.models import Message
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    history = [
        Message(section_id=section.id, role="user", content="前面问的"),
        Message(section_id=section.id, role="assistant", content="前面答的"),
    ]
    captured: dict = {}
    monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    _consume(orch_mod.astream_generate(db_session, section, history, llm_config=config))

    messages = captured["astream_input"]["messages"]
    # history 2 条 + instruction 1 条 = 3 条
    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "前面问的"}
    assert messages[1] == {"role": "assistant", "content": "前面答的"}
    assert "技术方案" in messages[2]["content"]  # instruction 含章节标题


def test_astream_generate_empty_history_only_instruction(db_session, monkeypatch):
    """[L2] history 为空时 messages 只有 instruction。"""
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}
    monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    _consume(orch_mod.astream_generate(db_session, section, [], llm_config=config))

    messages = captured["astream_input"]["messages"]
    assert len(messages) == 1  # 只有 instruction


# ===== astream_chat 测试（Task 3.2） =====

def test_astream_chat_passes_section_to_build_agent(db_session, monkeypatch):
    """[L1] chat 路径：build_agent 收到 section 参数。"""
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}
    monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    _consume(orch_mod.astream_chat(db_session, section, [], "用户问题", llm_config=config))

    assert captured["build_args"]["section"] is section


def test_astream_chat_passes_history_and_user_input(db_session, monkeypatch):
    """[L2] chat 透传 history + user_input。"""
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.models import Message
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    history = [
        Message(section_id=section.id, role="user", content="历史问"),
        Message(section_id=section.id, role="assistant", content="历史答"),
    ]
    captured: dict = {}
    monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    _consume(orch_mod.astream_chat(db_session, section, history, "当前问题", llm_config=config))

    messages = captured["astream_input"]["messages"]
    # history 2 条 + user_input 1 条 = 3 条
    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "历史问"}
    assert messages[1] == {"role": "assistant", "content": "历史答"}
    assert messages[2] == {"role": "user", "content": "当前问题"}
