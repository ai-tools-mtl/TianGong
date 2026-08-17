def _make_logged_in_section(client, registered_user, db_session):
    """登录 + 建项目 + 给用户配自定义配置（阶段 0 strict：端点要求生效 LLM 配置）+ 返回第一个 section。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from app.models import User, UserLLMConfig
    from app.core.security import encrypt_value
    from sqlalchemy import select

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    # 配自定义配置（阶段 0 strict：无配置则端点发 no_llm_config 错误）
    db_session.add(UserLLMConfig(
        user_id=user.id, name="test", provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model",
    ))
    db_session.commit()
    p = create_project(db_session, user=user, title="测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
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

    # mock astream_chat 返回固定 token（Task 23：orchestrator yield (kind, payload) 元组）
    async def fake_astream_chat(db, section, history, msg, **kwargs):
        yield ("token", "hello")

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
        yield ("token", "# 标题")

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
        yield ("token", "first")
        await asyncio.sleep(0.6)  # > 心跳间隔，触发心跳
        yield ("token", "second")  # 心跳后这个 token 必须仍能到达（原 bug 会丢失）

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
        yield ("token", "hello")

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
        yield ("token", "# 标题")

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


def test_chat_persists_partial_response_on_exception(client, registered_user, db_session, monkeypatch):
    """异常兜底：流式 yield 几个 token 后抛异常，已生成的半截内容应落库（标 incomplete），而非丢弃。

    旧实现 except 块直接 rollback，full_response 彻底丢失，表现为「有问无答」。
    改后保留半截 + meta.incomplete=True，并仍向前端发 error 事件。
    """
    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_chat(db, sec, history, msg, **kwargs):
        yield ("token", "这是已经")
        yield ("token", "生成的半截")
        raise RuntimeError("LLM 炸了")

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    body = res.text
    # 前端仍收到已 yield 的 token
    assert "这是已经" in body
    # 异常被友好化转发为 error 事件
    assert "event: error" in body

    # 关键断言：半截内容落库（不再丢），且标 incomplete
    db_session.expire_all()
    from app.models import Message as _Msg
    msgs = db_session.query(_Msg).filter_by(section_id=section.id).all()
    assert len(msgs) == 2  # user + assistant（半截）
    ai_msg = next(m for m in msgs if m.role == "assistant")
    assert "这是已经生成的半截" in ai_msg.content
    assert ai_msg.meta.get("incomplete") is True


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


# ── Fix 5: get_llm 透传自定义配置 / 全局配置 ──
# 本地 P2 设计：get_llm(llm_config: ResolvedChatConfig) —— 接收已解析的配置对象，
# 不做 settings 回退（调用方负责先 resolve_chat_config 并处理 None）。
# 下面两个测试验证该契约：传入的 ResolvedChatConfig 字段直接驱动 ChatOpenAI 构造。

def test_get_llm_uses_resolved_config_fields(monkeypatch):
    """get_llm(llm_config) 应把 ResolvedChatConfig 的 base_url/api_key/model 透传给 ChatOpenAI。"""
    from app.ai.llm_client import get_llm
    from app.services.llm_config_service import ResolvedChatConfig

    captured = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    # get_llm 现返回 ReasoningChatOpenAI（ChatOpenAI 子类，透传 reasoning_content），
    # 故 monkeypatch 子类而非基类。
    monkeypatch.setattr("app.ai.llm_client.ReasoningChatOpenAI", _FakeChatOpenAI)

    cfg = ResolvedChatConfig(
        base_url="https://user.custom.example/v1",
        api_key="sk-user-key",
        model="user-model-x",
        source="user",
    )
    get_llm(cfg)

    assert captured["base_url"] == "https://user.custom.example/v1"
    assert captured["api_key"] == "sk-user-key"
    assert captured["model"] == "user-model-x"


def test_get_llm_streaming_enables_stream_usage(monkeypatch):
    """streaming/stream_usage 参数透传（断链 C3：流式回传 token 用量给 usage_sink）。

    两参数独立（agent.py 调用方显式传 stream_usage=True）——streaming=True
    不隐式开启 stream_usage。
    """
    from app.ai.llm_client import get_llm
    from app.services.llm_config_service import ResolvedChatConfig

    captured = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    # get_llm 现返回 ReasoningChatOpenAI（ChatOpenAI 子类，透传 reasoning_content），
    # 故 monkeypatch 子类而非基类。
    monkeypatch.setattr("app.ai.llm_client.ReasoningChatOpenAI", _FakeChatOpenAI)

    cfg = ResolvedChatConfig(
        base_url="https://global.example/v1",
        api_key="sk-global",
        model="global-model",
        source="global",
    )
    get_llm(cfg, streaming=True, stream_usage=True)
    assert captured["streaming"] is True
    assert captured["stream_usage"] is True

    # 独立性：只开 streaming 不带 stream_usage
    captured.clear()
    get_llm(cfg, streaming=True)
    assert captured["streaming"] is True
    assert captured["stream_usage"] is False

    # 非 streaming 时两者均 False
    captured.clear()
    get_llm(cfg, streaming=False)
    assert captured["streaming"] is False
    assert captured["stream_usage"] is False


# ── 草稿会话 + LLM 标题总结 ──

def test_chat_summarizes_title_on_first_message(client, registered_user, db_session, monkeypatch):
    """草稿会话首条对话完成后：done 事件带 title，会话转 active。"""
    import json as _json

    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_chat(db, sec, history, msg, **kwargs):
        yield ("token", "你好，这是回复")

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)
    # mock 标题总结，避免真实 LLM 调用
    monkeypatch.setattr(
        "app.api.ai.conversation_service.summarize_conversation_title",
        lambda db, conv, u, a, user_id=None: "权利要求讨论",  # 对齐真实签名（db, conversation, first_user, first_ai, user_id）
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
    def fake_summarize(db, c, u, a, user_id=None):
        summarize_called["n"] += 1
        return "不应被调用"

    async def fake_astream_chat(db, sec, history, msg, **kwargs):
        yield ("token", "回复")

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


# ── 1214 修复闸 4：LLM 错误汉化 ──
# 根因：ai.py 的 except 把 str(e) 原样塞进 SSE error message，
# 前端 toast 显示晦涩英文 "Error code: 400 - {'error':{'code':'1214'...}}"。
# 修复：抽 _friendly_llm_error 把已知错误（1214 model空/1002 key无效）转中文友好提示。

def test_chat_sse_error_friendly_when_model_empty(client, registered_user, db_session, monkeypatch):
    """LLM 抛 1214（model 空）时，SSE error 的 message 应为中文友好提示，非晦涩英文。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    async def raise_model_empty(db, sec, history, msg, **kwargs):
        raise Exception("Error code: 400 - {'error': {'code': '1214', 'message': 'model:The model code cannot be empty.'}}")
        yield  # noqa: 让函数成为 async generator

    monkeypatch.setattr("app.api.ai.astream_chat", raise_model_empty)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    # SSE error 的 message 不能再含原始英文错误码
    assert "model code cannot be empty" not in res.text
    assert "1214" not in res.text
    # 应含中文友好提示（含"模型"关键词）
    assert "模型" in res.text


