# apps/api/tests/test_init_assistant.py
"""项目初始化助手 API 测试（阶段 A）。

覆盖：
- POST /projects/from-chat：从描述建项目+8空章节，返回 project_id/section_id，metadata 存 description
- POST /projects/{id}/init-chat：SSE 流式对话（mock），验证 token/done + conversation 创建
- POST /projects/{id}/init-generate：批量生成（mock），验证章节进度事件 + 各章 content 落库 + status 流转
- GET /projects/{id}/init-conversation：取对话历史
- 归属校验：非本人项目 404
"""
from uuid import UUID

from app.models import Project, Section
from app.services.seed_service import ensure_default_template


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })


def _make_user_with_config(client, registered_user, db_session):
    """登录 + 配 LLM 配置（端点要求生效配置）。返回 registered_user。"""
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
    return registered_user


# ── from-chat 建项目 ──────────────────────────────────────────────────

def test_from_chat_creates_project_with_sections(client, registered_user, db_session):
    """from-chat：从描述建项目，生成 8 空 section，metadata 存 description。"""
    _make_user_with_config(client, registered_user, db_session)

    res = client.post("/api/v1/projects/from-chat", json={
        "description": "我想做一个基于大模型的智能客服路由方法"
    })
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["project_id"]
    assert data["section_id"]
    assert "智能客服" in data["title"]  # 标题取自描述前 30 字

    # 验证项目 + 8 section
    db_session.expire_all()
    project = db_session.get(Project, UUID(data["project_id"]))
    assert project is not None
    assert project.metadata_.get("init_description") == "我想做一个基于大模型的智能客服路由方法"
    sections = db_session.query(Section).filter_by(project_id=project.id).all()
    assert len(sections) == 8  # 默认模板 8 章
    # 首个 section（order 最小）应是返回的 section_id
    first = min(sections, key=lambda s: s.order)
    assert str(first.id) == data["section_id"]


def test_from_chat_rejects_empty_description(client, registered_user, db_session):
    """空 description 拒绝。"""
    _make_user_with_config(client, registered_user, db_session)
    res = client.post("/api/v1/projects/from-chat", json={"description": ""})
    assert res.status_code in (400, 422)


# ── init-chat SSE ─────────────────────────────────────────────────────

def test_init_chat_emits_token_and_done(client, registered_user, db_session, monkeypatch):
    """init-chat：mock astream_init_chat，验证 token/done 事件 + conversation 创建 + 消息落库。"""
    user = _make_user_with_config(client, registered_user, db_session)
    # 先 from-chat 建项目
    pid = client.post("/api/v1/projects/from-chat", json={
        "description": "一种数据加密传输方法"
    }).json()["project_id"]

    async def fake_astream_init_chat(history, user_input, **kwargs):
        yield "你好，我们来聊聊技术领域"

    monkeypatch.setattr("app.api.init_assistant.astream_init_chat", fake_astream_init_chat)

    res = client.post(f"/api/v1/projects/{pid}/init-chat", json={"message": "我想做个加密方法"})
    assert res.status_code == 200
    body = res.text
    assert "event: token" in body
    assert "我们来聊聊技术领域" in body
    assert "event: done" in body

    # 验证对话挂在首个 section 下 + 消息落库
    from app.models import Conversation, Message
    from sqlalchemy import select
    db_session.expire_all()
    project = db_session.get(Project, UUID(pid))
    first_section = db_session.scalar(
        select(Section).where(Section.project_id == project.id).order_by(Section.order).limit(1)
    )
    convs = list(db_session.scalars(select(Conversation).where(Conversation.section_id == first_section.id)))
    assert len(convs) == 1
    msgs = list(db_session.scalars(
        select(Message).where(Message.section_id == first_section.id).order_by(Message.created_at)
    ))
    # user + assistant 各一条
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"


# ── init-generate 批量 ────────────────────────────────────────────────

