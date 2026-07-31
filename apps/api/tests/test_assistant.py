# apps/api/tests/test_assistant.py
"""ChatGPT 式初始化助手 API 测试：顶层 init 会话 CRUD + chat + generate。

详见 docs/superpowers/specs/2026-07-31-chatgpt-style-init-assistant-design.md。
"""
from uuid import UUID

from app.models import Conversation, KIND_INIT, Message, Project, Section
from app.services.seed_service import ensure_default_template


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })


def _make_user_with_config(client, registered_user, db_session):
    """登录 + 配 LLM（端点要求生效配置）。返回 user ORM。"""
    from app.models import User, UserLLMConfig
    from app.core.security import encrypt_value
    from sqlalchemy import select

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    db_session.add(UserLLMConfig(
        user_id=user.id, name="test", provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model",
    ))
    db_session.commit()
    _login(client, registered_user)
    return user


# ── CRUD ─────────────────────────────────────────────────────────────

def test_create_and_list_conversations(client, registered_user, db_session):
    """创建 init 会话，列表只列未落地的。"""
    _make_user_with_config(client, registered_user, db_session)
    c1 = client.post("/api/v1/assistant/conversations", json={"title": "想法A"}).json()
    client.post("/api/v1/assistant/conversations")  # 默认标题
    assert c1["title"] == "想法A"

    res = client.get("/api/v1/assistant/conversations")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_get_conversation_returns_messages(client, registered_user, db_session):
    """取会话含消息历史。"""
    _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()
    # 直接写消息（绕过 LLM，init 消息 section_id=NULL）
    c = db_session.get(Conversation, UUID(conv["id"]))
    db_session.add(Message(conversation_id=c.id, section_id=None, role="user", content="hi"))
    db_session.commit()

    res = client.get(f"/api/v1/assistant/conversations/{conv['id']}")
    assert res.status_code == 200
    assert res.json()["project_id"] is None
    assert len(res.json()["messages"]) == 1
    assert res.json()["messages"][0]["content"] == "hi"


def test_delete_conversation(client, registered_user, db_session):
    """删除未落地会话。"""
    _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()
    res = client.delete(f"/api/v1/assistant/conversations/{conv['id']}")
    assert res.status_code == 204
    assert len(client.get("/api/v1/assistant/conversations").json()) == 0


def test_ownership_other_user_404(client, registered_user, db_session):
    """非本人会话 CRUD 返回 404。"""
    _make_user_with_config(client, registered_user, db_session)
    from app.models import User
    other = User(username="other2", email="other2@test.com", password_hash="x", name="o")
    db_session.add(other)
    db_session.commit()
    other_conv = Conversation(kind=KIND_INIT, user_id=other.id, section_id=None, title="别人的")
    db_session.add(other_conv)
    db_session.commit()

    assert client.get(f"/api/v1/assistant/conversations/{other_conv.id}").status_code == 404
    assert client.delete(f"/api/v1/assistant/conversations/{other_conv.id}").status_code == 404


# ── chat（mock）──────────────────────────────────────────────────────

def test_chat_emits_token_done_and_ready_flag(client, registered_user, db_session, monkeypatch):
    """chat SSE：token/done + ready_to_create 由 [READY_TO_CREATE] 标记判定。"""
    _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()

    async def fake_astream_init_chat(history, user_input, **kwargs):
        yield "信息够了，可以创建了"
        yield "\n[READY_TO_CREATE]"

    monkeypatch.setattr("app.api.assistant.astream_init_chat", fake_astream_init_chat)

    res = client.post(f"/api/v1/assistant/conversations/{conv['id']}/chat", json={"message": "我想做XX"})
    assert res.status_code == 200
    body = res.text
    assert "event: token" in body
    assert "可以创建了" in body
    assert "event: done" in body

    import json as _json
    done_line = [l for l in body.split("\n") if l.startswith("data: ") and "ready_to_create" in l][-1]
    assert _json.loads(done_line[6:])["ready_to_create"] is True

    # 消息落库（section_id=NULL）
    db_session.expire_all()
    msgs = db_session.query(Message).filter_by(conversation_id=UUID(conv["id"])).all()
    assert len(msgs) == 2  # user + assistant
    assert all(m.section_id is None for m in msgs)


def test_chat_ready_false_without_marker(client, registered_user, db_session, monkeypatch):
    """无标记时 ready_to_create=false。"""
    _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()

    async def fake_astream_init_chat(history, user_input, **kwargs):
        yield "还需要补充技术领域"

    monkeypatch.setattr("app.api.assistant.astream_init_chat", fake_astream_init_chat)

    res = client.post(f"/api/v1/assistant/conversations/{conv['id']}/chat", json={"message": "hi"})
    import json as _json
    done_line = [l for l in res.text.split("\n") if l.startswith("data: ") and "ready_to_create" in l][-1]
    assert _json.loads(done_line[6:])["ready_to_create"] is False


# ── generate（mock）──────────────────────────────────────────────────

def test_generate_creates_project_and_marks_conversation(client, registered_user, db_session, monkeypatch):
    """generate：建项目+填章+会话 project_id 填上。"""
    user = _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()

    async def fake_astream_init_generate(db, conversation, history, user, **kwargs):
        from app.services.project_service import create_project
        from app.models import Section as _S
        from sqlalchemy import select as _sel
        project = create_project(db, user=user, title="测试项目")
        conversation.project_id = project.id
        db.commit()
        yield ("project_created", {"project_id": str(project.id)})
        secs = list(db.scalars(_sel(_S).where(_S.project_id == project.id).order_by(_S.order)))
        for idx, sec in enumerate(secs, start=1):
            yield ("chapter_start", {"index": idx, "total": len(secs), "title": sec.title, "key": sec.key})
            from app.ai.markdown_to_tiptap import markdown_to_tiptap
            sec.content = markdown_to_tiptap(f"{sec.title}初稿")
            sec.status = "drafting"
            db.commit()
            yield ("chapter_done", {"index": idx, "title": sec.title, "key": sec.key, "status": "ok", "error": None})
        yield ("all_done", {"project_id": str(project.id)})

    monkeypatch.setattr("app.api.assistant.astream_init_generate", fake_astream_init_generate)

    res = client.post(f"/api/v1/assistant/conversations/{conv['id']}/generate")
    assert res.status_code == 200
    body = res.text
    assert "event: project_created" in body
    assert "event: chapter_done" in body
    assert "event: done" in body

    # 会话已落地（project_id 非 NULL）→ 列表不再显示
    db_session.expire_all()
    c = db_session.get(Conversation, UUID(conv["id"]))
    assert c.project_id is not None
    assert len(client.get("/api/v1/assistant/conversations").json()) == 0
    # 项目 + 8 章已建
    project = db_session.get(Project, c.project_id)
    assert project is not None
    secs = db_session.query(Section).filter_by(project_id=project.id).all()
    assert len(secs) == 8
    assert all(s.content is not None for s in secs)


def test_generate_rejects_already_landed(client, registered_user, db_session):
    """已落地的会话再次 generate 报错。"""
    user = _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()
    c = db_session.get(Conversation, UUID(conv["id"]))
    p = Project(user_id=user.id, title="x")
    db_session.add(p)
    db_session.flush()
    c.project_id = p.id
    db_session.commit()

    res = client.post(f"/api/v1/assistant/conversations/{conv['id']}/generate")
    assert res.status_code in (400, 422)
