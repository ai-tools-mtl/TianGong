def _make_logged_in_section(client, registered_user, db_session):
    """登录 + 建项目 + 返回第一个 section 对象（含真实 id）。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from app.models import User
    from sqlalchemy import select

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    p = create_project(db_session, user=user, title="测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    return sections[0]


def test_astream_functions_exist():
    """三个异步编排函数存在且是 async generator function。"""
    import inspect
    from app.ai.orchestrator import astream_chat, astream_generate, astream_rewrite

    for fn in (astream_chat, astream_generate, astream_rewrite):
        assert inspect.isasyncgenfunction(fn), f"{fn.__name__} 应为 async generator function"


def test_sync_functions_still_exist():
    """同步编排函数保留（审查引擎等仍用）。"""
    from app.ai.orchestrator import stream_chat, stream_generate, stream_rewrite
    for fn in (stream_chat, stream_generate, stream_rewrite):
        assert callable(fn)


def test_chat_endpoint_emits_done_event_with_heartbeat_support(client, registered_user, db_session, monkeypatch):
    """SSE chat 端点：mock LLM，验证 token/done 事件格式 + 异步 generate。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    # mock astream_chat 返回固定 token
    async def fake_astream_chat(db, section, history, msg, **kwargs):
        yield "hello"

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    body = res.text
    assert "event: token" in body
    assert "event: done" in body
    assert "hello" in body


def test_generate_saves_draft_on_completion(client, registered_user, db_session, monkeypatch):
    """generate 端点正常完成时把 markdown 转为 tiptap 存入 section.content。"""
    section = _make_logged_in_section(client, registered_user, db_session)
    assert section.content is None  # 初始为空

    async def fake_astream_generate(db, sec, history, **kwargs):
        yield "# 标题"

    monkeypatch.setattr("app.api.ai.astream_generate", fake_astream_generate)

    res = client.post(f"/api/v1/sections/{section.id}/generate")
    assert res.status_code == 200
    assert "event: done" in res.text

    # 验证草稿已存
    db_session.expire_all()
    from app.models import Section
    s = db_session.get(Section, section.id)
    assert s.content is not None
    assert s.status == "drafting"


def test_heartbeat_does_not_kill_slow_stream(client, registered_user, db_session, monkeypatch):
    """心跳不能杀死慢速 LLM 流：第一个 token 后 sleep > 心跳间隔，第二个 token 仍应到达。

    这是 wait_for bug 的回归测试：wait_for 超时会取消 __anext__()，
    永久关闭生成器，导致心跳后的 token 全部丢失。
    """
    import asyncio

    import app.api.ai as ai_module

    section = _make_logged_in_section(client, registered_user, db_session)

    # 把心跳间隔改小，让测试跑得快
    monkeypatch.setattr(ai_module, "HEARTBEAT_INTERVAL", 0.3)

    async def slow_astream_chat(db, sec, history, msg, **kwargs):
        yield "first"
        await asyncio.sleep(0.6)  # > 心跳间隔，触发心跳
        yield "second"  # 心跳后这个 token 必须仍能到达（原 bug 会丢失）

    monkeypatch.setattr("app.api.ai.astream_chat", slow_astream_chat)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    body = res.text
    assert "event: heartbeat" in body  # 心跳确实发了
    assert "first" in body
    assert "second" in body  # 关键：心跳后的 token 仍到达（原 bug 会丢失）


# ── LLM 调用日志（plan 13）──

