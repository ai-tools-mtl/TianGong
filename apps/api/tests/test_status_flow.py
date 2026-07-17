import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.models import Base, Project, Section, User
from app.services import section_service as ss


@pytest.fixture
def db():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = {
        name: t for name, t in Base.metadata.tables.items()
        if name != "knowledge_chunks"
    }
    for t in tables.values():
        t.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng)
    session = Session()
    yield session
    session.close()


def _make_user(db, email="u@b.com"):
    username = email.split("@")[0]
    u = User(username=username, email=email, password_hash=hash_password("Pass1234!"), name="U")
    db.add(u)
    db.commit()
    return u


def _make_project_with_sections(db, user, n=2):
    """直接建一个含 n 个空 section 的项目（绕过模板依赖）。"""
    p = Project(user_id=user.id, title="测试项目")
    db.add(p)
    db.flush()
    for i in range(n):
        db.add(Section(
            project_id=p.id, template_section_id=f"s{i}", order=i,
            key=f"s{i}", title=f"章节{i}",
        ))
    db.commit()
    db.refresh(p)
    return p


def test_section_drafting_sets_project_in_progress(db):
    user = _make_user(db)
    p = _make_project_with_sections(db, user, n=2)
    assert p.status == "draft"  # 初始

    section = db.scalars(
        select(Section).where(Section.project_id == p.id)
    ).first()
    ss.update_section(db, user_id=user.id, section_id=str(section.id), status="drafting")

    db.refresh(p)
    assert p.status == "in_progress"


def test_all_sections_confirmed_sets_project_completed(db):
    user = _make_user(db)
    p = _make_project_with_sections(db, user, n=2)
    sections = list(db.scalars(
        select(Section).where(Section.project_id == p.id)
    ))

    for s in sections:
        ss.update_section(db, user_id=user.id, section_id=str(s.id), status="confirmed")

    db.refresh(p)
    assert p.status == "completed"


def test_partial_confirmed_sets_project_in_progress(db):
    user = _make_user(db)
    p = _make_project_with_sections(db, user, n=2)
    sections = list(db.scalars(
        select(Section).where(Section.project_id == p.id)
    ))

    # 只确认第一个
    ss.update_section(db, user_id=user.id, section_id=str(sections[0].id), status="confirmed")

    db.refresh(p)
    assert p.status == "in_progress"  # 不是 completed


def test_archived_project_not_overridden_by_section_update(db):
    """归档项目即使 section 变动也不回退 status（归档优先）。"""
    user = _make_user(db)
    p = _make_project_with_sections(db, user, n=1)
    p.status = "archived"
    db.commit()

    section = db.scalars(
        select(Section).where(Section.project_id == p.id)
    ).first()
    ss.update_section(db, user_id=user.id, section_id=str(section.id), status="drafting")

    db.refresh(p)
    assert p.status == "archived"  # 不被覆盖


def test_unconfirm_section_reverts_project_to_in_progress(db):
    """全部确认（completed）后，撤销一个 section（回退 drafting），项目应回到 in_progress。"""
    user = _make_user(db)
    p = _make_project_with_sections(db, user, n=2)
    sections = list(db.scalars(select(Section).where(Section.project_id == p.id)))

    # 全部确认 → completed
    for s in sections:
        ss.update_section(db, user_id=user.id, section_id=str(s.id), status="confirmed")
    db.refresh(p)
    assert p.status == "completed"

    # 撤销第一个 → 回到 drafting
    ss.update_section(db, user_id=user.id, section_id=str(sections[0].id), status="drafting")
    db.refresh(p)
    assert p.status == "in_progress"
