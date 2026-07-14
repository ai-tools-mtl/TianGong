import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models import Base, Project, User
from app.services import project_service as ps


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    session = S()
    yield session
    session.close()


def _make_user(db, email="u@b.com", role="user"):
    u = User(email=email, password_hash=hash_password("Pass1234!"), name="U", role=role)
    db.add(u)
    db.commit()
    return u


# ── service 层 ──

def test_create_project(db):
    user = _make_user(db)
    p = ps.create_project(db, user=user, title="我的发明")
    assert p.id is not None
    assert p.title == "我的发明"
    assert p.stage == "disclosure"
    assert p.status == "draft"
    assert p.user_id == user.id


def test_list_projects_only_own(db):
    owner = _make_user(db, "o@b.com")
    intruder = _make_user(db, "i@b.com")
    ps.create_project(db, user=owner, title="别人的")
    ps.create_project(db, user=intruder, title="我的")
    projects = ps.list_projects(db, user=intruder)
    assert len(projects) == 1
    assert projects[0].title == "我的"


def test_get_project_not_found_raises(db):
    user = _make_user(db)
    with pytest.raises(NotFoundError):
        ps.get_project(db, user=user, project_id=str(uuid.uuid4()))


def test_get_project_other_users_returns_404(db):
    owner = _make_user(db, "o@b.com")
    intruder = _make_user(db, "i@b.com")
    p = ps.create_project(db, user=owner, title="所有者的")
    with pytest.raises(NotFoundError):
        ps.get_project(db, user=intruder, project_id=str(p.id))


def test_delete_project(db):
    user = _make_user(db)
    p = ps.create_project(db, user=user, title="待删")
    ps.delete_project(db, user=user, project_id=str(p.id))
    with pytest.raises(NotFoundError):
        ps.get_project(db, user=user, project_id=str(p.id))


# ── API 层 ──

def test_api_create_and_list(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    res = client.post("/api/v1/projects", json={"title": "API发明"})
    assert res.status_code == 201
    assert res.json()["title"] == "API发明"

    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_api_access_other_users_project_returns_404(client, registered_user, db_session):
    other = User(email="o@b.com", password_hash=hash_password("Pass1234!"), name="O")
    db_session.add(other)
    db_session.commit()
    other_project = ps.create_project(db_session, user=other, title="别人的")

    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    res = client.get(f"/api/v1/projects/{other_project.id}")
    assert res.status_code == 404


def test_api_unauthenticated_returns_401(client):
    res = client.get("/api/v1/projects")
    assert res.status_code == 401


def test_api_get_project_returns_status_and_archived_at(client, registered_user, db_session):
    """GET /projects/{id} 响应含 status 与 archived_at（archived_at 初始为 null）。"""
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]

    res = client.get(f"/api/v1/projects/{project_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "draft"
    assert "archived_at" in body
    assert body["archived_at"] is None  # 未归档
