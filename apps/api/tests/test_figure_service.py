"""figure_service 测试。

mock LLM（get_llm）+ mock 渲染（drawio_client.render），验证：
- generate_figure 正常落库（Figure + Attachment）
- 渲染失败不落库（原子性）
- regenerate 替换 PNG + 删旧
- delete 清理 Figure + Attachment + storage
- 非 drawings 章节拒绝
"""
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.models import Attachment, Figure
from app.services.seed_service import ensure_default_template
from app.services.project_service import create_project
from app.services.section_service import list_sections
from sqlalchemy import select

from app.core.security import encrypt_value
from app.models import User, UserLLMConfig


# 最小合法 drawio XML（LLM 的模拟返回）
_FAKE_XML = '<?xml version="1.0"?><mxfile><diagram><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>'
# 最小合法 PNG 字节（通过 attachment_service 魔数校验）
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


def _setup_user_and_project(db_session, registered_user):
    """建模板 + 用户 LLM 配置 + 项目，返回 (user, drawings_section)。"""
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
    return user, drawings


def _mock_llm_invoke():
    """构造一个假 ChatOpenAI，invoke 返回含 _FAKE_XML 的响应。"""
    fake_llm = MagicMock()
    fake_resp = MagicMock()
    fake_resp.content = _FAKE_XML
    fake_llm.invoke.return_value = fake_resp
    return fake_llm


def test_generate_figure_success(db_session, registered_user):
    """生成成功：Figure + Attachment 落库，storage 写入 PNG。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.generate_figure(
            db_session, storage=MagicMock(), user_id=user.id,
            section_id=str(drawings.id), prompt="画一个客户端服务端流程图",
            diagram_type="flowchart", chat_source=None,
        )

    assert fig.prompt == "画一个客户端服务端流程图"
    assert fig.diagram_type == "flowchart"
    assert "<mxfile" in fig.drawio_xml
    assert fig.attachment_id is not None
    # Attachment 落库
    att = db_session.get(Attachment, fig.attachment_id)
    assert att is not None
    assert att.mime_type == "image/png"


def test_generate_figure_render_failure_no_db_record(db_session, registered_user):
    """渲染失败（ServiceUnavailableError）时不落库（原子性）。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render",
               side_effect=ServiceUnavailableError("down")):
        with pytest.raises(ServiceUnavailableError):
            figure_service.generate_figure(
                db_session, storage=MagicMock(), user_id=user.id,
                section_id=str(drawings.id), prompt="测试",
                diagram_type=None, chat_source=None,
            )

    # 无 Figure 残留
    assert db_session.scalar(select(Figure)) is None
    # 无 Attachment 残留
    assert db_session.scalar(select(Attachment)) is None


def test_generate_figure_rejects_non_drawings(db_session, registered_user):
    """非 drawings 章节拒绝生成。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    # 取一个非 drawings 章节（name 是 order=0）
    sections = list_sections(db_session, user_id=user.id, project_id=str(drawings.project_id))
    non_drawings = next(s for s in sections if s.key != "drawings")

    with pytest.raises(ValidationError):
        figure_service.generate_figure(
            db_session, storage=MagicMock(), user_id=user.id,
            section_id=str(non_drawings.id), prompt="测试",
            diagram_type=None, chat_source=None,
        )


def test_generate_figure_invalid_xml_rejected(db_session, registered_user):
    """LLM 返回非 XML（无 <mxfile）时拒绝。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)

    fake_llm = MagicMock()
    fake_resp = MagicMock()
    fake_resp.content = "抱歉，我无法画图"  # 非 XML
    fake_llm.invoke.return_value = fake_resp

    with patch("app.ai.llm_client.get_llm", return_value=fake_llm):
        with pytest.raises(ValidationError):
            figure_service.generate_figure(
                db_session, storage=MagicMock(), user_id=user.id,
                section_id=str(drawings.id), prompt="测试",
                diagram_type=None, chat_source=None,
            )


def test_regenerate_replaces_attachment(db_session, registered_user):
    """regenerate 替换 PNG：旧 Attachment 删除，新 Attachment 建立并关联。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    fake_storage = MagicMock()

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.generate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            section_id=str(drawings.id), prompt="原图", diagram_type=None, chat_source=None,
        )
    old_att_id = fig.attachment_id

    # regenerate 用新 prompt
    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.regenerate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            figure_id=str(fig.id), prompt="改后的图", chat_source=None,
        )

    assert fig.prompt == "改后的图"
    assert fig.attachment_id != old_att_id  # 换了新 Attachment
    assert db_session.get(Attachment, old_att_id) is None  # 旧 Attachment 已删


def test_delete_figure_removes_attachment_and_storage(db_session, registered_user):
    """delete 清理 Figure + Attachment，并删 storage 对象。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    fake_storage = MagicMock()

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.generate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            section_id=str(drawings.id), prompt="测试", diagram_type=None, chat_source=None,
        )
    fig_id = fig.id
    att_id = fig.attachment_id

    figure_service.delete_figure(db_session, storage=fake_storage, user_id=user.id, figure_id=str(fig_id))

    assert db_session.get(Figure, fig_id) is None
    assert db_session.get(Attachment, att_id) is None
    fake_storage.delete.assert_called()  # 删了 storage 对象