def test_chat_writes_llm_call_log_on_success(client, registered_user, db_session, monkeypatch):
    """chat 端点成功完成时写一条 LLMCallLog（status=success）。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_chat(db, sec, history, msg, **kwargs):
        yield "hello"

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert "event: done" in res.text

    from app.models import LLMCallLog
    from sqlalchemy import select
    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "chat")))
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "success"
    assert log.action == "chat"
    assert log.user_id is not None
    assert log.project_id == section.project_id
    assert log.duration_ms is not None and log.duration_ms >= 0
    assert log.error is None
    # 红线：绝不存 prompt/completion 内容
    assert not hasattr(log, "prompt")
    assert not hasattr(log, "completion")


def test_generate_writes_llm_call_log_on_success(client, registered_user, db_session, monkeypatch):
    """generate 端点成功完成时写一条 LLMCallLog。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_generate(db, sec, history, **kwargs):
        yield "# 标题"

    monkeypatch.setattr("app.api.ai.astream_generate", fake_astream_generate)

    res = client.post(f"/api/v1/sections/{section.id}/generate")
    assert res.status_code == 200
    assert "event: done" in res.text

    from app.models import LLMCallLog
    from sqlalchemy import select
    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "generate")))
    assert len(logs) == 1
    assert logs[0].status == "success"


def test_chat_writes_llm_call_log_on_failure(client, registered_user, db_session, monkeypatch):
    """chat 端点 LLM 异常时写一条 LLMCallLog（status=failed, error 记原因）。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_chat(db, sec, history, msg, **kwargs):
        raise RuntimeError("boom")
        yield  # 让它成为 async generator

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert "event: error" in res.text

    from app.models import LLMCallLog
    from sqlalchemy import select
    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "chat")))
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "failed"
    assert log.error is not None
    assert "boom" in log.error


# ── Fix 2: list_messages 必须按 conversation_id 隔离（防串历史）──

def test_list_messages_requires_conversation_id(client, registered_user, db_session):
    """list_messages 缺省 conversation_id 时应拒绝（422），
    避免前端漏传时把 section 下所有会话的消息混在一起（串历史 bug 根因）。
    """
    section = _make_logged_in_section(client, registered_user, db_session)

    # 不传 conversation_id
    res = client.get(f"/api/v1/sections/{section.id}/messages")
    assert res.status_code == 422, f"缺省 conversation_id 应 422，实际 {res.status_code}: {res.text}"


def test_list_messages_isolated_by_conversation(client, registered_user, db_session):
    """两个会话的消息互不串：传 A 的 conversation_id 只看到 A 的消息。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    # 建两个会话
    conv_a = client.post(f"/api/v1/sections/{section.id}/conversations", json={"title": "A"}).json()
    conv_b = client.post(f"/api/v1/sections/{section.id}/conversations", json={"title": "B"}).json()

    # 直接写消息（绕过 LLM）；conversation_id 列是 UUID，需转回 UUID
    import uuid as _uuid
    from app.models import Message
    db_session.add(Message(section_id=section.id, conversation_id=_uuid.UUID(conv_a["id"]), role="user", content="msg-in-A"))
    db_session.add(Message(section_id=section.id, conversation_id=_uuid.UUID(conv_b["id"]), role="user", content="msg-in-B"))
    db_session.commit()

    res_a = client.get(f"/api/v1/sections/{section.id}/messages?conversation_id={conv_a['id']}")
    assert res_a.status_code == 200
    contents_a = [m["content"] for m in res_a.json()]
    assert contents_a == ["msg-in-A"], f"会话 A 不应包含 B 的消息，实际 {contents_a}"


# ── Fix 5: get_llm 透传 BYOK / 全局配置 ──

def test_get_llm_uses_resolved_config_over_defaults(monkeypatch):
    """get_llm 传入 base_url/api_key/model 时应优先使用，而非 settings 默认值。"""
    from app.ai.llm_client import get_llm

    captured = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.ai.llm_client.ChatOpenAI", _FakeChatOpenAI)

    get_llm(
        base_url="https://user.byok.example/v1",
        api_key="sk-user-key",
        model="user-model-x",
    )

    assert captured["base_url"] == "https://user.byok.example/v1"
    assert captured["api_key"] == "sk-user-key"
    assert captured["model"] == "user-model-x"


