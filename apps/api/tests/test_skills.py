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

    u = User(username="s", email="s@b.com", password_hash=hash_password("Pass1234!"), name="S")
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
    u = User(username="s2", email="s2@b.com", password_hash=hash_password("Pass1234!"), name="S2")
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


def test_run_review_raises_when_rubric_review_disabled(db):
    """rubric_review 禁用时 run_review 拒绝执行。"""
    import pytest
    from app.core.exceptions import ValidationError
    from app.models import AgentSkill, Section

    p = _make_project(db)
    db.add(AgentSkill(project_id=p.id, skill_key="rubric_review", enabled=False))
    db.commit()
    # 加一个章节（review 需要）
    s = Section(project_id=p.id, template_section_id="t1", order=1, key="name",
                title="发明名称", status="empty")
    db.add(s)
    db.commit()

    from app.services import review_service
    with pytest.raises(ValidationError):
        review_service.run_review(db, user_id=p.user_id, project_id=str(p.id))


def test_run_review_uses_one_run_when_consistency_check_disabled(db, monkeypatch):
    """consistency_check 禁用时 _score_dimension 只调一次（CONSISTENCY_RUNS=1）。"""
    from app.models import Section

    p = _make_project(db)
    # 阶段 0 strict：run_review 现需生效 LLM 配置，否则抛 ValidationError
    from app.core.security import encrypt_value
    from app.models import UserLLMConfig
    db.add(UserLLMConfig(
        user_id=p.user_id, provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model", embedding_model="test-embed", is_active=True,
    ))
    # 禁用 consistency_check
    from app.models import AgentSkill
    db.add(AgentSkill(project_id=p.id, skill_key="consistency_check", enabled=False))
    db.commit()
    # 加章节
    s = Section(project_id=p.id, template_section_id="t1", order=1, key="name",
                title="发明名称", status="confirmed")
    s.content = {"text": "some content"}
    db.add(s)
    db.commit()

    # mock _score_dimension 计数
    calls = {"n": 0}

    import app.services.review_service as rs
    def counting_score(criterion, sections, llm_config):
        calls["n"] += 1
        return (80, "ev", "sug")

    monkeypatch.setattr(rs, "_score_dimension", counting_score)
    # mock get_effective_rubric 返回 1 个 criterion，避免依赖种子
    def fake_rubric(d, user_id):
        class FakeRubric:
            criteria = [{"key": "k", "name": "N", "weight": 1.0}]
        return FakeRubric()
    monkeypatch.setattr(rs, "get_effective_rubric", fake_rubric)

    rs.run_review(db, user_id=p.user_id, project_id=str(p.id))

    # 1 维度 × 1 run（consistency_check 禁用）= 1 次
    assert calls["n"] == 1


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })


def test_api_list_skills_returns_builtin_defaults(client, registered_user):
    """GET /projects/{id}/skills 返回 5 个 builtin 全启用。"""
    _login(client, registered_user)
    res = client.post("/api/v1/projects", json={"title": "P"})
    project_id = res.json()["id"]

    res = client.get(f"/api/v1/projects/{project_id}/skills")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 5
    assert all(s["enabled"] is True for s in data)
    assert all(s["is_builtin"] is True for s in data)


def test_api_update_skill_persists_override(client, registered_user):
    """PUT /projects/{id}/skills/{key} 持久化覆盖。"""
    _login(client, registered_user)
    project_id = client.post("/api/v1/projects", json={"title": "P"}).json()["id"]

    res = client.put(
        f"/api/v1/projects/{project_id}/skills/rag_search",
        json={"enabled": False, "config": {"k": 3}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["skill_key"] == "rag_search"
    assert body["enabled"] is False
    assert body["config"] == {"k": 3}

    # 再查 GET 确认持久化
    res = client.get(f"/api/v1/projects/{project_id}/skills")
    rag = next(s for s in res.json() if s["skill_key"] == "rag_search")
    assert rag["enabled"] is False
    assert rag["is_overridden"] is True


def test_api_update_unknown_skill_returns_422(client, registered_user):
    """未知 skill_key 返回 422。"""
    _login(client, registered_user)
    project_id = client.post("/api/v1/projects", json={"title": "P"}).json()["id"]
    res = client.put(
        f"/api/v1/projects/{project_id}/skills/nonexistent",
        json={"enabled": False},
    )
    assert res.status_code == 422


def test_api_list_skills_other_users_project_returns_404(client, registered_user, db_session):
    """非本人项目返回 404。"""
    from app.core.security import hash_password
    from app.models import User
    from app.services import project_service as ps

    other = User(username="other", email="other@b.com", password_hash=hash_password("Pass1234!"), name="O")
    db_session.add(other)
    db_session.commit()
    other_project = ps.create_project(db_session, user=other, title="别人的")

    _login(client, registered_user)
    res = client.get(f"/api/v1/projects/{other_project.id}/skills")
    assert res.status_code == 404


def test_api_skills_unauthenticated_returns_401(client, registered_user):
    """未登录返回 401。"""
    _login(client, registered_user)
    project_id = client.post("/api/v1/projects", json={"title": "P"}).json()["id"]
    # 清 cookie 模拟未登录
    client.cookies.clear()
    res = client.get(f"/api/v1/projects/{project_id}/skills")
    assert res.status_code == 401
