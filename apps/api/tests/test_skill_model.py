# apps/api/tests/test_skill_model.py
"""Skill 模型测试：两档可见性、状态机、MinIO 前缀。"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.base import Base


@pytest.fixture
def db():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def test_create_personal_skill(db):
    """个人 skill：scope=personal，owner_id 必填，minio_prefix 含 owner。"""
    from app.models import Skill

    owner = uuid.uuid4()
    skill = Skill(
        name="patent-claim-writer",
        description="辅助撰写权利要求",
        scope="personal",
        owner_id=owner,
        status="draft",
        minio_prefix=f"skills/personal/{owner}/patent-claim-writer/",
    )
    db.add(skill)
    db.commit()
    assert skill.id is not None
    assert skill.scope == "personal"
    assert skill.owner_id == owner
    assert skill.status == "draft"


def test_create_global_skill(db):
    """全局 skill：scope=global，owner_id=NULL。"""
    from app.models import Skill

    skill = Skill(
        name="prior-art-search",
        description="检索现有技术",
        scope="global",
        owner_id=None,
        status="active",
        minio_prefix="skills/global/prior-art-search/",
    )
    db.add(skill)
    db.commit()
    assert skill.scope == "global"
    assert skill.owner_id is None
    assert skill.status == "active"


def test_skill_has_timestamps(db):
    """Skill 继承 TimestampMixin，含 created_at/updated_at。"""
    from app.models import Skill

    skill = Skill(
        name="x", description="d", scope="global", status="draft",
        minio_prefix="skills/global/x/",
    )
    db.add(skill)
    db.commit()
    assert skill.created_at is not None
    assert skill.updated_at is not None


def test_duplicate_global_name_raises(db):
    """global skill 同名应被唯一约束拒绝。"""
    from sqlalchemy.exc import IntegrityError
    from app.models import Skill

    db.add(Skill(name="dup", description="d", scope="global", status="draft", minio_prefix="skills/global/dup/"))
    db.commit()

    db.add(Skill(name="dup", description="d2", scope="global", status="draft", minio_prefix="skills/global/dup/"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_duplicate_personal_name_same_owner_raises(db):
    """同一用户的 personal skill 同名应被拒绝。"""
    from sqlalchemy.exc import IntegrityError
    from app.models import Skill

    owner = uuid.uuid4()
    db.add(Skill(name="my-skill", description="d", scope="personal", owner_id=owner, status="draft",
                 minio_prefix=f"skills/personal/{owner}/my-skill/"))
    db.commit()

    db.add(Skill(name="my-skill", description="d2", scope="personal", owner_id=owner, status="draft",
                 minio_prefix=f"skills/personal/{owner}/my-skill/"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