def test_get_llm_falls_back_to_settings_when_no_config(monkeypatch):
    """get_llm 无参调用时回退 settings（保持向后兼容）。"""
    from app.ai.llm_client import get_llm

    captured = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("app.ai.llm_client.ChatOpenAI", _FakeChatOpenAI)

    get_llm()
    s = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    assert captured["base_url"] == s.glm_base_url
    assert captured["model"] == s.glm_model


# ── 草稿会话 + LLM 标题总结 ──

def test_chat_summarizes_title_on_first_message(client, registered_user, db_session, monkeypatch):
    """草稿会话首条对话完成后：done 事件带 title，会话转 active。"""
    import json as _json

    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_chat(db, sec, history, msg, **kwargs):
        yield "你好，这是回复"

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)
    # mock 标题总结，避免真实 LLM 调用
    monkeypatch.setattr(
        "app.api.ai.conversation_service.summarize_conversation_title",
        lambda db, conv, u, a, llm_config=None: "权利要求讨论",
    )

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "我想讨论权利要求"})
    assert res.status_code == 200
    body = res.text

    # done 事件带 title + conversation_id
    assert "event: done" in body
    done_line = [l for l in body.split("\n") if l.startswith("data: ") and "message_id" in l][-1]
    done_data = _json.loads(done_line[6:])
    assert done_data["title"] == "权利要求讨论"
    assert "conversation_id" in done_data

    # 会话已转 active
    db_session.expire_all()
    from app.models import Conversation
    from sqlalchemy import select as _sel
    conv = db_session.scalar(_sel(Conversation).where(Conversation.section_id == section.id))
    assert conv.status == "active"
    assert conv.title == "权利要求讨论"


def test_chat_does_not_resummarize_active_conversation(client, registered_user, db_session, monkeypatch):
    """已是 active 的会话再 chat：done 不带 title（不重复总结）。"""
    import json as _json

    section = _make_logged_in_section(client, registered_user, db_session)

    # 先建一个 active 会话
    from app.models import Conversation, ConversationStatus
    conv = Conversation(
        section_id=section.id, title="已有标题",
        status=ConversationStatus.active.value,
    )
    db_session.add(conv)
    db_session.commit()
    conv_id = str(conv.id)

    summarize_called = {"n": 0}
    def fake_summarize(db, c, u, a, llm_config=None):
        summarize_called["n"] += 1
        return "不应被调用"

    async def fake_astream_chat(db, sec, history, msg, **kwargs):
        yield "回复"

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)
    monkeypatch.setattr("app.api.ai.conversation_service.summarize_conversation_title", fake_summarize)

    res = client.post(
        f"/api/v1/sections/{section.id}/chat",
        json={"message": "继续聊", "conversation_id": conv_id},
    )
    assert res.status_code == 200
    body = res.text

    done_line = [l for l in body.split("\n") if l.startswith("data: ") and "message_id" in l][-1]
    done_data = _json.loads(done_line[6:])
    assert done_data["title"] is None  # active 会话不重新总结
    assert summarize_called["n"] == 0


def test_list_conversations_filter_by_status(client, registered_user, db_session):
    """list_conversations 支持 status 过滤。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    from app.models import Conversation, ConversationStatus
    db_session.add(Conversation(section_id=section.id, title="草稿1", status=ConversationStatus.draft.value))
    db_session.add(Conversation(section_id=section.id, title="正式1", status=ConversationStatus.active.value))
    db_session.add(Conversation(section_id=section.id, title="正式2", status=ConversationStatus.active.value))
    db_session.commit()

    # 不过滤：返回全部
    all_convs = client.get(f"/api/v1/sections/{section.id}/conversations").json()
    assert len(all_convs) == 3

    # 过滤 draft
    drafts = client.get(f"/api/v1/sections/{section.id}/conversations?status=draft").json()
    assert len(drafts) == 1
    assert drafts[0]["title"] == "草稿1"
    assert drafts[0]["status"] == "draft"

    # 过滤 active
    actives = client.get(f"/api/v1/sections/{section.id}/conversations?status=active").json()
    assert len(actives) == 2
    assert all(c["status"] == "active" for c in actives)
