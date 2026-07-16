def _make_logged_in_section(client, registered_user, db_session):
    """登录 + 建项目 + 给用户配 BYOK（阶段 0 strict：端点要求生效 LLM 配置）+ 返回第一个 section。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from app.models import User, UserLLMConfig
    from app.core.security import encrypt_value
    from sqlalchemy import select

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    # 配 BYOK（阶段 0 strict：无配置则端点发 no_llm_config 错误）
    db_session.add(UserLLMConfig(
        user_id=user.id, provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model", embedding_model="test-embed", is_active=True,
    ))
    db_session.commit()
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
