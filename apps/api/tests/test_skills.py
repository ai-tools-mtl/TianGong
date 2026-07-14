"""AgentSkill 模型与 skill_service 测试。"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db():
    """独立 sqlite 内存库（service 层测试用）。"""
    from app.models import Base
    eng = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    session = S()
    yield session
    session.close()


def test_agent_skill_model_basic_fields(db):
    """AgentSkill 表存在且字段齐全。"""
    from app.core.security import hash_password
    from app.models import AgentSkill, Project, User

    u = User(email="s@b.com", password_hash=hash_password("Pass1234!"), name="S")
    db.add(u)
    db.commit()
    p = Project(user_id=u.id, title="项目")
    db.add(p)
    db.commit()

    skill = AgentSkill(
        project_id=p.id,
        skill_key="rag_search",
        enabled=False,
        config={"k": 5},
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)

    assert skill.id is not None
    assert skill.project_id == p.id
    assert skill.skill_key == "rag_search"
    assert skill.enabled is False
    assert skill.config == {"k": 5}
    assert skill.created_at is not None


def test_agent_skill_importable_from_models():
    """AgentSkill 在 app.models 命名空间里。"""
    from app.models import AgentSkill
    assert AgentSkill.__tablename__ == "agent_skills"


def _make_project(db):
    from app.core.security import hash_password
    from app.models import Project, User
    u = User(email="s2@b.com", password_hash=hash_password("Pass1234!"), name="S2")
    db.add(u)
    db.commit()
    p = Project(user_id=u.id, title="P")
    db.add(p)
    db.commit()
    return p


def test_list_skills_merges_builtin_with_overrides(db):
    """list_skills 返回 5 个 builtin，缺行 = default_enabled。"""
    from app.services import skill_service

    p = _make_project(db)
    skills = skill_service.list_skills(db, project_id=p.id)

    assert len(skills) == 5
    keys = {s["skill_key"] for s in skills}
    assert keys == {"rag_search", "rubric_review", "consistency_check", "quality_report", "prior_art_hint"}
    # 默认全部启用
    assert all(s["enabled"] is True for s in skills)
    # name/description 来自 builtin
    rag = next(s for s in skills if s["skill_key"] == "rag_search")
    assert rag["name"] == "知识库检索"
    assert rag["is_builtin"] is True


def test_list_skills_applies_project_override(db):
    """项目里禁用某技能，list_skills 反映禁用状态。"""
    from app.models import AgentSkill
    from app.services import skill_service

    p = _make_project(db)
    db.add(AgentSkill(project_id=p.id, skill_key="rag_search", enabled=False))
    db.commit()

    skills = skill_service.list_skills(db, project_id=p.id)
    rag = next(s for s in skills if s["skill_key"] == "rag_search")
    assert rag["enabled"] is False
    assert rag["is_overridden"] is True


def test_is_skill_enabled_missing_row_returns_default(db):
    """缺行 = default_enabled（rag_search 默认 True）。"""
    from app.services import skill_service

    p = _make_project(db)
    assert skill_service.is_skill_enabled(db, project_id=p.id, skill_key="rag_search") is True


def test_is_skill_enabled_respects_override(db):
    """覆盖禁用后 is_skill_enabled 返回 False。"""
    from app.models import AgentSkill
    from app.services import skill_service

    p = _make_project(db)
    db.add(AgentSkill(project_id=p.id, skill_key="rag_search", enabled=False))
    db.commit()
    assert skill_service.is_skill_enabled(db, project_id=p.id, skill_key="rag_search") is False


def test_set_skill_creates_or_updates_row(db):
    """set_skill 幂等：首次创建行，再次更新。"""
    from app.models import AgentSkill
    from app.services import skill_service

    p = _make_project(db)

    # 首次：创建覆盖行
    skill_service.set_skill(db, project_id=p.id, skill_key="rag_search", enabled=False, config={"k": 3})
    rows = db.query(AgentSkill).filter_by(project_id=p.id, skill_key="rag_search").all()
    assert len(rows) == 1
    assert rows[0].enabled is False
    assert rows[0].config == {"k": 3}

    # 再次：更新同一行
    skill_service.set_skill(db, project_id=p.id, skill_key="rag_search", enabled=True, config={"k": 5})
    rows = db.query(AgentSkill).filter_by(project_id=p.id, skill_key="rag_search").all()
    assert len(rows) == 1
    assert rows[0].enabled is True
    assert rows[0].config == {"k": 5}


def test_set_skill_unknown_key_raises(db):
    """未知 skill_key 抛 ValidationError。"""
    import pytest
    from app.core.exceptions import ValidationError
    from app.services import skill_service

    p = _make_project(db)
    with pytest.raises(ValidationError):
        skill_service.set_skill(db, project_id=p.id, skill_key="not_a_real_skill", enabled=False)


def test_retrieve_knowledge_skipped_when_rag_search_disabled(db):
    """rag_search 禁用时，orchestrator._retrieve_knowledge 直接返回 None，不调 retrieve。"""
    from app.models import AgentSkill, Section

    p = _make_project(db)
    # 禁用 rag_search
    db.add(AgentSkill(project_id=p.id, skill_key="rag_search", enabled=False))
    db.commit()
    section = Section(
        project_id=p.id, template_section_id="t1", order=1, key="name",
        title="发明名称", status="empty",
    )
    db.add(section)
    db.commit()

    retrieve_called = {"n": 0}

    import app.rag.retriever as retriever_mod
    original_retrieve = retriever_mod.retrieve

    def fake_retrieve(*args, **kwargs):
        retrieve_called["n"] += 1
        return []

    retriever_mod.retrieve = fake_retrieve
    try:
        from app.ai.orchestrator import _retrieve_knowledge
        result = _retrieve_knowledge(db, section, "查询")
        assert result is None
        assert retrieve_called["n"] == 0
    finally:
        retriever_mod.retrieve = original_retrieve


def test_retrieve_knowledge_runs_when_rag_search_enabled(db):
    """rag_search 启用时，_retrieve_knowledge 进入原检索逻辑。"""
    from app.models import Section

    p = _make_project(db)
    section = Section(
        project_id=p.id, template_section_id="t1", order=1, key="name",
        title="发明名称", status="empty",
    )
    db.add(section)
    db.commit()

    retrieve_called = {"n": 0}

    import app.rag.retriever as retriever_mod
    original_retrieve = retriever_mod.retrieve

    def fake_retrieve(*args, **kwargs):
        retrieve_called["n"] += 1
        return []

    retriever_mod.retrieve = fake_retrieve
    try:
        from app.ai.orchestrator import _retrieve_knowledge
        _retrieve_knowledge(db, section, "查询")
        # retrieve 被调用了（或异常降级路径，但至少进了检索分支）
        assert retrieve_called["n"] == 1
    finally:
        retriever_mod.retrieve = original_retrieve
