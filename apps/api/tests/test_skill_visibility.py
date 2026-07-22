# apps/api/tests/test_skill_visibility.py
"""可见性合并：global ∪ personal（纯运行时，项目无状态）。

spec Q11-α：每次 agent run 实时算可见集合，不存项目状态。
"""
import uuid


def test_visible_skills_global_only(db_session):
    """只有 global skill 时，普通用户可见它。"""
    from app.models import Skill
    from app.skills.visibility import list_visible_skills

    g = Skill(name="g1", description="d", scope="global", owner_id=None,
              status="active", minio_prefix="skills/global/g1/")
    db_session.add(g); db_session.commit()

    user_id = uuid.uuid4()
    result = list_visible_skills(db_session, user_id=user_id)
    assert [s.name for s in result] == ["g1"]


def test_visible_skills_personal_only(db_session):
    """只有个人 skill，仅本人可见。"""
    from app.models import Skill
    from app.skills.visibility import list_visible_skills

    owner = uuid.uuid4()
    p = Skill(name="p1", description="d", scope="personal", owner_id=owner,
              status="active", minio_prefix=f"skills/personal/{owner}/p1/")
    db_session.add(p); db_session.commit()

    assert [s.name for s in list_visible_skills(db_session, user_id=owner)] == ["p1"]
    other = uuid.uuid4()
    assert list_visible_skills(db_session, user_id=other) == []


def test_visible_skills_union(db_session):
    """global + personal 并集。"""
    from app.models import Skill
    from app.skills.visibility import list_visible_skills

    owner = uuid.uuid4()
    db_session.add(Skill(name="g1", description="d", scope="global", status="active", minio_prefix="skills/global/g1/"))
    db_session.add(Skill(name="p1", description="d", scope="personal", owner_id=owner, status="active", minio_prefix=f"skills/personal/{owner}/p1/"))
    db_session.commit()

    names = {s.name for s in list_visible_skills(db_session, user_id=owner)}
    assert names == {"g1", "p1"}


def test_draft_skills_excluded(db_session):
    """status=draft 不进可见集合。"""
    from app.models import Skill
    from app.skills.visibility import list_visible_skills

    db_session.add(Skill(name="draft1", description="d", scope="global", status="draft", minio_prefix="skills/global/draft1/"))
    db_session.add(Skill(name="active1", description="d", scope="global", status="active", minio_prefix="skills/global/active1/"))
    db_session.commit()

    names = [s.name for s in list_visible_skills(db_session, user_id=uuid.uuid4())]
    assert "draft1" not in names
    assert "active1" in names


def test_build_agent_skill_sources(db_session):
    """为 deepagents 构造 source 路径列表（skills= 参数）。"""
    from app.models import Skill
    from app.skills.visibility import build_agent_skill_sources

    owner = uuid.uuid4()
    db_session.add(Skill(name="g1", description="d", scope="global", status="active", minio_prefix="skills/global/"))
    db_session.add(Skill(name="p1", description="d", scope="personal", owner_id=owner, status="active", minio_prefix=f"skills/personal/{owner}/"))
    db_session.commit()

    sources = build_agent_skill_sources(db_session, user_id=owner)
    assert "skills/global/" in sources
    assert f"skills/personal/{owner}/" in sources
