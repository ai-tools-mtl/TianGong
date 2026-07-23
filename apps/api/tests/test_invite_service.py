"""邀请码 service 层测试。"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models import InviteCode, User
from app.services import invite_service
from app.core.security import hash_password


@pytest.fixture
def admin_user(db_session):
    u = User(
        username="admin1",
        email="admin@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="管理员",
        role="admin",
    )
    db_session.add(u)
    db_session.commit()
    return u


def test_generate_code_returns_valid_code(db_session, admin_user):
    """生成的码 8 位,大写字母+数字,不含易混淆字符。"""
    invite = invite_service.generate_code(db_session, actor=admin_user)
    assert len(invite.code) == 8
    forbidden = set("0O1I")
    assert not (set(invite.code) & forbidden)
    assert invite.used_count == 0
    assert invite.max_uses == 1


def test_generate_code_with_custom_max_uses(db_session, admin_user):
    invite = invite_service.generate_code(db_session, actor=admin_user, max_uses=5)
    assert invite.max_uses == 5


def test_generate_code_no_expiry(db_session, admin_user):
    """expires_in_days=None 表示不过期。"""
    invite = invite_service.generate_code(db_session, actor=admin_user, expires_in_days=None)
    assert invite.expires_at is None


def test_generate_code_rejects_invalid_max_uses(db_session, admin_user):
    with pytest.raises(ForbiddenError):
        invite_service.generate_code(db_session, actor=admin_user, max_uses=0)


def test_validate_and_consume_increments_count(db_session, admin_user):
    invite = invite_service.generate_code(db_session, actor=admin_user)
    invite_service.validate_and_consume(db_session, code=invite.code)
    db_session.refresh(invite)
    assert invite.used_count == 1


def test_validate_and_consume_multi_use(db_session, admin_user):
    """max_uses=3 的码可用 3 次。"""
    invite = invite_service.generate_code(db_session, actor=admin_user, max_uses=3)
    for _ in range(3):
        invite_service.validate_and_consume(db_session, code=invite.code)
    db_session.refresh(invite)
    assert invite.used_count == 3
    # 第 4 次应失败
    with pytest.raises(ForbiddenError):
        invite_service.validate_and_consume(db_session, code=invite.code)


def test_validate_and_consume_invalid_code(db_session):
    """不存在的码核销失败。"""
    with pytest.raises(ForbiddenError):
        invite_service.validate_and_consume(db_session, code="NOSUCHCODE")


def test_validate_and_consume_expired(db_session, admin_user):
    """过期码核销失败。"""
    invite = invite_service.generate_code(db_session, actor=admin_user, expires_in_days=7)
    # 手动改过期时间为过去
    invite.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()
    with pytest.raises(ForbiddenError):
        invite_service.validate_and_consume(db_session, code=invite.code)


def test_validate_and_consume_revoked(db_session, admin_user):
    """吊销码核销失败。"""
    invite = invite_service.generate_code(db_session, actor=admin_user)
    invite_service.revoke_code(db_session, actor=admin_user, invite_id=invite.id)
    with pytest.raises(ForbiddenError):
        invite_service.validate_and_consume(db_session, code=invite.code)


def test_validate_and_consume_case_insensitive(db_session, admin_user):
    """码大小写不敏感(注册时 upper+strip)。"""
    invite = invite_service.generate_code(db_session, actor=admin_user)
    invite_service.validate_and_consume(db_session, code=invite.code.lower())
    db_session.refresh(invite)
    assert invite.used_count == 1


def test_revoke_code(db_session, admin_user):
    """吊销后状态变 revoked。"""
    invite = invite_service.generate_code(db_session, actor=admin_user)
    invite_service.revoke_code(db_session, actor=admin_user, invite_id=invite.id)
    db_session.refresh(invite)
    assert invite.revoked_at is not None
    assert invite_service.code_status(invite) == "revoked"


def test_revoke_code_idempotent(db_session, admin_user):
    """重复吊销 no-op(不报错)。"""
    invite = invite_service.generate_code(db_session, actor=admin_user)
    invite_service.revoke_code(db_session, actor=admin_user, invite_id=invite.id)
    # 再次吊销不抛错
    invite_service.revoke_code(db_session, actor=admin_user, invite_id=invite.id)


def test_revoke_nonexistent_raises(db_session, admin_user):
    with pytest.raises(NotFoundError):
        invite_service.revoke_code(db_session, actor=admin_user, invite_id=uuid.uuid4())


def test_code_status_active(db_session, admin_user):
    invite = invite_service.generate_code(db_session, actor=admin_user)
    assert invite_service.code_status(invite) == "active"


def test_code_status_exhausted(db_session, admin_user):
    invite = invite_service.generate_code(db_session, actor=admin_user)
    invite_service.validate_and_consume(db_session, code=invite.code)
    assert invite_service.code_status(invite) == "exhausted"


def test_code_status_expired(db_session, admin_user):
    invite = invite_service.generate_code(db_session, actor=admin_user, expires_in_days=7)
    invite.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    assert invite_service.code_status(invite) == "expired"


def test_list_codes_returns_all(db_session, admin_user):
    """列表返回所有邀请码。

    不断言排序顺序:SQLite 的 created_at(server_default=now)精度为秒,
    同秒创建的码排序顺序不保证。排序在生产 PG 下可靠。
    """
    i1 = invite_service.generate_code(db_session, actor=admin_user)
    i2 = invite_service.generate_code(db_session, actor=admin_user)
    codes = invite_service.list_codes(db_session)
    code_ids = {c.id for c in codes}
    assert {i1.id, i2.id} <= code_ids
