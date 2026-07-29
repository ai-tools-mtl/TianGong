"""记忆注入 system prompt 集成测试。"""
import uuid


def test_build_system_prompt_includes_memories(db_session, monkeypatch):
    """build_system_prompt 注入用户记忆段。"""
    from app.ai.context_assembler import build_system_prompt
    from app.models import Project, Section

    # 构造一个 section（带 project）
    project = Project(title="测试项目", user_id=uuid.uuid4())
    db_session.add(project)
    db_session.commit()
    section = Section(
        project_id=project.id, template_section_id="background",
        key="background", title="背景技术",
        order=1, content=None,
    )
    db_session.add(section)
    db_session.commit()

    # mock search_memories：patch 源模块属性（延迟 import 会拿到 patched 版本）
    from app.services import memory_service

    class _FakeMem:
        content = "偏好简洁风格"

    monkeypatch.setattr(memory_service, "search_memories",
                        lambda db, *, user_id, query, top_k=5: [_FakeMem()])

    prompt = build_system_prompt(db_session, section)

    assert "关于这位用户的长期记忆" in prompt
    assert "偏好简洁风格" in prompt


def test_build_system_prompt_no_memories_omits_section(db_session, monkeypatch):
    """无记忆时不输出记忆段（不留空标题）。"""
    from app.ai.context_assembler import build_system_prompt
    from app.models import Project, Section

    project = Project(title="测试项目", user_id=uuid.uuid4())
    db_session.add(project)
    db_session.commit()
    section = Section(
        project_id=project.id, template_section_id="background",
        key="background", title="背景技术",
        order=1, content=None,
    )
    db_session.add(section)
    db_session.commit()

    from app.services import memory_service
    monkeypatch.setattr(memory_service, "search_memories",
                        lambda db, *, user_id, query, top_k=5: [])

    prompt = build_system_prompt(db_session, section)
    assert "关于这位用户的长期记忆" not in prompt