def test_chat_sse_error_friendly_when_auth_invalid(client, registered_user, db_session, monkeypatch):
    """LLM 抛 1002（key 无效）时，SSE error 的 message 应为中文友好提示。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    async def raise_auth_invalid(db, sec, history, msg, **kwargs):
        raise Exception("Error code: 401 - {'error': {'code': '1002', 'message': 'Authorization Token非法'}}")
        yield  # noqa

    monkeypatch.setattr("app.api.ai.astream_chat", raise_auth_invalid)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert "Authorization Token" not in res.text
    assert "API Key" in res.text or "密钥" in res.text or "授权" in res.text


def test_chat_sse_error_keeps_unknown_error_message(client, registered_user, db_session, monkeypatch):
    """未识别的错误保留原始 message（截断），不丢失信息。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    async def raise_unknown(db, sec, history, msg, **kwargs):
        raise Exception("某种未知错误XYZ123")
        yield  # noqa

    monkeypatch.setattr("app.api.ai.astream_chat", raise_unknown)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert "某种未知错误XYZ123" in res.text


# ── Task 23：agent loop 透明化（SSE 暴露 tool_call/tool_result）──

def test_chat_emits_tool_call_and_tool_result_events(client, registered_user, db_session, monkeypatch):
    """chat 端点：orchestrator yield 的 tool_call/tool_result 元组应转为对应 SSE 事件。

    前端据此显示"正在检索知识库..."等进度提示，agent loop 不再黑盒。
    验证事件类型、payload 字段、token 仍正常累加、done 事件带 message_id。
    """
    import json as _json

    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_chat(db, sec, history, msg, **kwargs):
        # 模拟 agent loop：先调工具，再出文本 token
        yield ("tool_call", {"name": "rag_search", "args": {"query": "权利要求"}})
        yield ("tool_result", {"name": "rag_search", "result": "相关文档片段..."})
        yield ("token", "基于检索结果，")

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "帮我查"})
    assert res.status_code == 200
    body = res.text

    # tool_call 事件
    assert "event: tool_call" in body
    tool_call_data = _json.loads(
        [l for l in body.split("\n") if l.startswith("data: ") and "rag_search" in l and "query" in l][0][6:]
    )
    assert tool_call_data["name"] == "rag_search"
    assert tool_call_data["args"] == {"query": "权利要求"}

    # tool_result 事件
    assert "event: tool_result" in body
    tool_result_data = _json.loads(
        [l for l in body.split("\n") if l.startswith("data: ") and "result" in l][0][6:]
    )
    assert tool_result_data["name"] == "rag_search"
    assert tool_result_data["result"] == "相关文档片段..."

    # token 仍正常出
    assert "event: token" in body
    assert "基于检索结果" in body

    # done 仍带 message_id
    assert "event: done" in body


