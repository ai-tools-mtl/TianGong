import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import hash_password
from app.models import Base, Project, User
from app.services import tag_service as ts


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


def _make_project(db, user, title="P1"):
    p = Project(user_id=user.id, title=title)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ── CRUD ──

def test_create_tag(db):
    user = _make_user(db)
    tag = ts.create_tag(db, user=user, name="通信")
    assert tag.id is not None
    assert tag.name == "通信"
    assert tag.user_id == user.id


def test_list_tags_returns_only_own(db):
    user_a = _make_user(db, email="a@b.com")
    user_b = _make_user(db, email="b@b.com")
    ts.create_tag(db, user=user_a, name="A的标签")
    ts.create_tag(db, user=user_b, name="B的标签")

    result = ts.list_tags(db, user=user_a)
    assert len(result) == 1
    assert result[0].name == "A的标签"


def test_list_tags_with_project_count(db):
    user = _make_user(db)
    p1 = _make_project(db, user, "P1")
    p2 = _make_project(db, user, "P2")
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p1.id), tag_id=str(tag.id))
    ts.attach_tag(db, user=user, project_id=str(p2.id), tag_id=str(tag.id))

    result = ts.list_tags(db, user=user)
    assert result[0].name == "通信"
    assert result[0].project_count == 2


def test_rename_tag(db):
    user = _make_user(db)
    tag = ts.create_tag(db, user=user, name="通信")
    updated = ts.rename_tag(db, user=user, tag_id=str(tag.id), name="通信领域")
    assert updated.name == "通信领域"


def test_rename_tag_not_owner_returns_404(db):
    user_a = _make_user(db, email="a@b.com")
    user_b = _make_user(db, email="b@b.com")
    tag = ts.create_tag(db, user=user_a, name="A的")
    with pytest.raises(NotFoundError):
        ts.rename_tag(db, user=user_b, tag_id=str(tag.id), name="改了")


def test_delete_tag_cascades_project_tags(db):
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))

    ts.delete_tag(db, user=user, tag_id=str(tag.id))

    from app.models import ProjectTag
    links = list(db.scalars(select(ProjectTag).where(ProjectTag.tag_id == tag.id)))
    assert len(links) == 0


def test_delete_tag_not_owner_returns_404(db):
    user_a = _make_user(db, email="a@b.com")
    user_b = _make_user(db, email="b@b.com")
    tag = ts.create_tag(db, user=user_a, name="A的")
    with pytest.raises(NotFoundError):
        ts.delete_tag(db, user=user_b, tag_id=str(tag.id))


# ── 合并 ──

def test_merge_tags_moves_links_and_deletes_source(db):
    user = _make_user(db)
    p1 = _make_project(db, user, "P1")
    p2 = _make_project(db, user, "P2")
    source = ts.create_tag(db, user=user, name="通讯")
    target = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p1.id), tag_id=str(source.id))
    ts.attach_tag(db, user=user, project_id=str(p2.id), tag_id=str(source.id))

    ts.merge_tags(db, user=user, source_id=str(source.id), target_id=str(target.id))

    from app.models import Tag
    assert db.get(Tag, source.id) is None
    target_tags = ts.list_tags_for_project(db, user=user, project_id=str(p1.id))
    assert any(t.name == "通信" for t in target_tags)
    target_tags_p2 = ts.list_tags_for_project(db, user=user, project_id=str(p2.id))
    assert any(t.name == "通信" for t in target_tags_p2)


def test_merge_same_tag_raises_validation_error(db):
    user = _make_user(db)
    tag = ts.create_tag(db, user=user, name="通信")
    with pytest.raises(ValidationError):
        ts.merge_tags(db, user=user, source_id=str(tag.id), target_id=str(tag.id))


# ── 项目贴/摘标签 ──

def test_attach_tag(db):
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))

    tags = ts.list_tags_for_project(db, user=user, project_id=str(p.id))
    assert len(tags) == 1
    assert tags[0].name == "通信"


def test_attach_tag_idempotent(db):
    """同一标签贴两次不报错、不重复。"""
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))  # 幂等

    tags = ts.list_tags_for_project(db, user=user, project_id=str(p.id))
    assert len(tags) == 1


