from app.ai.context_assembler import assemble_messages, SYSTEM_PROMPT
from app.models import Message, Section


def _make_section(key="solution", title="技术方案"):
    return Section(
        template_section_id="ts", order=1, key=key, title=title,
        project_id="00000000-0000-0000-0000-000000000000",
    )


def test_assemble_has_system_prompt():
    section = _make_section()
    msgs = assemble_messages(section, [], user_input="测试")
    assert msgs[0].content.startswith(SYSTEM_PROMPT[:20])


def test_assemble_includes_section_goal():
    section = _make_section("solution")
    msgs = assemble_messages(section, [], user_input="测试")
    assert "技术方案" in msgs[0].content


def test_assemble_includes_history():
    section = _make_section()
    history = [
        Message(section_id="x", role="user", content="之前的问题"),
        Message(section_id="x", role="assistant", content="之前的回答"),
    ]
    msgs = assemble_messages(section, history, user_input="新问题")
    assert len(msgs) == 4


def test_assemble_includes_project_summaries():
    section = _make_section()
    summaries = [{"title": "背景技术", "summary": "现有技术不足"}]
    msgs = assemble_messages(section, [], user_input="测试", project_summaries=summaries)
    assert "背景技术" in msgs[0].content
    assert "现有技术不足" in msgs[0].content


# ===== get_written_sections_text 测试 =====

def _tiptap(text: str) -> dict:
    """构造最小 Tiptap JSON（含一段 text）。"""
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _make_project(db_session):
    """构造一个真实入库的 Project（含前置 User，满足 user_id NOT NULL 外键）。"""
    from app.models import Project, User
    import uuid
    from app.core.security import hash_password
    u = User(
        username=f"test-{uuid.uuid4().hex[:8]}",
        email=f"test-{uuid.uuid4().hex[:8]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="测试用户",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    p = Project(user_id=u.id, title="测试交底书")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _make_db_section(db_session, project_id, *, key, title, order, content=None):
    """构造一个真实入库的 Section。"""
    from app.models import Section
    s = Section(
        project_id=project_id,
        template_section_id=f"ts-{key}",
        order=order, key=key, title=title,
        content=content, status="drafting",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def test_get_written_sections_text_filters_empty_content(db_session):
    """content 为 None 的章节被跳过。"""
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)  # None，跳过
    _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("机械领域"))  # 保留
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert "技术领域" in text
    assert "发明名称" not in text  # content=None 被跳过


def test_get_written_sections_text_orders_by_section_order(db_session):
    """按 Section.order 排序（不是按插入顺序）。"""
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    # 故意倒序插入
    _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("BBB"))
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("AAA"))
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert text.index("AAA") < text.index("BBB")  # name(order=1) 在 field(order=2) 前


def test_get_written_sections_text_excludes_current_section(db_session):
    """exclude_key 指定的当前章节被排除。"""
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("门锁"))
    text = get_written_sections_text(db_session, p.id, exclude_key="name")
    assert "门锁" not in text
    assert text == ""  # 只有 name，被排除后为空


def test_get_written_sections_text_truncates_at_budget(db_session, monkeypatch):
    """超 8000 字时截断 + 标注「（已截断）」。"""
    from app.ai import context_assembler
    # 把预算调小到 50 字，便于测试
    monkeypatch.setattr(context_assembler, "WRITTEN_SECTIONS_CHAR_BUDGET", 50)
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    long_text = "X" * 200  # 远超 50 字预算
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap(long_text))
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert "（已截断）" in text
    assert len(text) <= 200  # 截断后远小于原文 200 字


def test_get_written_sections_text_truncation_keeps_earlier_full(db_session, monkeypatch):
    """截断时前面章节保持完整，当前超长章截断。"""
    from app.ai import context_assembler
    monkeypatch.setattr(context_assembler, "WRITTEN_SECTIONS_CHAR_BUDGET", 100)
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("短章完整内容"))
    _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("Y" * 200))  # 超长
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert "短章完整内容" in text  # name 完整保留
    assert "（已截断）" in text  # field 被截断
