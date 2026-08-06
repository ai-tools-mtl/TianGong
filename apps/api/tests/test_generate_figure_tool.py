"""generate_figure agent 工具测试。

验证工具装配条件 + 调用行为（mock figure_service，隔离 LLM/渲染）：
- section 非 None（章节场景）且 scope=section → 工具装配
- section=None（init 场景）→ 工具不装配
- scope=init 即使 section 非 None → 白名单过滤掉（init 阶段项目未成型）
- 工具调用：定位 drawings 章节 → 调 figure_service.generate_figure → 返回结果
- figure_service 抛异常 → 工具 rollback + 返回友好错误（事务边界）
"""
import asyncio
import uuid
from unittest.mock import MagicMock, patch


def _mock_mcp_empty(monkeypatch):
    from app.ai import tools as tools_mod

    async def _empty(_db):
        return []

    monkeypatch.setattr(tools_mod, "load_mcp_tools", _empty)


def _tool_names(tools) -> set[str]:
    return {getattr(t, "name", None) for t in tools}


def test_generate_figure_assembled_when_section_present(monkeypatch, db_session):
    """章节场景（section 非 None）装配 generate_figure。"""
    _mock_mcp_empty(monkeypatch)
    from app.ai.tools import create_agent_tools

    section = MagicMock()
    section.project_id = uuid.uuid4()
    tools = asyncio.run(create_agent_tools(db_session, uuid.uuid4(), scope="section", section=section))
    assert "generate_figure" in _tool_names(tools)


def test_generate_figure_not_assembled_when_section_none(monkeypatch, db_session):
    """init 场景（section=None）不装配 generate_figure。"""
    _mock_mcp_empty(monkeypatch)
    from app.ai.tools import create_agent_tools

    tools = asyncio.run(create_agent_tools(db_session, uuid.uuid4(), scope="section", section=None))
    assert "generate_figure" not in _tool_names(tools)


def test_generate_figure_filtered_out_in_init_scope(monkeypatch, db_session):
    """init scope 即使 section 非 None，白名单也过滤掉 generate_figure。"""
    _mock_mcp_empty(monkeypatch)
    from app.ai.tools import create_agent_tools

    section = MagicMock()
    section.project_id = uuid.uuid4()
    tools = asyncio.run(create_agent_tools(db_session, uuid.uuid4(), scope="init", section=section))
    assert "generate_figure" not in _tool_names(tools)


def test_generate_figure_tool_calls_figure_service(monkeypatch, db_session, registered_user):
    """工具调用：定位 drawings 章节 → 调 figure_service.generate_figure → 返回成功。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from sqlalchemy import select
    from app.models import User

    _mock_mcp_empty(monkeypatch)
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    project = create_project(db_session, user=user, title="测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(project.id))
    drawings = next(s for s in sections if s.key == "drawings")
    # 当前 agent 在 background 章节对话（非 drawings），图应归到 drawings
    current_section = next(s for s in sections if s.key == "background")

    from app.ai.tools import create_agent_tools
    tools = asyncio.run(create_agent_tools(db_session, user.id, scope="section", section=current_section))
    gen_tool = next(t for t in tools if t.name == "generate_figure")

    # mock figure_service.generate_figure（隔离 LLM + 渲染）
    fake_fig = MagicMock()
    fake_fig.id = uuid.uuid4()
    with patch("app.services.figure_service.generate_figure", return_value=fake_fig) as mock_gen:
        # langchain @tool 包装：invoke 传 dict
        result = gen_tool.invoke({"prompt": "系统框图", "diagram_type": "architecture"})

    assert "已生成附图" in result
    # 确认传给 figure_service 的是 drawings 章节 id（不是当前 background 章节）
    _, kwargs = mock_gen.call_args
    assert kwargs["section_id"] == str(drawings.id)
    assert kwargs["prompt"] == "系统框图"


def test_generate_figure_tool_rolls_back_on_failure(monkeypatch, db_session, registered_user):
    """figure_service 抛异常 → 工具 rollback + 返回友好错误（事务边界，不毒化 session）。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from sqlalchemy import select
    from app.models import User

    _mock_mcp_empty(monkeypatch)
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    project = create_project(db_session, user=user, title="测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(project.id))
    current_section = next(s for s in sections if s.key == "background")

    from app.ai.tools import create_agent_tools
    tools = asyncio.run(create_agent_tools(db_session, user.id, scope="section", section=current_section))
    gen_tool = next(t for t in tools if t.name == "generate_figure")

    with patch("app.services.figure_service.generate_figure", side_effect=Exception("渲染服务挂了")):
        result = gen_tool.invoke({"prompt": "测试", "diagram_type": "general"})

    assert "未生成" in result
    assert "渲染服务挂了" in result
    # session 仍可用（rollback 后未毒化）——验证能正常查询
    assert db_session.scalar(select(User).where(User.id == user.id)) is not None


def test_generate_figure_tool_no_drawings_section(monkeypatch, db_session, registered_user):
    """项目无 drawings 章节时返回提示（不崩溃）。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from sqlalchemy import select
    from app.models import User, Section

    _mock_mcp_empty(monkeypatch)
    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    project = create_project(db_session, user=user, title="测试发明")
    # 删掉 drawings 章节，模拟异常情况
    db_session.query(Section).filter(Section.key == "drawings", Section.project_id == project.id).delete()
    db_session.commit()
    sections = list_sections(db_session, user_id=user.id, project_id=str(project.id))
    current_section = sections[0]

    from app.ai.tools import create_agent_tools
    tools = asyncio.run(create_agent_tools(db_session, user.id, scope="section", section=current_section))
    gen_tool = next(t for t in tools if t.name == "generate_figure")

    result = gen_tool.invoke({"prompt": "测试", "diagram_type": "general"})
    assert "无「附图说明」章节" in result