def test_attach_tag_other_users_project_404(db):
    user_a = _make_user(db, email="a@b.com")
    user_b = _make_user(db, email="b@b.com")
    p = _make_project(db, user_a)
    tag = ts.create_tag(db, user=user_b, name="B的标签")
    with pytest.raises(NotFoundError):
        ts.attach_tag(db, user=user_b, project_id=str(p.id), tag_id=str(tag.id))


def test_detach_tag(db):
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))
    ts.detach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))

    tags = ts.list_tags_for_project(db, user=user, project_id=str(p.id))
    assert len(tags) == 0


def test_detach_not_attached_is_idempotent(db):
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    # 不贴直接摘，不报错
    ts.detach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))


def test_merge_tags_handles_duplicate_project(db):
    """合并时 source 和 target 都关联了同一项目：source link 应被删除而非引发唯一约束冲突。"""
    user = _make_user(db)
    p = _make_project(db, user, "P1")
    source = ts.create_tag(db, user=user, name="通讯")
    target = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(source.id))
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(target.id))  # both on P1

    ts.merge_tags(db, user=user, source_id=str(source.id), target_id=str(target.id))

    # P1 should have exactly ONE tag link (target), no constraint violation
    tags = ts.list_tags_for_project(db, user=user, project_id=str(p.id))
    assert len(tags) == 1
    assert tags[0].name == "通信"


# ── API 层 ──

def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })


def test_api_list_tags_empty(client, registered_user):
    _login(client, registered_user)
    res = client.get("/api/v1/tags")
    assert res.status_code == 200
    assert res.json() == []


def test_api_create_and_list_tag(client, registered_user):
    _login(client, registered_user)
    res = client.post("/api/v1/tags", json={"name": "通信"})
    assert res.status_code == 201
    assert res.json()["name"] == "通信"

    res = client.get("/api/v1/tags")
    assert len(res.json()) == 1
    assert res.json()[0]["name"] == "通信"
    assert res.json()[0]["project_count"] == 0


def test_api_rename_tag(client, registered_user):
    _login(client, registered_user)
    tag_id = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]
    res = client.patch(f"/api/v1/tags/{tag_id}", json={"name": "通信领域"})
    assert res.status_code == 200
    assert res.json()["name"] == "通信领域"


def test_api_merge_tags(client, registered_user):
    _login(client, registered_user)
    source_id = client.post("/api/v1/tags", json={"name": "通讯"}).json()["id"]
    target_id = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]
    res = client.post("/api/v1/tags/merge", json={"source_id": source_id, "target_id": target_id})
    assert res.status_code == 200

    tags = client.get("/api/v1/tags").json()
    assert len(tags) == 1
    assert tags[0]["name"] == "通信"


def test_api_delete_tag(client, registered_user):
    _login(client, registered_user)
    tag_id = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]
    res = client.delete(f"/api/v1/tags/{tag_id}")
    assert res.status_code == 204
    assert client.get("/api/v1/tags").json() == []


def test_api_attach_tag_to_project(client, registered_user, db_session):
    _login(client, registered_user)
    pid = client.post("/api/v1/projects", json={"title": "P1"}).json()["id"]
    tid = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]

    res = client.post(f"/api/v1/projects/{pid}/tags/{tid}")
    assert res.status_code == 200
    tags = res.json()
    assert len(tags) == 1
    assert tags[0]["name"] == "通信"


def test_api_detach_tag_from_project(client, registered_user, db_session):
    _login(client, registered_user)
    pid = client.post("/api/v1/projects", json={"title": "P1"}).json()["id"]
    tid = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]
    client.post(f"/api/v1/projects/{pid}/tags/{tid}")  # 先贴上

    res = client.delete(f"/api/v1/projects/{pid}/tags/{tid}")
    assert res.status_code == 200
    tags = res.json()
    assert len(tags) == 0  # 摘除后为空


def test_api_project_out_includes_tags(client, registered_user, db_session):
    """GET /projects 返回的项目对象含 tags 字段。"""
    _login(client, registered_user)
    pid = client.post("/api/v1/projects", json={"title": "P1"}).json()["id"]
    tid = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]
    client.post(f"/api/v1/projects/{pid}/tags/{tid}")

    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    projects = res.json()
    assert len(projects) == 1
    assert projects[0]["tags"] == [tid]
