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
