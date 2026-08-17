# apps/api/tests/test_novelty.py
"""新颖性评估测试：上下文加载（409 分支/章节选取/截断）+ 消息构造 + SSE 端点 + 持久化。"""
import uuid

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import encrypt_value, hash_password
from app.models import Project, Section, User, UserLLMConfig
from app.services.novelty_service import (
    _extract_text,
    build_assessment_messages,
    load_assessment_context,
)


@pytest.fixture
def user_with_config(db_session):
    u = User(
        username=f"nu-{uuid.uuid4().hex[:6]}",
        email=f"nu-{uuid.uuid4().hex[:6]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="评估用户",
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


def _mk_project(db_session, user, *, prior_art=None):
    p = Project(user_id=user.id, title="评估项目", prior_art_refs=prior_art)
    db_session.add(p)
    db_session.flush()
    return p


def _mk_section(db_session, project, key, title, paragraphs):
    content = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": t}]} for t in paragraphs
    ]}
    s = Section(project_id=project.id, template_section_id=f"ts-{key}", order=1,
                key=key, title=title, status="confirmed", content=content)
    db_session.add(s)
    db_session.flush()
    return s


# ── load_assessment_context ───────────────────────────────────────────────────


def test_context_requires_prior_art(db_session, user_with_config):
    p = _mk_project(db_session, user_with_config, prior_art=None)
    with pytest.raises(ConflictError):
        load_assessment_context(
            db_session, user_id=user_with_config.id, project_id=str(p.id))


def test_context_requires_section_content(db_session, user_with_config):
    p = _mk_project(db_session, user_with_config, prior_art={
        "query": "q", "results": [{"patent_number": "CN1"}]})
    with pytest.raises(ConflictError):
        load_assessment_context(
            db_session, user_id=user_with_config.id, project_id=str(p.id))


def test_context_owner_check_404(db_session, user_with_config):
    p = _mk_project(db_session, user_with_config, prior_art={"query": "q", "results": []})
    other = uuid.uuid4()
    with pytest.raises(NotFoundError):
        load_assessment_context(db_session, user_id=other, project_id=str(p.id))


def test_context_picks_core_sections(db_session, user_with_config):
    p = _mk_project(db_session, user_with_config, prior_art={
        "query": "q",
        "results": [{"patent_number": "CN1", "title": "t", "abstract": "a",
                     "legal_status": "有效"}],
    })
    _mk_section(db_session, p, "background", "背景技术", ["现有技术是A"])
    _mk_section(db_session, p, "solution", "技术方案", ["本方案采用B"])
    db_session.commit()
    _, results, text = load_assessment_context(
        db_session, user_id=user_with_config.id, project_id=str(p.id))
    assert results[0]["legal_status"] == "有效"
    assert "现有技术是A" in text
    assert "本方案采用B" in text


def test_extract_text_ignores_non_text_nodes():
    content = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "hello"}]},
        {"type": "image", "attrs": {"src": "x"}},
        {"type": "paragraph", "content": [{"type": "text", "text": "world"}]},
    ]}
    assert _extract_text(content) == "hello\nworld"


# ── build_assessment_messages ─────────────────────────────────────────────────


def test_build_messages_contains_refs_and_structure():
    results = [{
        "patent_number": "CN110123456A", "title": "图像识别",
        "applicant": "XX公司", "publication_date": "2019-08-09",
        "legal_status": "有效", "abstract": "卷积神经网络",
    }]
    msgs = build_assessment_messages(results, "本方案采用B")
    user_content = msgs[1].content
    assert "CN110123456A" in user_content
    assert "法律状态：有效" in user_content
    assert "本方案采用B" in user_content
    assert "总体新颖性风险" in user_content
    assert "差异化撰写建议" in user_content


# ── SSE 端点 ──────────────────────────────────────────────────────────────────


def _login(client, user):
    client.post("/api/v1/auth/login", json={
        "username": user.username, "password": "Pass1234!"})


def test_assess_endpoint_streams_and_persists(
        client, db_session, user_with_config, monkeypatch):
    p = _mk_project(db_session, user_with_config, prior_art={
        "query": "图像识别",
        "results": [{"patent_number": "CN1", "title": "t", "applicant": "a",
                     "abstract": "abs", "url": "u", "publication_date": "d",
                     "legal_status": "有效", "relevance": 0.9}],
    })
    _mk_section(db_session, p, "solution", "技术方案", ["本方案采用特征X"])
    db_session.commit()
    _login(client, user_with_config)

    async def _fake_astream(messages, *, llm_config, usage_sink=None):
        for t in ["总体风险：低", "。区别点：特征X"]:
            yield t

    # astream_llm 在端点内延迟 import，patch 源模块（调用方经 from-import 拿到 patched 版本）
    monkeypatch.setattr("app.ai.llm_client.astream_llm", _fake_astream)

    res = client.post(f"/api/v1/projects/{p.id}/patents/assess")
    assert res.status_code == 200
    body = res.text
    assert "event: token" in body and "总体风险：低" in body
    assert "event: done" in body

    db_session.expire_all()
    saved = db_session.get(Project, p.id).prior_art_refs
    assert saved["assessment"]["content"] == "总体风险：低。区别点：特征X"
    assert saved["query"] == "图像识别"  # 检索快照保留

    # LLMCallLog 记账
    from app.models import LLMCallLog
    assert db_session.query(LLMCallLog).filter_by(
        action="novelty_assess", project_id=p.id).count() == 1


