"""协作系统测试（计划 17）。

覆盖：
- ProjectMember / ShareLink 模型字段与约束
- share_service 成员 CRUD / 分享链接 CRUD / verify / get_user_permission
- share API（owner-only 成员与分享链接管理 + 公开 /shared/{token}）
- collabora.py 权限感知的 collabora-url（owner=edit / member=comment / 非成员=404）
- /shared/{token}/collabora-url 访客端点
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models import Project, ProjectMember, ShareLink, User
from app.services import project_service as ps


# ── fixtures ──

def _make_user(db, email="owner@tiangong.dev", name="所有者"):
    u = User(email=email, password_hash=hash_password("Pass1234!"), name=name)
    db.add(u)
    db.commit()
    return u


def _make_project(db, user, title="协作测试项目"):
    return ps.create_project(db, user=user, title=title)


# ── ProjectMember 模型 ──

def test_project_member_defaults(db_session):
    """ProjectMember 默认 role=reviewer，含 id/时间戳。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    agent = _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    member = ProjectMember(project_id=project.id, user_id=agent.id)
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)

    assert member.role == "reviewer"
    assert member.id is not None
    assert member.created_at is not None
    assert member.updated_at is not None
    assert member.project_id == project.id
    assert member.user_id == agent.id


def test_project_member_unique_constraint(db_session):
    """(project_id, user_id) 唯一约束：重复插入抛 IntegrityError。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    agent = _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    m1 = ProjectMember(project_id=project.id, user_id=agent.id)
    db_session.add(m1)
    db_session.commit()

    m2 = ProjectMember(project_id=project.id, user_id=agent.id)
    db_session.add(m2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_project_member_same_user_different_projects(db_session):
    """同一用户可加入不同项目（唯一约束是 project+user 组合）。"""
    owner = _make_user(db_session)
    p1 = _make_project(db_session, owner, title="项目一")
    p2 = _make_project(db_session, owner, title="项目二")
    agent = _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    db_session.add_all([
        ProjectMember(project_id=p1.id, user_id=agent.id),
        ProjectMember(project_id=p2.id, user_id=agent.id),
    ])
    db_session.commit()
    rows = list(db_session.scalars(select(ProjectMember).where(ProjectMember.user_id == agent.id)))
    assert len(rows) == 2


# ── ShareLink 模型 ──

def test_share_link_defaults(db_session):
    """ShareLink 默认 permissions=comment，token 唯一，expires_at 可空。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    link = ShareLink(
        project_id=project.id,
        token=uuid.uuid4().hex,
        created_by=owner.id,
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    assert link.permissions == "comment"
    assert link.expires_at is None
    assert link.created_by == owner.id
    assert len(link.token) == 32  # uuid4().hex


def test_share_link_with_expiry(db_session):
    """expires_at 可设置 timezone-aware datetime。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    exp = datetime.now(timezone.utc) + timedelta(days=7)
    link = ShareLink(
        project_id=project.id,
        token=uuid.uuid4().hex,
        permissions="readonly",
        expires_at=exp,
        created_by=owner.id,
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)
    assert link.permissions == "readonly"
    assert link.expires_at is not None


def test_share_link_token_unique(db_session):
    """token 唯一约束：重复 token 抛 IntegrityError。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    token = uuid.uuid4().hex
    db_session.add(ShareLink(project_id=project.id, token=token, created_by=owner.id))
    db_session.commit()
    db_session.add(ShareLink(project_id=project.id, token=token, created_by=owner.id))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# ── share_service: 成员管理 ──

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.services import share_service


def test_list_members_returns_project_members(db_session):
    """list_members 返回项目的所有成员（不含 owner）。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    agent = _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    db_session.add(ProjectMember(project_id=project.id, user_id=agent.id))
    db_session.commit()

    members = share_service.list_members(db_session, project.id)
    assert len(members) == 1
    assert members[0].user_id == agent.id
    assert members[0].role == "reviewer"


def test_list_members_empty(db_session):
    """无成员时返回空列表。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    assert share_service.list_members(db_session, project.id) == []


def test_add_member_finds_user_by_email(db_session):
    """add_member 按邮箱找到已注册用户并创建成员（默认 reviewer）。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    _make_user(db_session, email="agent@tiangong.dev", name="代理人")

    member = share_service.add_member(db_session, project.id, "agent@tiangong.dev")
    assert member.user_id is not None
    assert member.role == "reviewer"
    assert member.project_id == project.id


def test_add_member_unregistered_email_raises_validation(db_session):
    """邮箱未注册时抛 ValidationError（用户未注册）。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    with pytest.raises(ValidationError) as exc:
        share_service.add_member(db_session, project.id, "nobody@tiangong.dev")
    assert "用户未注册" in str(exc.value)


def test_add_member_duplicate_raises_conflict(db_session):
    """重复添加同一成员抛 ConflictError。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    share_service.add_member(db_session, project.id, "agent@tiangong.dev")
    with pytest.raises(ConflictError):
        share_service.add_member(db_session, project.id, "agent@tiangong.dev")


def test_add_member_owner_self_raises_validation(db_session):
    """不能把项目 owner 自己加为成员。"""
    owner = _make_user(db_session, email="owner@tiangong.dev", name="所有者")
    project = _make_project(db_session, owner)
    with pytest.raises(ValidationError):
        share_service.add_member(db_session, project.id, "owner@tiangong.dev")


def test_remove_member_deletes_record(db_session):
    """remove_member 删除成员记录，幂等（不存在不报错）。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    agent = _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    member = ProjectMember(project_id=project.id, user_id=agent.id)
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)

    share_service.remove_member(db_session, project.id, member.id)
    assert db_session.get(ProjectMember, member.id) is None
    # 再次删除不报错（幂等）
    share_service.remove_member(db_session, project.id, member.id)


