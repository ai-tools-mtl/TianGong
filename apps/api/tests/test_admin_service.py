"""admin_service 测试：封禁/重置密码 + 自我保护 + 审计。"""

import uuid

import pytest
import sqlalchemy

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import verify_password
from app.models import AuditLog, User
from app.services import admin_service


@pytest.fixture
def admin_user(db_session):
    """普通管理员（role=admin, is_superuser=False）。"""
    u = User(
        username="admin",
        email="admin@example.com",
        password_hash="x",
        name="管理员",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def normal_user(db_session):
    u = User(
        username="user",
        email="user@example.com",
        password_hash="oldhash",
        name="普通用户",
        role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def superadmin(db_session):
    """命令行创建的超管（is_superuser=True）。"""
    u = User(
        username="root",
        email="root@example.com",
        password_hash="x",
        name="超管",
        role="admin",
        status="active",
        is_superuser=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def another_admin(db_session):
    u = User(
        username="admin2",
        email="admin2@example.com",
        password_hash="x",
        name="管理员2",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(u)
    db_session.commit()
    return u


# ── 封禁/解禁正常路径 ──

def test_ban_user_sets_status_disabled(db_session, admin_user, normal_user):
    admin_service.set_user_status(db_session, actor=admin_user, user_id=normal_user.id, status="disabled")
    db_session.refresh(normal_user)
    assert normal_user.status == "disabled"


def test_unban_user_sets_status_active(db_session, admin_user, normal_user):
    normal_user.status = "disabled"
    db_session.commit()
    admin_service.set_user_status(db_session, actor=admin_user, user_id=normal_user.id, status="active")
    db_session.refresh(normal_user)
    assert normal_user.status == "active"


def test_set_user_status_writes_audit_log(db_session, admin_user, normal_user):
    admin_service.set_user_status(db_session, actor=admin_user, user_id=normal_user.id, status="disabled")
    logs = list(db_session.scalars(sqlalchemy.select(AuditLog)))
    assert len(logs) == 1
    log = logs[0]
    assert log.action == "ban_user"
    assert log.target_type == "user"
    assert log.target_id == str(normal_user.id)
    assert log.actor_id == admin_user.id
    assert log.detail["status"] == "disabled"


# ── 自我保护 1：不能封禁/重置自己（ban + reset 都禁）──

def test_cannot_ban_self(db_session, admin_user):
    with pytest.raises(ForbiddenError):
        admin_service.set_user_status(
            db_session, actor=admin_user, user_id=admin_user.id, status="disabled"
        )


def test_cannot_reset_self(db_session, admin_user):
    with pytest.raises(ForbiddenError):
        admin_service.reset_user_password(
            db_session, actor=admin_user, user_id=admin_user.id, new_password="NewPass1!"
        )


# ── 自我保护 2：不能封禁超管（仅 ban；reset 放行——设计 8.1 仅禁封禁语义）──

def test_cannot_ban_superuser(db_session, admin_user, superadmin):
    with pytest.raises(ForbiddenError):
        admin_service.set_user_status(
            db_session, actor=admin_user, user_id=superadmin.id, status="disabled"
        )


def test_can_reset_superuser_password(db_session, admin_user, superadmin):
    """重置超管密码：设计 8.1 自我保护仅禁'封禁'语义，reset 放行。"""
    admin_service.reset_user_password(
        db_session, actor=admin_user, user_id=superadmin.id, new_password="NewPass1!"
    )
    db_session.refresh(superadmin)
    assert verify_password("NewPass1!", superadmin.password_hash)


# ── 自我保护 3：不能封禁其他管理员（仅 ban）──

def test_cannot_ban_other_admin(db_session, admin_user, another_admin):
    with pytest.raises(ForbiddenError):
        admin_service.set_user_status(
            db_session, actor=admin_user, user_id=another_admin.id, status="disabled"
        )


def test_can_reset_other_admin_password(db_session, admin_user, another_admin):
    """重置其他管理员密码：设计 8.1 仅禁封禁，reset 放行（不改账号可用性）。"""
    admin_service.reset_user_password(
        db_session, actor=admin_user, user_id=another_admin.id, new_password="NewPass1!"
    )
    db_session.refresh(another_admin)
    assert verify_password("NewPass1!", another_admin.password_hash)


# ── 重置密码正常路径 ──

def test_reset_password_updates_hash(db_session, admin_user, normal_user):
    admin_service.reset_user_password(
        db_session, actor=admin_user, user_id=normal_user.id, new_password="FreshPass9!"
    )
    db_session.refresh(normal_user)
    assert verify_password("FreshPass9!", normal_user.password_hash)
    assert normal_user.password_hash != "oldhash"


def test_reset_password_writes_audit_log(db_session, admin_user, normal_user):
    admin_service.reset_user_password(
        db_session, actor=admin_user, user_id=normal_user.id, new_password="FreshPass9!"
    )
    logs = list(db_session.scalars(sqlalchemy.select(AuditLog)))
    assert len(logs) == 1
    log = logs[0]
    assert log.action == "reset_password"
    assert log.target_type == "user"
    # 关键：detail 不含新密码明文
    assert "new_password" not in (log.detail or {})
    assert log.detail.get("reset") is True


# ── 404：用户不存在 ──

def test_set_status_user_not_found(db_session, admin_user):
    with pytest.raises(NotFoundError):
        admin_service.set_user_status(
            db_session, actor=admin_user, user_id=uuid.uuid4(), status="disabled"
        )


def test_reset_password_user_not_found(db_session, admin_user):
    with pytest.raises(NotFoundError):
        admin_service.reset_user_password(
            db_session, actor=admin_user, user_id=uuid.uuid4(), new_password="X"
        )


# ── 审计 helper ──

def test_audit_log_redacts_api_key(db_session, admin_user):
    """审计 helper 直接调用：detail 不含 api_key 明文。"""
    admin_service._audit(
        db_session,
        actor=admin_user,
        action="set_global_llm",
        target_type="system_setting",
        target_id="llm_global_config",
        detail={"model": "glm-4-flash", "base_url": "https://x", "enabled": True},
    )
    log = db_session.scalar(sqlalchemy.select(AuditLog))
    assert log is not None
    assert "api_key" not in (log.detail or {})
    assert log.detail["model"] == "glm-4-flash"
    assert log.actor_email == admin_user.email