def test_assess_without_prior_art_409(client, db_session, user_with_config):
    p = _mk_project(db_session, user_with_config, prior_art=None)
    db_session.commit()
    _login(client, user_with_config)
    res = client.post(f"/api/v1/projects/{p.id}/patents/assess")
    assert res.status_code == 409
    assert "先执行专利检索" in res.json()["message"]


# ── T2 批4：建议结构化（parse_suggestions + persist 集成）───────────────────

def _mock_parse_llm(monkeypatch, content: str):
    """mock novelty_service 的 get_llm：invoke 返回固定文本。"""
    from unittest.mock import MagicMock
    from app.services import novelty_service
    mock_llm = MagicMock()
    resp = MagicMock()
    resp.content = content
    mock_llm.invoke.return_value = resp
    monkeypatch.setattr(novelty_service, "get_llm", lambda cfg: mock_llm)
    return mock_llm


class TestParseSuggestions:
    def test_parses_and_filters_whitelist(self, db_session, user_with_config, monkeypatch):
        """正常解析 + section_key 白名单过滤（非法 key 丢弃，spec §3.4）。"""
        from app.services.novelty_service import parse_suggestions
        _mock_parse_llm(monkeypatch, '{"suggestions": ['
            '{"section_key": "solution", "text": "突出特征X的连接方式"},'
            '{"section_key": "claims", "text": "非法key应被丢弃"},'
            '{"section_key": "problem", "text": "对准区别技术问题"}]}')
        got = parse_suggestions(db_session, user_id=user_with_config.id, content="报告全文")
        assert got is not None and len(got) == 2
        assert {s["section_key"] for s in got} == {"solution", "problem"}
        assert got[0]["text"]

    def test_prompt_targets_third_section_only(self):
        """parse prompt 明确只解析「## 三、差异化撰写建议」段（v1.2 补充）。"""
        from app.services.novelty_service import _build_parse_prompt
        prompt = _build_parse_prompt("报告")
        assert "三、差异化撰写建议" in prompt
        assert "suggestions" in prompt

    def test_parse_failure_returns_none(self, db_session, user_with_config, monkeypatch):
        """LLM 输出解析失败 → None（fail-open：assessment 仅存 content）。"""
        from app.services.novelty_service import parse_suggestions
        _mock_parse_llm(monkeypatch, "不是JSON")
        assert parse_suggestions(db_session, user_id=user_with_config.id, content="x") is None

    def test_persist_includes_suggestions(self, db_session, user_with_config):
        """persist_assessment 传 suggestions → assessment dict 含该键；None → 不含。"""
        from app.services.novelty_service import persist_assessment
        p = _mk_project(db_session, user_with_config)
        persist_assessment(db_session, p, content="报告A", model="m",
                           suggestions=[{"section_key": "solution", "text": "建议"}])
        db_session.expire_all()
        assert db_session.get(Project, p.id).prior_art_refs["assessment"]["suggestions"] == [
            {"section_key": "solution", "text": "建议"}]

        p2 = _mk_project(db_session, user_with_config)
        persist_assessment(db_session, p2, content="报告B", model="m")
        db_session.expire_all()
        assert "suggestions" not in db_session.get(Project, p2.id).prior_art_refs["assessment"]


def test_assess_endpoint_persists_suggestions(
        client, db_session, user_with_config, monkeypatch):
    """端点集成：主报告流完成 → done 前同步解析 → suggestions 随 assessment 落库。"""
    p = _mk_project(db_session, user_with_config, prior_art={
        "query": "图像识别",
        "results": [{"patent_number": "CN1", "title": "t", "applicant": "a",
                     "abstract": "abs", "url": "u", "publication_date": "d",
                     "legal_status": "有效", "relevance": 0.9}],
    })
    _mk_section(db_session, p, "solution", "技术方案", ["本方案采用特征X"])
    db_session.commit()
    _login(client, user_with_config)

    async def _fake_astream(messages, *, llm_config, usage_sink=None):
        yield "## 三、差异化撰写建议\n突出特征X的连接方式。"

    monkeypatch.setattr("app.ai.llm_client.astream_llm", _fake_astream)
    from app.services import novelty_service
    _mock_parse_llm(monkeypatch, '{"suggestions": [{"section_key": "solution", "text": "突出特征X的连接方式"}]}')

    res = client.post(f"/api/v1/projects/{p.id}/patents/assess")
    assert res.status_code == 200
    assert "event: done" in res.text

    db_session.expire_all()
    saved = db_session.get(Project, p.id).prior_art_refs["assessment"]
    assert saved["suggestions"][0]["section_key"] == "solution"