# ── share_service: get_user_permission ──

def test_get_user_permission_owner(db_session):
    """owner 返回 'owner'。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    assert share_service.get_user_permission(db_session, project.id, owner.id) == "owner"


def test_get_user_permission_member(db_session):
    """项目成员返回其角色（reviewer）。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    agent = _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    db_session.add(ProjectMember(project_id=project.id, user_id=agent.id, role="reviewer"))
    db_session.commit()
    assert share_service.get_user_permission(db_session, project.id, agent.id) == "reviewer"


def test_get_user_permission_none(db_session):
    """非 owner 非成员返回 'none'。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    stranger = _make_user(db_session, email="stranger@tiangong.dev", name="陌生人")
    assert share_service.get_user_permission(db_session, project.id, stranger.id) == "none"


def test_get_user_permission_nonexistent_project(db_session):
    """项目不存在返回 'none'（不抛异常，供 collabora-url 安全降级）。"""
    owner = _make_user(db_session)
    assert share_service.get_user_permission(db_session, uuid.uuid4(), owner.id) == "none"


# ── share_service: 分享链接管理 ──

def test_create_share_link_default_comment(db_session):
    """create_share_link 默认 permissions=comment，无过期。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    link = share_service.create_share_link(
        db_session, project.id, created_by=owner.id, permissions="comment", expires_days=None,
    )
    assert link.token == uuid.UUID(link.token).hex  # 合法 hex
    assert len(link.token) == 32
    assert link.permissions == "comment"
    assert link.expires_at is None
    assert link.created_by == owner.id


def test_create_share_link_readonly_with_expiry(db_session):
    """permissions=readonly + expires_days 设置过期时间。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    link = share_service.create_share_link(
        db_session, project.id, created_by=owner.id, permissions="readonly", expires_days=7,
    )
    assert link.permissions == "readonly"
    assert link.expires_at is not None
    # 过期时间约 7 天后
    now = datetime.now(timezone.utc)
    exp = link.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    delta = exp - now
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, minutes=1)


def test_create_share_link_invalid_permissions_raises(db_session):
    """permissions 非 comment/readonly 抛 ValidationError。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    with pytest.raises(ValidationError):
        share_service.create_share_link(
            db_session, project.id, created_by=owner.id, permissions="edit", expires_days=None,
        )


def test_create_share_link_unique_tokens(db_session):
    """连续创建两个链接，token 不同。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    l1 = share_service.create_share_link(db_session, project.id, owner.id, "comment", None)
    l2 = share_service.create_share_link(db_session, project.id, owner.id, "comment", None)
    assert l1.token != l2.token


def test_list_share_links(db_session):
    """list_share_links 返回项目的所有链接。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    share_service.create_share_link(db_session, project.id, owner.id, "comment", None)
    share_service.create_share_link(db_session, project.id, owner.id, "readonly", 7)
    links = share_service.list_share_links(db_session, project.id)
    assert len(links) == 2


