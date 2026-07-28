# apps/api/tests/test_sections_api.py
"""sections API 端点测试（选区重写 diff 端点端到端）。"""
import pytest


def _make_logged_in_section(client, registered_user, db_session):
    """登录 + 建项目 + 取第一个 section。

    照搬 test_ai.py 的脚手架模式：必须 client.post 登录注入 cookie，
    否则受 get_current_user 保护的端点会返回 401。
    """
    from sqlalchemy import select

    from app.models import User, UserLLMConfig
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from app.services.seed_service import ensure_default_template
    from app.core.security import encrypt_value

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    # 配 LLM 配置（使脚手架与 test_ai.py 一致，便于后续混合用）
    db_session.add(UserLLMConfig(
        user_id=user.id, name="test", provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model",
    ))
    db_session.commit()
    p = create_project(db_session, user=user, title="rewrite-diff 测试项目")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    # 登录注入 cookie —— plan 原始脚手架漏了这一步，未登录会 401
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    return sections[0]


def test_rewrite_diff_endpoint_basic(client, registered_user, db_session):
    """POST /sections/{id}/rewrite-diff → 返回 DiffResponse（含 hunks + ai_full）。"""
    section = _make_logged_in_section(client, registered_user, db_session)
    # 给章节写内容
    from app.ai.markdown_to_tiptap import markdown_to_tiptap
    section.content = markdown_to_tiptap("本发明涉及一种机械装置")
    db_session.commit()

    res = client.post(
        f"/api/v1/sections/{section.id}/rewrite-diff",
        json={"selected_text": "涉及", "ai_text": "归属于"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "hunks" in data
    assert len(data["hunks"]) >= 1
    assert data["hunks"][0]["type"] == "replace"
    # ai_full：选区首次出现被 ai_text 替换后的整章文本。
    # apply-diff 时前端必须把它原样作为 ai_text 回传，否则后端按
    # (original, ai_text) 重算的 hunks 与计算时生成的 hunk id 不一致 → 数据损坏。
    assert data["ai_full"] == "本发明归属于一种机械装置"


def test_rewrite_diff_endpoint_not_found_returns_422(client, registered_user, db_session):
    """selected_text 不在章节 → 422 ValidationError（AppError.status_code=422）。"""
    section = _make_logged_in_section(client, registered_user, db_session)
    from app.ai.markdown_to_tiptap import markdown_to_tiptap
    section.content = markdown_to_tiptap("本发明涉及一种机械装置")
    db_session.commit()

    res = client.post(
        f"/api/v1/sections/{section.id}/rewrite-diff",
        json={"selected_text": "不存在的文字", "ai_text": "新内容"},
    )
    assert res.status_code == 422


def test_rewrite_diff_endpoint_unauthorized_returns_404(app_obj, registered_user, db_session):
    """未登录访问 → 401（get_current_user 拦截），验证端点受保护。

    用全新 TestClient（不共享前两个测试的登录 cookie），聚焦未鉴权场景。
    """
    from fastapi.testclient import TestClient
    from app.ai.markdown_to_tiptap import markdown_to_tiptap

    # 先用已登录 client 建好 section（写内容）
    with TestClient(app_obj) as logged_in:
        section = _make_logged_in_section(logged_in, registered_user, db_session)
        section.content = markdown_to_tiptap("本发明涉及一种机械装置")
        db_session.commit()
        section_id = section.id

    # 全新 TestClient：无登录 cookie → get_current_user 拦截 → 401
    with TestClient(app_obj) as anon:
        res = anon.post(
            f"/api/v1/sections/{section_id}/rewrite-diff",
            json={"selected_text": "涉及", "ai_text": "归属于"},
        )
    assert res.status_code == 401