def test_generate_emits_tool_call_and_tool_result_events(client, registered_user, db_session, monkeypatch):
    """generate 端点：同样透传 tool_call/tool_result SSE 事件 + token 累加存草稿。"""
    import json as _json

    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_generate(db, sec, history, **kwargs):
        yield ("tool_call", {"name": "rag_search", "args": {"query": "背景"}})
        yield ("tool_result", {"name": "rag_search", "result": "背景知识"})
        yield ("token", "# 草稿标题")

    monkeypatch.setattr("app.api.ai.astream_generate", fake_astream_generate)

    res = client.post(f"/api/v1/sections/{section.id}/generate")
    assert res.status_code == 200
    body = res.text

    assert "event: tool_call" in body
    assert "event: tool_result" in body
    assert "event: token" in body
    assert "草稿标题" in body
    assert "event: done" in body

    # 草稿仍正确累加并落库
    db_session.expire_all()
    from app.models import Section
    s = db_session.get(Section, section.id)
    assert s.content is not None


def test_update_conversation_calls_refresh_after_commit(client, registered_user, db_session, monkeypatch):
    """C1 修复：PATCH /sections/{sid}/conversations/{cid} commit 后必须 db.refresh(conv)。

    与 memories.py 同类 stale-read：update_conversation 读 updated_at（onupdate）后未 refresh，
    expire_on_commit=False 下返回 stale 时间戳。SQLite 不执行 PG server_default/onupdate，
    无法断言时间戳变化，故 spy Session.refresh 验证修复存在。
    """
    from sqlalchemy.orm import Session
    section = _make_logged_in_section(client, registered_user, db_session)

    # 先建一个会话（create 路径也会调 refresh，但我们只关心 update 的 refresh）
    created = client.post(
        f"/api/v1/sections/{section.id}/conversations", json={"title": "原标题"}
    ).json()
    cid = created["id"]

    # 重置计数，只统计 update 的 refresh
    call_count = {"n": 0}
    orig_refresh = Session.refresh

    def spy_refresh(self, *args, **kwargs):
        call_count["n"] += 1
        return orig_refresh(self, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", spy_refresh)

    r = client.patch(
        f"/api/v1/sections/{section.id}/conversations/{cid}", json={"title": "新标题"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "新标题"
    assert call_count["n"] >= 1, "update_conversation commit 后必须调用 db.refresh（C1 修复）"
