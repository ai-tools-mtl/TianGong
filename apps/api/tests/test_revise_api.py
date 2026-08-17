# apps/api/tests/test_revise_api.py
"""revise 端点（T2 批 1）：建议 → 章节针对性修订。

spec：docs/superpowers/specs/2026-08-17-advice-revision-loop-design.md §3.1
- POST /sections/{sid}/revise（SSE：token/thinking/tool_call/tool_result/heartbeat/done/error）
- done 带 {content: 权威全文, section_id}；不写 section.content、不建 Message、不建 conversation
- 不传 checkpointer（spec §3.1.3：config=None + checkpointer 会入口级 ValueError，探针坐实）
- directives 1..10 条、每条 1..500 字；origin 白名单（仅记账）
"""
import asyncio
import uuid

import pytest
from pydantic import ValidationError


# ===== helpers（复用 test_orchestrator.py 的模式） =====

def _build_section_with_project(db_session, *, content=None, status="drafting", user=None):
    """构造真实入库的 User + Project + Section（content 可指定 Tiptap JSON）。

    user 可传入已有用户（端点测试需 owner=登录用户）；None 时新建。
    """
    from app.models import Project, Section, User
    from app.core.security import hash_password
    if user is not None:
        u = user
    else:
        u = User(
            username=f"test-{uuid.uuid4().hex[:8]}",
            email=f"test-{uuid.uuid4().hex[:8]}@tiangong.dev",
            password_hash=hash_password("Pass1234!"),
            name="测试用户",
        )
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
    p = Project(user_id=u.id, title="修订测试项目")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    s = Section(
        project_id=p.id,
        template_section_id="ts-solution",
        order=5, key="solution", title="技术方案",
        content=content, status=status,
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return u, p, s


def _tiptap_para(text: str) -> dict:
    """单段落 Tiptap JSON。"""
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def _make_fake_build_agent(captured: dict, events=()):
    """fake build_agent：捕获调用参数，返回可产出预置事件的假 agent。"""

    class _FakeAgent:
        async def astream_events(self, input_, *, version="v2", config=None):
            captured["astream_input"] = input_
            captured["config"] = config
            for e in events:
                yield e
            return

    async def _build_agent(db, *, llm_config, user_id, section=None, **kw):
        captured.setdefault("build_args_list", []).append({**kw, "section": section})
        return _FakeAgent()

    return _build_agent


def _token_event(text: str) -> dict:
    from langchain_core.messages import AIMessageChunk
    return {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content=text)}}


# ===== Task 1.1: ReviseRequest schema =====

class TestReviseRequest:
    def test_valid(self):
        from app.schemas.ai import ReviseRequest
        r = ReviseRequest(directives=["补充实施例", "统一术语为「模块」"], origin="review")
        assert r.origin == "review"
        assert r.chat_source is None

    def test_directives_stripped(self):
        from app.schemas.ai import ReviseRequest
        r = ReviseRequest(directives=["  补充实施例  "])
        assert r.directives == ["补充实施例"]

    def test_directives_empty_rejected(self):
        from app.schemas.ai import ReviseRequest
        with pytest.raises(ValidationError):
            ReviseRequest(directives=[])

    def test_directives_blank_rejected(self):
        from app.schemas.ai import ReviseRequest
        with pytest.raises(ValidationError):
            ReviseRequest(directives=["   "])

    def test_directives_over_10_rejected(self):
        from app.schemas.ai import ReviseRequest
        with pytest.raises(ValidationError):
            ReviseRequest(directives=["x"] * 11)

    def test_directive_over_500_chars_rejected(self):
        from app.schemas.ai import ReviseRequest
        with pytest.raises(ValidationError):
            ReviseRequest(directives=["字" * 501])

    def test_origin_whitelist(self):
        from app.schemas.ai import ReviseRequest
        with pytest.raises(ValidationError):
            ReviseRequest(directives=["x"], origin="evil")
        for ok in ("review", "novelty", "terms", "manual"):
            ReviseRequest(directives=["x"], origin=ok)

    def test_origin_default_manual(self):
        from app.schemas.ai import ReviseRequest
        assert ReviseRequest(directives=["x"]).origin == "manual"


# ===== Task 1.2: build_revise_instruction 纯函数 =====

