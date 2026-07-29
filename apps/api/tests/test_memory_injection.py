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


# ===== S3-2：记忆使用规则指令（spec 2026-07-29-prompt-content-design §4 S3-2）=====

def test_build_system_prompt_memories_has_usage_rules(db_session, monkeypatch):
    """[S3-2] 有记忆时注入使用规则（自然融入/不机械复读/无关则忽略）。

    注意：现有记忆段标题已含「请遵循其偏好与约定」，故断言用使用规则的独有特征词
    （「机械复读」「无关」），确保测的是新增规则而非旧文案。
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

    class _FakeMem:
        content = "偏好简洁风格"

    monkeypatch.setattr(memory_service, "search_memories",
                        lambda db, *, user_id, query, top_k=5: [_FakeMem()])
    # 无画像，避免画像段干扰
    monkeypatch.setattr(memory_service, "list_memories",
                        lambda db, *, user_id, source=None, limit=200: [])

    prompt = build_system_prompt(db_session, section)
    # 使用规则的独有特征词（旧文案「请遵循其偏好与约定」没有）
    assert "机械复读" in prompt or "复读" in prompt  # 不要机械复读
    assert "无关" in prompt                            # 无关记忆忽略


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


# ===== S2-3：用户画像 + 表达密度指令（spec 2026-07-29-prompt-content-design §4 S2-3）=====

def test_build_system_prompt_injects_profile_and_density(db_session, monkeypatch):
    """[S2-3] 有画像记忆（source=profile）时注入画像 + 表达密度指令。"""
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

    # 语义检索返回空（画像走单独的 list_memories(source=profile)）
    monkeypatch.setattr(memory_service, "search_memories",
                        lambda db, *, user_id, query, top_k=5: [])

    # 画像检索返回一条「专利代理人」画像
    class _FakeProfile:
        content = "用户是专利代理人，机械领域"
    monkeypatch.setattr(memory_service, "list_memories",
                        lambda db, *, user_id, source=None, limit=200: [_FakeProfile()] if source == "profile" else [])

    prompt = build_system_prompt(db_session, section)

    assert "专利代理人" in prompt          # 画像内容注入
    assert "专业术语" in prompt or "高密度" in prompt  # 代理人 → 高密度专业表达指令


def test_build_system_prompt_inventor_profile_gets_plain_language(db_session, monkeypatch):
    """[S2-3] 画像是发明人（非代理人）时注入「通俗化」表达指令。

    注意：SYSTEM_PROMPT 第1条含「通俗」，故断言用画像密度指令的独有标识词（「大白话」
    /「翻译成」/「过度解释」），避免被现有 SYSTEM_PROMPT 误命中。
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
    monkeypatch.setattr(memory_service, "search_memories",
                        lambda db, *, user_id, query, top_k=5: [])

    class _FakeProfile:
        content = "用户是机械工程师，发明人"
    monkeypatch.setattr(memory_service, "list_memories",
                        lambda db, *, user_id, source=None, limit=200: [_FakeProfile()] if source == "profile" else [])

    prompt = build_system_prompt(db_session, section)

    assert "用户画像" in prompt  # 画像段存在
    # 发明人 → 通俗化指令（用画像密度指令独有词，避开 SYSTEM_PROMPT 的「通俗」）
    assert "大白话" in prompt or "翻译成" in prompt or "过度解释" in prompt


def test_build_system_prompt_no_profile_omits_density(db_session, monkeypatch):
    """[S2-3] 无画像记忆时不注入表达密度段。"""
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
    monkeypatch.setattr(memory_service, "list_memories",
                        lambda db, *, user_id, source=None, limit=200: [])

    prompt = build_system_prompt(db_session, section)
    # 无画像 → 不出现画像密度指令段（用密度指令的独有特征词判断）
    assert "用户画像" not in prompt
