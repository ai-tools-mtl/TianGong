"""图注润色端点测试。"""
from app.core.security import encrypt_value
from app.models import User, UserLLMConfig
from app.services.seed_service import ensure_default_template
from app.services.project_service import create_project
from app.services.section_service import list_sections
from sqlalchemy import select


def _setup_and_login(client, registered_user, db_session):
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    # 阶段 0 strict：端点要求生效 LLM 配置，否则发 no_llm_config 错误
    db_session.add(UserLLMConfig(
        user_id=user.id, name="test", provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model",
    ))
    db_session.commit()
    p = create_project(db_session, user=user, title="测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={"username": registered_user["username"], "password": registered_user["password"]})
    return sections


def test_caption_figures_endpoint(client, registered_user, db_session, monkeypatch):
    sections = _setup_and_login(client, registered_user, db_session)
    drawings = next(s for s in sections if s.key == "drawings")

    async def fake_astream(messages, **kwargs):
        yield "图 1 是本发明装置的整体结构示意图。"

    monkeypatch.setattr("app.api.ai.astream_llm", fake_astream)
    res = client.post(f"/api/v1/sections/{drawings.id}/caption-figures", json={"descriptions": ["图1是装置结构图"]})
    assert res.status_code == 200
    assert "event: token" in res.text
    assert "图 1" in res.text


def test_caption_figures_rejects_non_drawings(client, registered_user, db_session):
    sections = _setup_and_login(client, registered_user, db_session)
    # first section is "name", not drawings
    res = client.post(f"/api/v1/sections/{sections[0].id}/caption-figures", json={"descriptions": ["测试"]})
    assert res.status_code == 422


# ── vision：看图说话（attachment_ids + vision model → 多模态）──

def _make_attachment(db, project_id, *, storage_path="attachments/test/v.png", mime="image/png"):
    from app.core.storage import get_storage
    from app.models import Attachment

    att = Attachment(
        project_id=project_id, filename="x.png",
        storage_path=storage_path, mime_type=mime, size=8,
    )
    db.add(att)
    db.commit()
    get_storage().put("personal", storage_path, b"\x89PNG\r\n\x1a\n", mime)
    return att


def _set_vision_model(db):
    from app.models import UserLLMConfig

    cfg = db.scalar(select(UserLLMConfig).where(UserLLMConfig.model == "test-model"))
    cfg.model = "gpt-4o-mini"
    db.commit()


def _capture_astream(monkeypatch):
    """mock astream_llm，捕获收到的 messages 供断言。"""
    captured: dict = {}

    async def fake_astream(messages, **kwargs):
        captured["messages"] = messages
        yield "图注"

    monkeypatch.setattr("app.api.ai.astream_llm", fake_astream)
    return captured


def test_caption_figures_with_vision(client, registered_user, db_session, monkeypatch):
    """vision model + attachment_ids → 多模态 messages（HumanMessage.content 是 list 含 image_url）。"""
    sections = _setup_and_login(client, registered_user, db_session)
    drawings = next(s for s in sections if s.key == "drawings")
    _set_vision_model(db_session)
    att = _make_attachment(db_session, drawings.project_id)

    captured = _capture_astream(monkeypatch)
    res = client.post(
        f"/api/v1/sections/{drawings.id}/caption-figures",
        json={"attachment_ids": [str(att.id)]},
    )
    assert res.status_code == 200, res.text
    human = captured["messages"][1]
    assert isinstance(human.content, list)  # 多模态
    assert any(c.get("type") == "image_url" for c in human.content)


def test_caption_figures_non_vision_model_fallback(client, registered_user, db_session, monkeypatch):
    """非 vision model（test-model）+ attachment_ids → 纯文字降级（兼容老行为）。"""
    sections = _setup_and_login(client, registered_user, db_session)
    drawings = next(s for s in sections if s.key == "drawings")
    att = _make_attachment(db_session, drawings.project_id, storage_path="attachments/test/v2.png")

    captured = _capture_astream(monkeypatch)
    res = client.post(
        f"/api/v1/sections/{drawings.id}/caption-figures",
        json={"attachment_ids": [str(att.id)], "descriptions": ["装置图"]},
    )
    assert res.status_code == 200
    human = captured["messages"][1]
    assert isinstance(human.content, str)  # 纯文字降级


def test_caption_figures_skips_cross_project_attachment(client, registered_user, db_session, monkeypatch):
    """跨项目 attachment 被跳过（不泄露、不报错），走文字降级。"""
    sections = _setup_and_login(client, registered_user, db_session)
    drawings = next(s for s in sections if s.key == "drawings")
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    other_p = create_project(db_session, user=user, title="他人项目")
    other_att = _make_attachment(db_session, other_p.id, storage_path="attachments/test/other.png")

    captured = _capture_astream(monkeypatch)
    res = client.post(
        f"/api/v1/sections/{drawings.id}/caption-figures",
        json={"attachment_ids": [str(other_att.id)], "descriptions": ["装置图"]},
    )
    assert res.status_code == 200
    human = captured["messages"][1]
    assert isinstance(human.content, str)  # 跨项目图被跳过 → 文字降级


def test_caption_figures_invalid_attachment_id_skipped(client, registered_user, db_session, monkeypatch):
    """非法 UUID 的 attachment_id 被跳过，不报错。"""
    sections = _setup_and_login(client, registered_user, db_session)
    drawings = next(s for s in sections if s.key == "drawings")
    _capture_astream(monkeypatch)
    res = client.post(
        f"/api/v1/sections/{drawings.id}/caption-figures",
        json={"attachment_ids": ["not-a-uuid"], "descriptions": ["装置图"]},
    )
    assert res.status_code == 200


def test_caption_figures_requires_input(client, registered_user, db_session):
    """descriptions 和 attachment_ids 都空 → 422。"""
    sections = _setup_and_login(client, registered_user, db_session)
    drawings = next(s for s in sections if s.key == "drawings")
    res = client.post(f"/api/v1/sections/{drawings.id}/caption-figures", json={})
    assert res.status_code == 422