class TestBuildReviseInstruction:
    def test_contains_directives_and_constraints(self, db_session):
        from app.ai.orchestrator import build_revise_instruction
        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("现有方案正文"))
        text = build_revise_instruction(db_session, s, ["补充至少两个实施例", "术语统一为「处理模块」"])
        assert "补充至少两个实施例" in text
        assert "术语统一为「处理模块」" in text
        assert "技术方案" in text  # 章节标题
        # spec §3.1.4 四类约束（最小改动 / 逐字保留 / 术语表优先 / 现有内容）
        assert "最小改动" in text
        assert "逐字保留" in text
        assert "术语表" in text
        assert "现有章节内容" in text

    def test_embeds_current_content_as_markdown(self, db_session):
        """现有内容以 _tiptap_to_markdown 转换后嵌入（与 /diff 端点同款转换器，
        LLM 看到的原文 = diff 比较的原文 → 减少格式伪 hunk，spec §7 R2）。"""
        from app.ai.orchestrator import build_revise_instruction
        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("现有方案正文ABC"))
        text = build_revise_instruction(db_session, s, ["改写"])
        assert "现有方案正文ABC" in text

    def test_directives_numbered(self, db_session):
        from app.ai.orchestrator import build_revise_instruction
        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("x"))
        text = build_revise_instruction(db_session, s, ["第一条", "第二条", "第三条"])
        assert "1. 第一条" in text and "2. 第二条" in text and "3. 第三条" in text


# ===== Task 1.3: astream_revise（mock 装配） =====

def _consume(async_gen):
    async def _drain():
        got = []
        async for item in async_gen:
            got.append(item)
        return got
    return asyncio.run(_drain())


class TestAstreamRevise:
    def test_checkpointer_explicitly_none(self, db_session, monkeypatch):
        """spec §3.1.3：revise 显式不传 checkpointer（探针坐实 config=None +
        checkpointer 会入口级 ValueError，generate 同款全坏）。"""
        from app.ai import agent as agent_mod
        from app.ai import orchestrator as orch_mod
        from app.services.llm_config_service import ResolvedChatConfig

        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("正文"))
        captured: dict = {}
        monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))
        config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
        _consume(orch_mod.astream_revise(db_session, s, ["补充实施例"], llm_config=config))
        assert captured["build_args_list"][0]["checkpointer"] is None

    def test_no_history_single_message(self, db_session, monkeypatch):
        """spec §3.1.2-3 输入语义：不带聊天历史、不 compress_history——
        input messages 仅 1 条（修订指令）。"""
        from app.ai import agent as agent_mod
        from app.ai import orchestrator as orch_mod
        from app.models import Message
        from app.services.llm_config_service import ResolvedChatConfig

        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("正文"))
        # 预置历史消息：astream_revise 不接收 history 参数，也不应影响 input
        from app.models import Conversation
        conv = Conversation(section_id=s.id)
        db_session.add(conv)
        db_session.commit()
        db_session.refresh(conv)
        db_session.add(Message(conversation_id=conv.id, section_id=s.id, role="user", content="旧对话"))
        db_session.commit()
        captured: dict = {}
        monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))
        config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
        _consume(orch_mod.astream_revise(db_session, s, ["指令A"], llm_config=config))
        messages = captured["astream_input"]["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "指令A" in messages[0]["content"]
        assert "旧对话" not in messages[0]["content"]

    def test_yields_tokens(self, db_session, monkeypatch):
        from app.ai import agent as agent_mod
        from app.ai import orchestrator as orch_mod
        from app.services.llm_config_service import ResolvedChatConfig

        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("正文"))
        captured: dict = {}
        events = [_token_event("修订"), _token_event("稿")]
        monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured, events=events))
        config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
        got = _consume(orch_mod.astream_revise(db_session, s, ["指令"], llm_config=config))
        tokens = [p for k, p in got if k == "token"]
        assert tokens == ["修订", "稿"]

    def test_intent_edit_and_no_user_input(self, db_session, monkeypatch):
        """spec §3.1.2-2：intent="edit"，user_input=None（记忆检索走章节默认路径）。"""
        from app.ai import agent as agent_mod
        from app.ai import orchestrator as orch_mod
        from app.services.llm_config_service import ResolvedChatConfig

        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("正文"))
        captured: dict = {}
        monkeypatch.setattr(agent_mod, "build_agent", _make_fake_build_agent(captured))
        config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
        _consume(orch_mod.astream_revise(db_session, s, ["指令"], llm_config=config))
        args = captured["build_args_list"][0]
        assert args.get("intent") == "edit"
        assert args.get("user_input") is None


# ===== Task 1.4: revise 端点（SSE 端到端） =====

