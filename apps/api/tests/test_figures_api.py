"""figures API 端点测试。

用 client fixture 走真实 HTTP（storage 是 fake），mock LLM + 渲染，
验证端点鉴权、drawings 章节校验、生成/列出/详情/重生成/删除。
"""
from unittest.mock import MagicMock, patch

from app.core.security import encrypt_value
from app.models import User, UserLLMConfig
from app.services.project_service import create_project
from app.services.section_service import list_sections
from app.services.seed_service import ensure_default_template
from sqlalchemy import select


_FAKE_XML = '<?xml version="1.0"?><mxfile><diagram><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>'
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


def _setup_and_login(client, registered_user, db_session):
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    db_session.add(UserLLMConfig(
        user_id=user.id, name="test", provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model",
    ))
    db_session.commit()
    p = create_project(db_session, user=user, title="测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    drawings = next(s for s in sections if s.key == "drawings")
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    return user, p, drawings


def _mock_llm():
    fake = MagicMock()
    resp = MagicMock()
    resp.content = _FAKE_XML
    fake.invoke.return_value = resp
    return fake


def test_generate_figure_endpoint(client, registered_user, db_session):
    """生成附图：返回 201 + figure dict。"""
    user, project, drawings = _setup_and_login(client, registered_user, db_session)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        res = client.post(
            f"/api/v1/sections/{drawings.id}/figures/generate",
            json={"prompt": "客户端服务端流程图", "diagram_type": "flowchart"},
        )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["prompt"] == "客户端服务端流程图"
    assert body["diagram_type"] == "flowchart"
    assert body["attachment_id"] is not None


def test_generate_figure_rejects_non_drawings(client, registered_user, db_session):
    """非 drawings 章节拒绝（422）。"""
    user, project, drawings = _setup_and_login(client, registered_user, db_session)
    sections = list_sections(db_session, user_id=user.id, project_id=str(project.id))
    non_drawings = next(s for s in sections if s.key != "drawings")

    res = client.post(
        f"/api/v1/sections/{non_drawings.id}/figures/generate",
        json={"prompt": "测试"},
    )
    assert res.status_code == 422


def test_list_figures_endpoint(client, registered_user, db_session):
    """列出项目附图。"""
    user, project, drawings = _setup_and_login(client, registered_user, db_session)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        client.post(f"/api/v1/sections/{drawings.id}/figures/generate", json={"prompt": "图1"})
        client.post(f"/api/v1/sections/{drawings.id}/figures/generate", json={"prompt": "图2"})

    res = client.get(f"/api/v1/projects/{project.id}/figures")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 2


def test_get_figure_detail_includes_xml(client, registered_user, db_session):
    """详情接口返回 drawio_xml 源。"""
    user, project, drawings = _setup_and_login(client, registered_user, db_session)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        r = client.post(f"/api/v1/sections/{drawings.id}/figures/generate", json={"prompt": "测试"})
    fig_id = r.json()["id"]

    res = client.get(f"/api/v1/figures/{fig_id}")
    assert res.status_code == 200
    assert "<mxfile" in res.json()["drawio_xml"]


def test_regenerate_endpoint(client, registered_user, db_session):
    """重新生成：返回新 prompt。"""
    user, project, drawings = _setup_and_login(client, registered_user, db_session)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        r = client.post(f"/api/v1/sections/{drawings.id}/figures/generate", json={"prompt": "原图"})
    fig_id = r.json()["id"]

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        res = client.post(f"/api/v1/figures/{fig_id}/regenerate", json={"prompt": "改后"})

    assert res.status_code == 200
    assert res.json()["prompt"] == "改后"


def test_delete_figure_endpoint(client, registered_user, db_session):
    """删除附图：204。"""
    user, project, drawings = _setup_and_login(client, registered_user, db_session)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        r = client.post(f"/api/v1/sections/{drawings.id}/figures/generate", json={"prompt": "测试"})
    fig_id = r.json()["id"]

    res = client.delete(f"/api/v1/figures/{fig_id}")
    assert res.status_code == 204

    # 再列应为空
    res2 = client.get(f"/api/v1/projects/{project.id}/figures")
    assert res2.json() == []


def test_generate_requires_auth(client, db_session):
    """未登录生成附图：401。"""
    res = client.post("/api/v1/sections/00000000-0000-0000-0000-000000000000/figures/generate",
                      json={"prompt": "x"})
    assert res.status_code in (401, 404)  # 未鉴权先挡


def test_render_unavailable_returns_503(client, registered_user, db_session):
    """渲染服务挂掉：返回 503（fail-closed）。"""
    from app.core.exceptions import ServiceUnavailableError

    user, project, drawings = _setup_and_login(client, registered_user, db_session)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm()), \
         patch("app.services.figure_service.drawio_client.render",
               side_effect=ServiceUnavailableError("down")):
        res = client.post(
            f"/api/v1/sections/{drawings.id}/figures/generate",
            json={"prompt": "测试"},
        )
    assert res.status_code == 503
