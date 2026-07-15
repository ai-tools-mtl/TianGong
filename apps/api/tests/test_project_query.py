import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.models import Base, Project, Section, User
from app.services import project_service as ps


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
    u = User(email=email, password_hash=hash_password("Pass1234!"), name="U")
    db.add(u)
    db.commit()
    return u


def _make_project(db, user, title, status="draft"):
    p = Project(user_id=user.id, title=title, status=status)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_list_excludes_archived_by_default(db):
    user = _make_user(db)
    _make_project(db, user, "进行中", status="in_progress")
    _make_project(db, user, "已归档", status="archived")

    result = ps.list_projects(db, user=user)
    titles = [p.title for p in result]
    assert "进行中" in titles
    assert "已归档" not in titles  # 默认排除


def test_list_status_filter_archived(db):
    user = _make_user(db)
    _make_project(db, user, "进行中", status="in_progress")
    _make_project(db, user, "已归档", status="archived")

    result = ps.list_projects(db, user=user, status="archived")
    titles = [p.title for p in result]
    assert titles == ["已归档"]


def test_list_status_filter_in_progress(db):
    user = _make_user(db)
    _make_project(db, user, "草稿A", status="draft")
    _make_project(db, user, "进行B", status="in_progress")
    _make_project(db, user, "完成C", status="completed")

    result = ps.list_projects(db, user=user, status="in_progress")
    titles = [p.title for p in result]
    assert titles == ["进行B"]


def test_list_search_by_title(db):
    user = _make_user(db)
    _make_project(db, user, "通信专利改进方案")
    _make_project(db, user, "机械结构设计")
    _make_project(db, user, "通信协议优化")

    result = ps.list_projects(db, user=user, q="通信")
    titles = [p.title for p in result]
    assert set(titles) == {"通信专利改进方案", "通信协议优化"}


def test_list_search_case_insensitive(db):
    user = _make_user(db)
    _make_project(db, user, "AI Patent")
    _make_project(db, user, "Other")

    result = ps.list_projects(db, user=user, q="ai")
    assert len(result) == 1
    assert result[0].title == "AI Patent"
