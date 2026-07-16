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
    username = email.split("@")[0]
    u = User(username=username, email=email, password_hash=hash_password("Pass1234!"), name="U", role=role)
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
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    res = client.post("/api/v1/projects", json={"title": "API发明"})
    assert res.status_code == 201
    assert res.json()["title"] == "API发明"

    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_api_access_other_users_project_returns_404(client, registered_user, db_session):
    other = User(username="o", email="o@b.com", password_hash=hash_password("Pass1234!"), name="O")
    db_session.add(other)
    db_session.commit()
    other_project = ps.create_project(db_session, user=other, title="别人的")

    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
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
        "username": registered_user["username"], "password": registered_user["password"],
    })
    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]

    res = client.get(f"/api/v1/projects/{project_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "draft"
    assert "archived_at" in body
    assert body["archived_at"] is None  # 未归档


# ── 归档端点（POST /projects/{id}/archive）──

def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })


def _seed_project_with_confirmed_section(db_session, registered_user, title="可归档发明"):
    """建项目并在 DB 层把第一个章节置为 confirmed+非空（绕过 confirm 时触发的 LLM summary）。"""
    from sqlalchemy import select
    from app.models import User
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    p = create_project(db_session, user=user, title=title)
    section = list_sections(db_session, user_id=user.id, project_id=str(p.id))[0]
    section.status = "confirmed"
    section.content = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "本发明涉及一种新型装置。"}]}
    ]}
    db_session.commit()
    return p


def test_api_archive_success(client, registered_user, db_session, monkeypatch):
    """归档成功返回 chunk 数（mock archiver 避开 sqlite pgvector 限制）。"""
    p = _seed_project_with_confirmed_section(db_session, registered_user)
    _login(client, registered_user)

    def fake_archive(db, *, user_id, project_id):
        return {"project_id": project_id, "chunks": 5, "status": "archived"}
    monkeypatch.setattr("app.api.projects.archive_service.archive", fake_archive)

    res = client.post(f"/api/v1/projects/{p.id}/archive")
    assert res.status_code == 200
    body = res.json()
    assert body["project_id"] == str(p.id)
    assert body["chunks"] == 5
    assert body["status"] == "archived"


def test_api_archive_idempotent(client, registered_user, db_session, monkeypatch):
    """重复归档幂等：二次调用同样 200。"""
    p = _seed_project_with_confirmed_section(db_session, registered_user)
    _login(client, registered_user)

    def fake_archive(db, *, user_id, project_id):
        return {"project_id": project_id, "chunks": 5, "status": "archived"}
    monkeypatch.setattr("app.api.projects.archive_service.archive", fake_archive)

    r1 = client.post(f"/api/v1/projects/{p.id}/archive")
    r2 = client.post(f"/api/v1/projects/{p.id}/archive")
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_api_archive_other_user_404(client, registered_user, db_session):
    """非本人项目归档返回 404（防探测，与 get/patch/delete 一致）。"""
    p = _seed_project_with_confirmed_section(db_session, registered_user)

    from app.core.security import hash_password
    from app.models import User
    other = User(username="other", email="other@b.com", password_hash=hash_password("Pass1234!"), name="Other")
    db_session.add(other)
    db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "other", "password": "Pass1234!"})

    res = client.post(f"/api/v1/projects/{p.id}/archive")
    assert res.status_code == 404


def test_api_archive_empty_project_422(client, registered_user, db_session):
    """无已确认章节的空项目归档返回 422（防造垃圾 chunk）。"""
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    _login(client, registered_user)
    res = client.post("/api/v1/projects", json={"title": "空项目"})
    project_id = res.json()["id"]

    res = client.post(f"/api/v1/projects/{project_id}/archive")
    assert res.status_code == 422
