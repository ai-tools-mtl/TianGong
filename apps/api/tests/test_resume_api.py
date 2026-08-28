# apps/api/tests/test_resume_api.py
"""resume 端点测试（Checkpoint 红利：断点恢复 + HITL 决策恢复）。

策略：monkeypatch app.api.ai.build_resume_agent 返回 fake agent
（支持 aget_state / astream_events），不真实装配 agent、不真实调 LLM。
"""
import json
from types import SimpleNamespace
from uuid import UUID

from langchain_core.messages import AIMessage

from app.models import Conversation, Message, Project, Section, User, UserLLMConfig
from app.services.seed_service import ensure_default_template


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })


def _make_fixture(db_session, registered_user, *, meta):
    """登录 + 配 LLM + 建 Project/Section/Conversation + 一轮 user/assistant 消息。

    assistant 消息带传入的 meta（incomplete 或 interrupted），返回 (section, conv, user_msg, ai_msg)。
    """
    from app.core.security import encrypt_value, hash_password
    from sqlalchemy import select

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    db_session.add(UserLLMConfig(
        user_id=user.id, name="test", provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model",
    ))
    project = Project(user_id=user.id, title="resume 测试项目")
    db_session.add(project)
    db_session.flush()
    section = Section(
        project_id=project.id, template_section_id="ts-solution",
        order=5, key="solution", title="技术方案", content=None, status="empty",
    )
    db_session.add(section)
    db_session.flush()
    conv = Conversation(section_id=section.id, title="新对话",
                        status="active")  # active：跳过完成后的 LLM 标题总结（测试不真调 LLM）
    db_session.add(conv)
    db_session.flush()
    user_msg = Message(section_id=section.id, conversation_id=conv.id,
                       role="user", content="帮我画个系统框图")
    db_session.add(user_msg)
    db_session.flush()
    ai_msg = Message(section_id=section.id, conversation_id=conv.id, role="assistant",
                     content="生成到一半的", meta=meta)
    db_session.add(ai_msg)
    db_session.commit()
    return section, conv, user_msg, ai_msg


def _make_agent(events=(), next_=("model",), tasks=(), values=None):
    class _FakeAgent:
        def __init__(self):
            self.captured_input = "UNSET"

        async def aget_state(self, config):
            return SimpleNamespace(values=values, next=next_, tasks=tasks)

        async def astream_events(self, input_, *, version="v2", config=None):
            self.captured_input = input_
            for e in events:
                yield e

    return _FakeAgent()


def _token(text):
    return {"event": "on_chat_model_stream",
            "data": {"chunk": SimpleNamespace(content=text, usage_metadata=None)}}



def _patch_agent(monkeypatch, agent):
    async def _fake_build(db, section, *, llm_config, user_input=None):
        return agent
    monkeypatch.setattr("app.api.ai.build_resume_agent", _fake_build)
    return agent


def test_resume_crash_appends_and_rebuilds_content(client, registered_user, db_session, monkeypatch):
    """崩溃续跑：SSE token/done 正常，完成时以 checkpoint 权威重建全文并清 incomplete。"""
    section, conv, user_msg, ai_msg = _make_fixture(
        db_session, registered_user, meta={"incomplete": True})
    _login(client, registered_user)

    agent = _patch_agent(monkeypatch, _make_agent(
        events=[_token("续跑段落")],
        values={"messages": [AIMessage("生成到一半的"), AIMessage("续跑段落")]},
    ))
    res = client.post(
        f"/api/v1/sections/{section.id}/messages/{ai_msg.id}/resume",
        json={"thread_id": str(user_msg.id)})
    assert res.status_code == 200
    body = res.text
    assert "event: token" in body and "续跑段落" in body
    assert "event: done" in body
    assert agent.captured_input is None  # 崩溃续跑 → input=None

    db_session.expire_all()
    updated = db_session.get(Message, ai_msg.id)
    assert updated.content == "生成到一半的续跑段落"  # 权威重建（state 拼接）
    assert not (updated.meta or {}).get("incomplete")
    assert not (updated.meta or {}).get("interrupted")


def test_resume_rejects_without_pending_checkpoint(client, registered_user, db_session, monkeypatch):
    """checkpoint 无未完任务（state.next 空）→ 409 引导重发。"""
    section, conv, user_msg, ai_msg = _make_fixture(
        db_session, registered_user, meta={"incomplete": True})
    _login(client, registered_user)
    _patch_agent(monkeypatch, _make_agent(next_=()))

    res = client.post(
        f"/api/v1/sections/{section.id}/messages/{ai_msg.id}/resume",
        json={"thread_id": str(user_msg.id)})
    assert res.status_code == 409


def test_resume_pending_interrupt_requires_decision(client, registered_user, db_session, monkeypatch):
    """HITL 断点等确认但不带 decision → 422。"""
    section, conv, user_msg, ai_msg = _make_fixture(
        db_session, registered_user,
        meta={"interrupted": True, "pending_interrupt": [{"name": "generate_figure"}]})
    _login(client, registered_user)
    task_with_interrupt = SimpleNamespace(interrupts=(SimpleNamespace(value={}),))
    _patch_agent(monkeypatch, _make_agent(tasks=(task_with_interrupt,)))

    res = client.post(
        f"/api/v1/sections/{section.id}/messages/{ai_msg.id}/resume",
        json={"thread_id": str(user_msg.id)})
    assert res.status_code == 422


