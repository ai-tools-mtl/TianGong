"""figure_service 测试。

mock LLM（get_llm）+ mock 渲染（drawio_client.render），验证：
- generate_figure 正常落库（Figure + Attachment）
- 渲染失败不落库（原子性）
- regenerate 原地覆写同一 Attachment（正文引用不失效）
- delete 清理 Figure + Attachment + storage；正文引用防护（409 + force）
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
    assert fig.style == "patent-bw"  # 默认 style
    assert "<mxfile" in fig.drawio_xml
    assert fig.attachment_id is not None
    # Attachment 落库
    att = db_session.get(Attachment, fig.attachment_id)
    assert att is not None
    assert att.mime_type == "image/png"


def test_generate_figure_render_uses_preset_params(db_session, registered_user):
    """render 调用收到预设的 scale/border 参数（patent-bw: scale=3, border=20）。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG) as mock_render:
        figure_service.generate_figure(
            db_session, storage=MagicMock(), user_id=user.id,
            section_id=str(drawings.id), prompt="测试", diagram_type=None, chat_source=None,
            style="patent-bw",
        )
    _, kwargs = mock_render.call_args
    assert kwargs["scale"] == 3
    assert kwargs["border"] == 20


def test_generate_figure_style_recorded(db_session, registered_user):
    """传 style=clean-color 后 Figure.style 落库为 clean-color。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.generate_figure(
            db_session, storage=MagicMock(), user_id=user.id,
            section_id=str(drawings.id), prompt="彩色测试", diagram_type=None, chat_source=None,
            style="clean-color",
        )
    assert fig.style == "clean-color"


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


def test_regenerate_overwrites_same_attachment(db_session, registered_user):
    """regenerate 原地覆写：attachment_id 不变，storage 同一对象写入新 PNG。

    正文图 src 含 attachment id——id 不变则已插入正文的图自动同步为新图，
    不再出现「重生成后正文图片失效」（2026-08-25 引用完整性）。
    """
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
    old_key = db_session.get(Attachment, old_att_id).storage_path
    fake_storage.reset_mock()
    new_png = b"\x89PNG\r\n\x1a\n" + b"\x01" * 300  # 与原 PNG 不同的字节

    # regenerate 用新 prompt
    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=new_png):
        fig = figure_service.regenerate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            figure_id=str(fig.id), prompt="改后的图", chat_source=None,
        )

    assert fig.prompt == "改后的图"
    assert fig.attachment_id == old_att_id  # 同一 Attachment（正文引用不失效）
    att = db_session.get(Attachment, old_att_id)
    assert att is not None
    assert att.size == len(new_png)  # 元数据随覆写更新
    # storage：覆写同一对象，不建新对象、不删旧对象
    fake_storage.put.assert_called_once_with("personal", old_key, new_png, "image/png")
    fake_storage.delete.assert_not_called()


def test_regenerate_rejects_non_png_overwrite(db_session, registered_user):
    """覆写前拦截非 PNG 字节：render 异常返回（HTTP 200 + 空/错误页）不得覆盖正文在用的旧图。

    generate 路径的 _store_png 一直有魔数校验，覆写路径此前只有大小检查——
    坏字节一旦 put 进旧对象，正文原有图不可恢复（2026-08-26 补齐对称防护）。
    """
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    fake_storage = MagicMock()

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.generate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            section_id=str(drawings.id), prompt="原图", diagram_type=None, chat_source=None,
        )
    old_size = db_session.get(Attachment, fig.attachment_id).size
    fake_storage.reset_mock()

    # 模拟渲染链路异常：drawio 服务 200 但返回空字节（非 PNG）
    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=b""), \
         pytest.raises(ValidationError):
        figure_service.regenerate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            figure_id=str(fig.id), prompt=None, chat_source=None,
        )

    # 旧对象未被覆写，元数据不变
    fake_storage.put.assert_not_called()
    assert db_session.get(Attachment, fig.attachment_id).size == old_size


def test_regenerate_creates_attachment_when_missing(db_session, registered_user):
    """历史遗留（Figure 无 Attachment）时 regenerate 走新建附件。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    fake_storage = MagicMock()

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.generate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            section_id=str(drawings.id), prompt="原图", diagram_type=None, chat_source=None,
        )
    # 人为清掉 Attachment 关联，模拟历史脏数据
    fig.attachment_id = None
    db_session.commit()

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.regenerate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            figure_id=str(fig.id), prompt=None, chat_source=None,
        )

    assert fig.attachment_id is not None
    assert db_session.get(Attachment, fig.attachment_id) is not None


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


def _insert_body_reference(db_session, section, attachment_id) -> None:
    """把含 attachment id 的图片节点写进章节正文（模拟「插入文档」后的落库状态）。"""
    src = f"/api/v1/projects/{section.project_id}/attachments/{attachment_id}/file"
    section.content = {
        "type": "doc",
        "content": [{"type": "image", "attrs": {"src": src, "alt": "附图"}}],
    }
    db_session.commit()


