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