def test_resume_approve_decision_sends_command(client, registered_user, db_session, monkeypatch):
    """HITL approve → astream_resume 收到 Command(resume={"decisions": [approve]})。"""
    from langgraph.types import Command

    section, conv, user_msg, ai_msg = _make_fixture(
        db_session, registered_user,
        meta={"interrupted": True, "pending_interrupt": [{"name": "generate_figure"}]})
    _login(client, registered_user)
    task_with_interrupt = SimpleNamespace(interrupts=(SimpleNamespace(value={}),))
    agent = _patch_agent(monkeypatch, _make_agent(
        events=[_token("好，开始生成")],
        tasks=(task_with_interrupt,),
        values={"messages": [AIMessage("好，开始生成")]},
    ))

    res = client.post(
        f"/api/v1/sections/{section.id}/messages/{ai_msg.id}/resume",
        json={"thread_id": str(user_msg.id), "decision": "approve"})
    assert res.status_code == 200
    assert isinstance(agent.captured_input, Command)
    assert agent.captured_input.resume == {"decisions": [{"type": "approve"}]}


def test_resume_by_thread_anchor_id(client, registered_user, db_session, monkeypatch):
    """message_id 传 user 消息 id（start 锚点语义，断线自动接续路径）→
    反查该会话最新 assistant 消息续跑成功（修复：此前必 404）。"""
    section, conv, user_msg, ai_msg = _make_fixture(
        db_session, registered_user, meta={"incomplete": True})
    _login(client, registered_user)
    agent = _patch_agent(monkeypatch, _make_agent(
        events=[_token("自动接续段落")],
        values={"messages": [AIMessage("生成到一半的"), AIMessage("自动接续段落")]},
    ))

    res = client.post(
        f"/api/v1/sections/{section.id}/messages/{user_msg.id}/resume",
        json={"thread_id": str(user_msg.id)})
    assert res.status_code == 200
    assert "自动接续段落" in res.text
    assert "event: done" in res.text

    db_session.expire_all()
    updated = db_session.get(Message, ai_msg.id)
    assert "自动接续段落" in updated.content


def test_resume_by_thread_anchor_without_assistant_404(client, registered_user, db_session):
    """user 消息 id 路径但会话内无任何 assistant 消息 → 404。"""
    section, conv, user_msg, ai_msg = _make_fixture(
        db_session, registered_user, meta={"incomplete": True})
    _login(client, registered_user)
    # 换一个只有 user 消息的会话模拟「断连兜底尚未落库/无内容可落」
    from app.models import Conversation as _Conv
    bare_conv = _Conv(section_id=section.id, title="只有 user 的会话", status="active")
    db_session.add(bare_conv)
    db_session.flush()
    bare_user_msg = Message(section_id=section.id, conversation_id=bare_conv.id,
                            role="user", content="刚发出就断")
    db_session.add(bare_user_msg)
    db_session.commit()

    res = client.post(
        f"/api/v1/sections/{section.id}/messages/{bare_user_msg.id}/resume",
        json={"thread_id": str(bare_user_msg.id)})
    assert res.status_code == 404


def test_resume_rejects_completed_message(client, registered_user, db_session):
    """非 incomplete/interrupted 消息 → 409。"""
    section, conv, user_msg, ai_msg = _make_fixture(db_session, registered_user, meta=None)
    _login(client, registered_user)
    res = client.post(
        f"/api/v1/sections/{section.id}/messages/{ai_msg.id}/resume",
        json={"thread_id": str(user_msg.id)})
    assert res.status_code == 409


def test_resume_other_user_section_404(client, registered_user, db_session):
    """非本人 section → 404（资源级授权）。"""
    section, conv, user_msg, ai_msg = _make_fixture(
        db_session, registered_user, meta={"incomplete": True})
    _login(client, registered_user)
    res = client.post(
        f"/api/v1/sections/{UUID(int=0)}/messages/{ai_msg.id}/resume",
        json={"thread_id": str(user_msg.id)})
    assert res.status_code == 404


def test_resume_thread_cross_conversation_rejected(client, registered_user, db_session):
    """thread 的 user 消息与 assistant 消息不同会话 → 404（防跨会话拼续）。"""
    section, conv, user_msg, ai_msg = _make_fixture(
        db_session, registered_user, meta={"incomplete": True})
    _login(client, registered_user)
    other_conv = Conversation(section_id=section.id, title="另一个会话")
    db_session.add(other_conv)
    db_session.flush()
    other_user_msg = Message(section_id=section.id, conversation_id=other_conv.id,
                             role="user", content="别的会话的问题")
    db_session.add(other_user_msg)
    db_session.commit()

    res = client.post(
        f"/api/v1/sections/{section.id}/messages/{ai_msg.id}/resume",
        json={"thread_id": str(other_user_msg.id)})
    assert res.status_code == 404