def test_find_body_references_scans_sections(db_session, registered_user):
    """服务端引用探测：content 序列化后含 attachment id 的章节被命中。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    fake_storage = MagicMock()

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.generate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            section_id=str(drawings.id), prompt="引用探测", diagram_type=None, chat_source=None,
        )

    # 无引用
    assert figure_service.find_body_references(
        db_session, project_id=drawings.project_id, attachment_id=fig.attachment_id
    ) == []
    # attachment_id 为 None（Figure 无附件）直接空
    assert figure_service.find_body_references(
        db_session, project_id=drawings.project_id, attachment_id=None
    ) == []

    _insert_body_reference(db_session, drawings, fig.attachment_id)
    refs = figure_service.find_body_references(
        db_session, project_id=drawings.project_id, attachment_id=fig.attachment_id
    )
    assert len(refs) == 1
    assert refs[0]["section_id"] == str(drawings.id)
    assert refs[0]["section_title"] == drawings.title


def test_delete_figure_referenced_conflicts_then_force(db_session, registered_user):
    """正文引用防护：有引用默认 409（消息含章节名+图号），force=True 才真正删除。"""
    import pytest

    from app.core.exceptions import ConflictError
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    fake_storage = MagicMock()

    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        fig = figure_service.generate_figure(
            db_session, storage=fake_storage, user_id=user.id,
            section_id=str(drawings.id), prompt="防删测试", diagram_type=None, chat_source=None,
        )
    _insert_body_reference(db_session, drawings, fig.attachment_id)

    # 默认：409 + 消息含引用章节标题与图号（图号系统 V1）
    with pytest.raises(ConflictError, match=drawings.title):
        figure_service.delete_figure(
            db_session, storage=fake_storage, user_id=user.id, figure_id=str(fig.id),
        )
    assert db_session.get(Figure, fig.id) is not None  # 未删

    # force：放行删除
    figure_service.delete_figure(
        db_session, storage=fake_storage, user_id=user.id, figure_id=str(fig.id), force=True,
    )
    assert db_session.get(Figure, fig.id) is None


# ── 图号系统 V1（2026-08-26：项目内连续编号 + 删除重排）──


def _gen(db_session, storage, user, drawings, prompt: str) -> Figure:
    from app.services import figure_service
    with patch("app.ai.llm_client.get_llm", return_value=_mock_llm_invoke()), \
         patch("app.services.figure_service.drawio_client.render", return_value=_FAKE_PNG):
        return figure_service.generate_figure(
            db_session, storage=storage, user_id=user.id,
            section_id=str(drawings.id), prompt=prompt, diagram_type=None, chat_source=None,
        )


def test_generate_assigns_sequential_numbers(db_session, registered_user):
    """图号分配：项目内按生成顺序 1、2、3 连续；API 出参带 number。"""
    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    fake_storage = MagicMock()

    f1 = _gen(db_session, fake_storage, user, drawings, "第一张")
    f2 = _gen(db_session, fake_storage, user, drawings, "第二张")
    f3 = _gen(db_session, fake_storage, user, drawings, "第三张")
    assert (f1.number, f2.number, f3.number) == (1, 2, 3)
    assert figure_service._to_figure_out(f2, project_id=str(f2.project_id))["number"] == 2


def test_delete_renumbers_no_gaps(db_session, registered_user):
    """删除重排：删中间图后后续图号前移，保持 1..n 无空洞；删空后再生成从 1 起。"""
    from sqlalchemy import select as sa_select

    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    fake_storage = MagicMock()

    f1 = _gen(db_session, fake_storage, user, drawings, "一")
    f2 = _gen(db_session, fake_storage, user, drawings, "二")
    f3 = _gen(db_session, fake_storage, user, drawings, "三")

    # 删除图2（无正文引用，无需 force）
    figure_service.delete_figure(
        db_session, storage=fake_storage, user_id=user.id, figure_id=str(f2.id),
    )
    nums = list(db_session.scalars(
        sa_select(Figure.number).where(Figure.project_id == f1.project_id).order_by(Figure.number)
    ))
    assert nums == [1, 2]  # 原图1 不动，原图3 前移为 2

    # 删空后再生成：图号从 1 重新开始
    figure_service.delete_figure(db_session, storage=fake_storage, user_id=user.id, figure_id=str(f1.id))
    figure_service.delete_figure(db_session, storage=fake_storage, user_id=user.id, figure_id=str(f3.id))
    f4 = _gen(db_session, fake_storage, user, drawings, "新一轮")
    assert f4.number == 1


def test_delete_renumber_boundary_first_and_last(db_session, registered_user):
    """连续删除幂等：删首/删尾后编号仍为 1..n（两阶段重排的边界）。"""
    from sqlalchemy import select as sa_select

    from app.services import figure_service

    user, drawings = _setup_user_and_project(db_session, registered_user)
    fake_storage = MagicMock()
    figs = [_gen(db_session, fake_storage, user, drawings, f"图{i}") for i in range(1, 4)]

    def _nums():
        return list(db_session.scalars(
            sa_select(Figure.number).where(Figure.project_id == figs[0].project_id)
            .order_by(Figure.number)
        ))

    # 删首
    figure_service.delete_figure(db_session, storage=fake_storage, user_id=user.id, figure_id=str(figs[0].id))
    assert _nums() == [1, 2]
    # 删尾
    figure_service.delete_figure(db_session, storage=fake_storage, user_id=user.id, figure_id=str(figs[2].id))
    assert _nums() == [1]