def test_init_generate_fills_all_sections(client, registered_user, db_session, monkeypatch):
    """init-generate：mock astream_init_generate，验证章节进度事件 + 各章 content 落库。

    init_generate 直接 mock 编排函数（绕过真实 LLM），产出 chapter_start/token/chapter_done/all_done。
    """
    _make_user_with_config(client, registered_user, db_session)
    pid = client.post("/api/v1/projects/from-chat", json={
        "description": "一种分布式任务调度系统"
    }).json()["project_id"]

    # mock 编排：模拟生成 2 章（name + field），每章 yield 事件序列
    async def fake_astream_init_generate(db, project, history, **kwargs):
        from app.models import Section as _S
        from sqlalchemy import select as _sel
        secs = list(db.scalars(_sel(_S).where(_S.project_id == project.id).order_by(_S.order)))
        total = len(secs)
        for idx, sec in enumerate(secs, start=1):
            yield ("chapter_start", {"index": idx, "total": total, "title": sec.title, "key": sec.key})
            yield ("token", f"{sec.title}的初稿内容")
            # 回写（模拟真实编排的落库行为）
            from app.ai.markdown_to_tiptap import markdown_to_tiptap
            sec.content = markdown_to_tiptap(f"{sec.title}的初稿内容")
            if sec.status == "empty":
                sec.status = "drafting"
            db.commit()
            yield ("chapter_done", {"index": idx, "title": sec.title, "status": "ok", "error": None})
        yield ("all_done", {"project_id": str(project.id)})

    monkeypatch.setattr("app.api.init_assistant.astream_init_generate", fake_astream_init_generate)

    res = client.post(f"/api/v1/projects/{pid}/init-generate")
    assert res.status_code == 200
    body = res.text
    # 进度事件
    assert "event: chapter_start" in body
    assert "event: chapter_done" in body
    assert "event: done" in body  # all_done → done

    # 验证所有章节都被填充
    db_session.expire_all()
    sections = db_session.query(Section).filter_by(project_id=db_session.get(Project, UUID(pid)).id).all()
    assert len(sections) == 8
    for s in sections:
        assert s.content is not None, f"章节 {s.title} 未被填充"
        assert s.status == "drafting", f"章节 {s.title} 状态未流转"


# ── init-conversation 取历史 ──────────────────────────────────────────

def test_init_conversation_returns_history(client, registered_user, db_session):
    """init-conversation：返回对话历史（先 init-chat 再取）。"""
    _make_user_with_config(client, registered_user, db_session)
    pid = client.post("/api/v1/projects/from-chat", json={"description": "测试取历史"}).json()["project_id"]

    # 直接写消息（绕过 LLM），挂首个 section
    from app.models import Conversation, Message
    from sqlalchemy import select
    project = db_session.get(Project, UUID(pid))
    first_section = db_session.scalar(
        select(Section).where(Section.project_id == project.id).order_by(Section.order).limit(1)
    )
    conv = Conversation(section_id=first_section.id, title="测试对话")
    db_session.add(conv)
    db_session.flush()
    db_session.add(Message(section_id=first_section.id, conversation_id=conv.id, role="user", content="用户的话"))
    db_session.add(Message(section_id=first_section.id, conversation_id=conv.id, role="assistant", content="助手的话"))
    db_session.commit()
    conv_id = str(conv.id)

    # 带 conversation_id 取
    res = client.get(f"/api/v1/projects/{pid}/init-conversation?conversation_id={conv_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["conversation_id"] == conv_id
    assert len(data["messages"]) == 2
    assert data["messages"][0]["content"] == "用户的话"

    # 不带 conversation_id：取最近一个对话
    res2 = client.get(f"/api/v1/projects/{pid}/init-conversation")
    assert res2.status_code == 200
    assert res2.json()["conversation_id"] == conv_id


def test_init_conversation_empty_when_no_conversation(client, registered_user, db_session):
    """无对话时返回空。"""
    _make_user_with_config(client, registered_user, db_session)
    pid = client.post("/api/v1/projects/from-chat", json={"description": "空项目"}).json()["project_id"]

    res = client.get(f"/api/v1/projects/{pid}/init-conversation")
    assert res.status_code == 200
    assert res.json()["conversation_id"] is None
    assert res.json()["messages"] == []


# ── 归属校验 ──────────────────────────────────────────────────────────

def test_init_chat_rejects_other_users_project(client, registered_user, db_session):
    """非本人项目 init-chat 返回 404（防探测）。"""
    _make_user_with_config(client, registered_user, db_session)
    # 建一个别人的项目
    from app.models import User
    from app.services.project_service import create_project
    other = User(username="other", email="other@test.com", password_hash="x", name="其他")
    db_session.add(other)
    db_session.commit()
    other_project = create_project(db_session, user=other, title="别人的")

    res = client.post(f"/api/v1/projects/{other_project.id}/init-chat", json={"message": "hi"})
    assert res.status_code == 404
