# apps/api/tests/test_support_access.py
"""经授权临时查看（§8.3 完整版）测试：service 生命周期 + 用户侧 owner-only + admin 核销/窗口/审计。"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models import AuditLog, Project, Section, SupportAccessCode, User
from app.services import support_access_service as svc


@pytest.fixture
def owner_user(db_session):
    u = User(
        username=f"owner-{uuid.uuid4().hex[:6]}",
        email=f"owner-{uuid.uuid4().hex[:6]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="求助用户",
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def admin_user(db_session):
    a = User(
        username="supportadmin",
        email="supportadmin@tiangong.dev",
        password_hash=hash_password("Admin1234!"), name="管理员",
        role="admin", status="active",
    )
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture
def project(db_session, owner_user):
    p = Project(user_id=owner_user.id, title="求助项目")
    db_session.add(p)
    db_session.flush()
    db_session.add(Section(
        project_id=p.id, template_section_id="ts-bg", order=1,
        key="background", title="背景技术", status="confirmed",
        content={"type": "doc", "content": []},
    ))
    db_session.commit()
    db_session.refresh(p)
    return p


# ── service 层 ────────────────────────────────────────────────────────────────


def test_generate_and_redeem_lifecycle(db_session, owner_user, admin_user, project):
    row = svc.generate_code(db_session, project_id=project.id, user=owner_user)
    assert len(row.code) == 8
    assert svc.code_status(row) == "active"

    redeemed, proj = svc.verify_and_redeem(db_session, code=row.code, admin=admin_user)
    assert proj.id == project.id
    assert redeemed.redeemed_by == admin_user.id
    assert redeemed.view_expires_at is not None
    assert svc.code_status(redeemed) == "redeemed"

    # 二次核销失败（一次性）
    with pytest.raises(NotFoundError):
        svc.verify_and_redeem(db_session, code=row.code, admin=admin_user)

    # 窗口内核销人可反复查看
    again, _ = svc.verify_view_access(db_session, code=row.code, admin=admin_user)
    assert again.id == redeemed.id

    # 其他 admin 不能看
    other_admin = User(
        username="otheradmin", email="otheradmin@tiangong.dev",
        password_hash="x", name="o", role="admin", status="active",
    )
    db_session.add(other_admin)
    db_session.commit()
    with pytest.raises(NotFoundError):
        svc.verify_view_access(db_session, code=row.code, admin=other_admin)


def test_redeem_expired_code_rejected(db_session, owner_user, admin_user, project):
    row = svc.generate_code(db_session, project_id=project.id, user=owner_user)
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    with pytest.raises(NotFoundError):
        svc.verify_and_redeem(db_session, code=row.code, admin=admin_user)


def test_view_window_expiry(db_session, owner_user, admin_user, project):
    row = svc.generate_code(db_session, project_id=project.id, user=owner_user)
    _, _ = svc.verify_and_redeem(db_session, code=row.code, admin=admin_user)
    row.view_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert svc.code_status(row) == "expired"
    with pytest.raises(NotFoundError):
        svc.verify_view_access(db_session, code=row.code, admin=admin_user)


def test_revoke_blocks_everything(db_session, owner_user, admin_user, project):
    row = svc.generate_code(db_session, project_id=project.id, user=owner_user)
    _, _ = svc.verify_and_redeem(db_session, code=row.code, admin=admin_user)
    svc.revoke_code(db_session, code_id=row.id, user_id=owner_user.id)
    assert svc.code_status(row) == "revoked"
    # 吊销后窗口内查看也拒绝
    with pytest.raises(NotFoundError):
        svc.verify_view_access(db_session, code=row.code, admin=admin_user)
    # 幂等：重复吊销不报错
    svc.revoke_code(db_session, code_id=row.id, user_id=owner_user.id)


def test_invalid_codes_unified_404(db_session, admin_user):
    """不存在/错误格式统一 NotFoundError（防探测）。"""
    with pytest.raises(NotFoundError):
        svc.verify_and_redeem(db_session, code="ZZZZZZZZ", admin=admin_user)
    with pytest.raises(NotFoundError):
        svc.verify_and_redeem(db_session, code="", admin=admin_user)


# ── 用户侧 API（owner-only）──────────────────────────────────────────────────


def _login(client, username, password):
    client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_user_create_list_revoke_codes(client, db_session, owner_user, project):
    _login(client, owner_user.username, "Pass1234!")
    res = client.post(f"/api/v1/projects/{project.id}/support-codes", json={"ttl_minutes": 60})
    assert res.status_code == 201
    code = res.json()
    assert code["status"] == "active"
    assert len(code["code"]) == 8

    res = client.get(f"/api/v1/projects/{project.id}/support-codes")
    assert res.status_code == 200 and len(res.json()) == 1

    res = client.delete(f"/api/v1/projects/{project.id}/support-codes/{code['id']}")
    assert res.status_code == 204
    db_session.expire_all()
    assert db_session.get(SupportAccessCode, uuid.UUID(code["id"])).revoked_at is not None


def test_user_side_non_owner_404(client, db_session, project):
    """非 owner 生成/列表 → 404（资源级授权）。"""
    other = User(
        username="intruder", email="intruder@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="i",
    )
    db_session.add(other)
    db_session.commit()
    _login(client, other.username, "Pass1234!")
    assert client.post(
        f"/api/v1/projects/{project.id}/support-codes", json={}).status_code == 404
    assert client.get(
        f"/api/v1/projects/{project.id}/support-codes").status_code == 404


# ── admin 侧 API（require_admin + 审计）──────────────────────────────────────


def test_admin_redeem_returns_sections_and_audits(client, db_session, owner_user, admin_user, project):
    row = svc.generate_code(db_session, project_id=project.id, user=owner_user)
    _login(client, admin_user.username, "Admin1234!")

    res = client.post("/api/v1/admin/support-codes/redeem", json={"code": row.code})
    assert res.status_code == 200
    data = res.json()
    assert data["project"]["title"] == "求助项目"
    assert len(data["project"]["sections"]) == 1
    assert data["project"]["sections"][0]["title"] == "背景技术"
    assert data["owner_id"] == str(owner_user.id)
    assert data["view_expires_at"] is not None

    db_session.expire_all()
    audits = db_session.query(AuditLog).filter_by(action="support_view_project").all()
    assert len(audits) == 1
    # 审计 detail 不含码明文
    assert row.code not in str(audits[0].detail)
    assert audits[0].detail["code_id"] == str(row.id)

    # 窗口内重复查看（GET）：再次审计
    res2 = client.get(f"/api/v1/admin/support-codes/{row.code}/view")
    assert res2.status_code == 200
    assert res2.json()["project"]["title"] == "求助项目"
    db_session.expire_all()
    assert db_session.query(AuditLog).filter_by(action="support_view_project").count() == 2

    # 二次核销 404（一次性）
    res3 = client.post("/api/v1/admin/support-codes/redeem", json={"code": row.code})
    assert res3.status_code == 404


def test_admin_redeem_requires_admin(client, db_session, owner_user, project):
    row = svc.generate_code(db_session, project_id=project.id, user=owner_user)
    _login(client, owner_user.username, "Pass1234!")  # 普通用户
    assert client.post(
        "/api/v1/admin/support-codes/redeem", json={"code": row.code}).status_code == 403


def test_admin_view_only_by_redeemer(client, db_session, owner_user, admin_user, project):
    row = svc.generate_code(db_session, project_id=project.id, user=owner_user)
    svc.verify_and_redeem(db_session, code=row.code, admin=admin_user)
    other_admin = User(
        username="otheradmin2", email="otheradmin2@tiangong.dev",
        password_hash=hash_password("Admin1234!"), name="o", role="admin", status="active",
    )
    db_session.add(other_admin)
    db_session.commit()
    _login(client, other_admin.username, "Admin1234!")
    assert client.get(
        f"/api/v1/admin/support-codes/{row.code}/view").status_code == 404
