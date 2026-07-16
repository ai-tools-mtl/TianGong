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
        user_id=user.id, provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model", embedding_model="test-embed", is_active=True,
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
