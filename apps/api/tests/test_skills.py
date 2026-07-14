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