@pytest.fixture
def revise_user(db_session):
    """配了自定 LLM 的用户（resolve_chat_config 走通）。"""
    from app.core.security import encrypt_value, hash_password
    from app.models import User, UserLLMConfig
    u = User(
        username=f"rv-{uuid.uuid4().hex[:6]}",
        email=f"rv-{uuid.uuid4().hex[:6]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="修订用户",
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(UserLLMConfig(
        user_id=u.id, name="test", provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test"),
        model="test-model",
    ))
    db_session.commit()
    return u


@pytest.fixture
def other_user(db_session):
    from app.core.security import hash_password
    from app.models import User
    u = User(
        username=f"ot-{uuid.uuid4().hex[:6]}",
        email=f"ot-{uuid.uuid4().hex[:6]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="他人",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _login(client, user):
    client.post("/api/v1/auth/login", json={
        "username": user.username, "password": "Pass1234!"})


def _fake_astream_revise(monkeypatch, tokens=("修订段落一。", "修订段落二。")):
    async def _fake(db, section, directives, *, llm_config, usage_sink=None):
        captured = {"directives": directives, "section_id": str(section.id)}
        _fake.captured = captured
        for t in tokens:
            yield ("token", t)
    _fake.captured = {}
    monkeypatch.setattr("app.api.ai.astream_revise", _fake)
    return _fake


class TestReviseEndpoint:
    def test_404_other_users_section(self, client, db_session, revise_user, other_user, monkeypatch):
        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("正文"), user=revise_user)
        _fake_astream_revise(monkeypatch)
        _login(client, other_user)
        res = client.post(f"/api/v1/sections/{s.id}/revise",
                          json={"directives": ["补充实施例"], "origin": "review"})
        assert res.status_code == 404

    def test_409_empty_content_none(self, client, db_session, revise_user, monkeypatch):
        _, _, s = _build_section_with_project(db_session, content=None, status="empty", user=revise_user)
        _fake_astream_revise(monkeypatch)
        _login(client, revise_user)
        res = client.post(f"/api/v1/sections/{s.id}/revise",
                          json={"directives": ["补充实施例"]})
        assert res.status_code == 409
        assert "尚无内容" in res.json()["message"]

    def test_409_empty_content_blank(self, client, db_session, revise_user, monkeypatch):
        """status=drafting 但内容全空白（断连半截）也 409（spec §3.1.2-1：不看 status）。"""
        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("   "), status="drafting", user=revise_user)
        _fake_astream_revise(monkeypatch)
        _login(client, revise_user)
        res = client.post(f"/api/v1/sections/{s.id}/revise",
                          json={"directives": ["补充实施例"]})
        assert res.status_code == 409

    def test_422_bad_origin(self, client, db_session, revise_user, monkeypatch):
        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("正文"), user=revise_user)
        _fake_astream_revise(monkeypatch)
        _login(client, revise_user)
        res = client.post(f"/api/v1/sections/{s.id}/revise",
                          json={"directives": ["x"], "origin": "evil"})
        assert res.status_code == 422

    def test_422_empty_directives(self, client, db_session, revise_user, monkeypatch):
        _, _, s = _build_section_with_project(db_session, content=_tiptap_para("正文"), user=revise_user)
        _fake_astream_revise(monkeypatch)
        _login(client, revise_user)
        res = client.post(f"/api/v1/sections/{s.id}/revise", json={"directives": []})
        assert res.status_code == 422

    def test_stream_and_no_persist(self, client, db_session, revise_user, monkeypatch):
        """SSE 帧序列 + done 带权威全文；不写 content、不建 Message/conversation（spec §3.1.2-4）。"""
        from app.models import Conversation, Message, Section
        _, p, s = _build_section_with_project(db_session, content=_tiptap_para("原始正文"), user=revise_user)
        fake = _fake_astream_revise(monkeypatch)
        _login(client, revise_user)
        res = client.post(f"/api/v1/sections/{s.id}/revise",
                          json={"directives": ["补充实施例", "统一术语"], "origin": "review"})
        assert res.status_code == 200
        body = res.text
        assert "event: token" in body and "修订段落一。" in body
        assert "event: done" in body
        assert '"content": "修订段落一。修订段落二。"' in body
        assert '"section_id"' in body
        assert "event: title" not in body

        # directives 透传给 astream_revise
        assert fake.captured["directives"] == ["补充实施例", "统一术语"]

        # 不落库断言
        db_session.expire_all()
        s2 = db_session.get(Section, s.id)
        assert s2.content == _tiptap_para("原始正文")  # content 未变
        assert db_session.query(Message).filter_by(section_id=s.id).count() == 0
        assert db_session.query(Conversation).filter_by(section_id=s.id).count() == 0

        # LLMCallLog 记账（action=revise，origin 进 context_meta）
        from app.models import LLMCallLog
        logs = db_session.query(LLMCallLog).filter_by(action="revise", project_id=p.id).all()
        assert len(logs) == 1
        cm = logs[0].context_meta or {}
        assert cm.get("origin") == "review"