def test_revoke_share_link_deletes(db_session):
    """revoke_share_link 删除链接，幂等。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    link = share_service.create_share_link(db_session, project.id, owner.id, "comment", None)
    share_service.revoke_share_link(db_session, project.id, link.id)
    assert db_session.get(ShareLink, link.id) is None
    # 幂等
    share_service.revoke_share_link(db_session, project.id, link.id)


# ── share_service: verify_share_link ──

def test_verify_share_link_valid(db_session):
    """有效链接返回 (link, project)。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    link = share_service.create_share_link(db_session, project.id, owner.id, "comment", None)
    got_link, got_project = share_service.verify_share_link(db_session, link.token)
    assert got_link.id == link.id
    assert got_project.id == project.id


def test_verify_share_link_nonexistent_raises_not_found(db_session):
    """不存在的 token 抛 NotFoundError。"""
    with pytest.raises(NotFoundError):
        share_service.verify_share_link(db_session, uuid.uuid4().hex)


def test_verify_share_link_expired_raises_not_found(db_session):
    """过期链接抛 NotFoundError。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    # 直接构造已过期链接
    link = ShareLink(
        project_id=project.id,
        token=uuid.uuid4().hex,
        permissions="comment",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        created_by=owner.id,
    )
    db_session.add(link)
    db_session.commit()
    with pytest.raises(NotFoundError):
        share_service.verify_share_link(db_session, link.token)


def test_verify_share_link_no_expiry_never_expires(db_session):
    """expires_at 为空表示永不过期。"""
    owner = _make_user(db_session)
    project = _make_project(db_session, owner)
    link = share_service.create_share_link(db_session, project.id, owner.id, "comment", None)
    got_link, got_project = share_service.verify_share_link(db_session, link.token)
    assert got_link.expires_at is None
    assert got_project.id == project.id


# ── API: 成员管理（owner-only）──

def _login(client, email, password="Pass1234!"):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text


def _seed_and_login_owner(client, db_session):
    """创建 owner + 项目，登录 owner，返回 (user, project_id)。"""
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    owner = _make_user(db_session, email="owner@tiangong.dev", name="所有者")
    project = _make_project(db_session, owner, title="成员 API 项目")
    _login(client, "owner@tiangong.dev")
    return owner, str(project.id)


def test_add_member_endpoint_owner(db_session, client):
    """owner POST 成员 → 201 + MemberOut。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    _make_user(db_session, email="agent@tiangong.dev", name="代理人")

    res = client.post(f"/api/v1/projects/{project_id}/members", json={"email": "agent@tiangong.dev"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["email"] == "agent@tiangong.dev"
    assert body["name"] == "代理人"
    assert body["role"] == "reviewer"
    assert body["project_id"] == project_id


def test_list_members_endpoint_owner(db_session, client):
    """owner GET 成员列表。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    agent = _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    db_session.add(ProjectMember(project_id=uuid.UUID(project_id), user_id=agent.id))
    db_session.commit()

    res = client.get(f"/api/v1/projects/{project_id}/members")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["email"] == "agent@tiangong.dev"


def test_remove_member_endpoint_owner(db_session, client):
    """owner DELETE 成员 → 204。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    agent = _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    member = ProjectMember(project_id=uuid.UUID(project_id), user_id=agent.id)
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)

    member_id = str(member.id)
    res = client.delete(f"/api/v1/projects/{project_id}/members/{member_id}")
    assert res.status_code == 204
    # 用 fresh query 而非 db_session.get（跨 session identity map 缓存问题）
    from sqlalchemy import select as _select
    assert db_session.scalar(
        _select(ProjectMember).where(ProjectMember.id == uuid.UUID(member_id))
    ) is None


def test_add_member_unregistered_returns_422(db_session, client):
    """邀请未注册邮箱 → 422 用户未注册。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    res = client.post(f"/api/v1/projects/{project_id}/members", json={"email": "ghost@tiangong.dev"})
    assert res.status_code == 422
    assert "用户未注册" in res.json()["message"]


def test_add_member_duplicate_returns_409(db_session, client):
    """重复邀请 → 409。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    _make_user(db_session, email="agent@tiangong.dev", name="代理人")
    client.post(f"/api/v1/projects/{project_id}/members", json={"email": "agent@tiangong.dev"})
    res = client.post(f"/api/v1/projects/{project_id}/members", json={"email": "agent@tiangong.dev"})
    assert res.status_code == 409


def test_member_endpoints_non_owner_returns_404(db_session, client):
    """非项目 owner 访问成员端点 → 404（防探测，不是 403）。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    # 另一个用户登录
    _make_user(db_session, email="stranger@tiangong.dev", name="陌生人")
    _login(client, "stranger@tiangong.dev")

    res_get = client.get(f"/api/v1/projects/{project_id}/members")
    res_post = client.post(f"/api/v1/projects/{project_id}/members", json={"email": "x@tiangong.dev"})
    assert res_get.status_code == 404
    assert res_post.status_code == 404


def test_member_endpoints_unauthenticated_returns_401(db_session, client):
    """未登录访问成员端点 → 401。"""
    owner = _make_user(db_session, email="owner@tiangong.dev", name="所有者")
    project = _make_project(db_session, owner)
    client.cookies.clear()
    res = client.get(f"/api/v1/projects/{project.id}/members")
    assert res.status_code == 401


def test_member_endpoints_nonexistent_project_returns_404(db_session, client):
    """不存在的项目 → 404。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    res = client.get(f"/api/v1/projects/{uuid.uuid4()}/members")
    assert res.status_code == 404


# ── API: 分享链接管理（owner-only）──

def test_create_share_link_endpoint(db_session, client):
    """owner POST 分享链接 → 201 + ShareLinkOut。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    res = client.post(f"/api/v1/projects/{project_id}/share-links", json={"permissions": "comment"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["permissions"] == "comment"
    assert len(body["token"]) == 32
    assert body["expires_at"] is None
    assert body["project_id"] == project_id


def test_create_share_link_with_expiry(db_session, client):
    """带 expires_days 的链接返回非空 expires_at。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    res = client.post(
        f"/api/v1/projects/{project_id}/share-links",
        json={"permissions": "readonly", "expires_days": 7},
    )
    assert res.status_code == 201
    assert res.json()["expires_at"] is not None


def test_create_share_link_invalid_permissions_422(db_session, client):
    """permissions 非 comment/readonly → Pydantic 422。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    res = client.post(
        f"/api/v1/projects/{project_id}/share-links",
        json={"permissions": "edit"},
    )
    assert res.status_code == 422


def test_list_share_links_endpoint(db_session, client):
    """owner GET 分享链接列表。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    client.post(f"/api/v1/projects/{project_id}/share-links", json={"permissions": "comment"})
    client.post(f"/api/v1/projects/{project_id}/share-links", json={"permissions": "readonly"})
    res = client.get(f"/api/v1/projects/{project_id}/share-links")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_revoke_share_link_endpoint(db_session, client):
    """owner DELETE 分享链接 → 204。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    create_res = client.post(f"/api/v1/projects/{project_id}/share-links", json={"permissions": "comment"})
    link_id = create_res.json()["id"]
    res = client.delete(f"/api/v1/projects/{project_id}/share-links/{link_id}")
    assert res.status_code == 204


def test_share_link_endpoints_non_owner_404(db_session, client):
    """非 owner 访问分享链接端点 → 404。"""
    owner, project_id = _seed_and_login_owner(client, db_session)
    _make_user(db_session, email="stranger@tiangong.dev", name="陌生人")
    _login(client, "stranger@tiangong.dev")
    res_get = client.get(f"/api/v1/projects/{project_id}/share-links")
    res_post = client.post(f"/api/v1/projects/{project_id}/share-links", json={"permissions": "comment"})
    assert res_get.status_code == 404
    assert res_post.status_code == 404


# ── API: 公开 /shared/{token}（无 cookie 鉴权）──

def test_shared_info_public_endpoint(db_session, client):
    """GET /shared/{token} 无需登录返回项目标题 + 权限。"""
    owner = _make_user(db_session, email="owner@tiangong.dev", name="所有者")
    project = _make_project(db_session, owner, title="公开分享项目")
    link = share_service.create_share_link(db_session, project.id, owner.id, "comment", None)

    # 清除 cookie，模拟访客
    client.cookies.clear()
    res = client.get(f"/api/v1/shared/{link.token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "公开分享项目"
    assert body["permissions"] == "comment"
    assert body["share_token"] == link.token


def test_shared_info_nonexistent_token_404(db_session, client):
    """不存在的 token → 404。"""
    client.cookies.clear()
    res = client.get(f"/api/v1/shared/{uuid.uuid4().hex}")
    assert res.status_code == 404


def test_shared_info_expired_token_404(db_session, client):
    """过期 token → 404。"""
    owner = _make_user(db_session, email="owner@tiangong.dev", name="所有者")
    project = _make_project(db_session, owner)
    link = ShareLink(
        project_id=project.id,
        token=uuid.uuid4().hex,
        permissions="comment",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        created_by=owner.id,
    )
    db_session.add(link)
    db_session.commit()
    client.cookies.clear()
    res = client.get(f"/api/v1/shared/{link.token}")
    assert res.status_code == 404
