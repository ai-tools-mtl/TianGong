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


def test_build_system_prompt_user_input_used_as_retrieval_query(db_session, monkeypatch):
    """user_input 应作为记忆检索的唯一 query（spec §5.3 升级）。

    实测发现：user_input 与章节信号混拼会稀释语义信号（如「检查写作风格」
    +「发明名称」混拼后，最相关的「偏好简洁风格」记忆 score 跌出阈值）。
    故有 user_input 时只用 user_input，不混章节信号。
    """
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
    captured_query = {}

    class _FakeMem:
        content = "偏好简洁风格"

    def _capture(db, *, user_id, query, top_k=5):
        captured_query["query"] = query
        return [_FakeMem()]

    monkeypatch.setattr(memory_service, "search_memories", _capture)

    build_system_prompt(db_session, section, user_input="检查下我的写作风格")

    # 有 user_input 时，query 应等于 user_input（不混章节信号，避免稀释语义）
    assert captured_query["query"] == "检查下我的写作风格", \
        "有 user_input 时 query 应只含 user_input（混章节信号会稀释语义信号）"


def test_build_system_prompt_no_user_input_falls_back_to_section_signal(db_session, monkeypatch):
    """无 user_input（如 generate 场景）回退到纯章节信号检索。"""
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
    captured_query = {}

    def _capture(db, *, user_id, query, top_k=5):
        captured_query["query"] = query
        return []

    monkeypatch.setattr(memory_service, "search_memories", _capture)

    build_system_prompt(db_session, section, user_input=None)

    assert "背景技术" in captured_query["query"]
