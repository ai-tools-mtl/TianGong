"""User 模型 username 登录标识改造测试（阶段 1）。"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import User


def test_user_has_username_field():
    """User 必须有 username 字段。"""
    u = User(username="alice", password_hash="x", name="Alice")
    assert u.username == "alice"


def test_user_email_is_optional():
    """email 可选（nullable）。"""
    u = User(username="bob", password_hash="x", name="Bob")  # 不传 email
    assert u.email is None  # 默认 None


def test_username_unique(db_session):
    """username 唯一约束。"""
    db_session.add(User(username="dup", password_hash="x", name="A"))
    db_session.commit()
    db_session.add(User(username="dup", password_hash="x", name="B"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_email_not_unique(db_session):
    """email 不再唯一（可重复）。"""
    db_session.add(User(username="u1", email="same@test.com", password_hash="x", name="A"))
    db_session.add(User(username="u2", email="same@test.com", password_hash="x", name="B"))
    db_session.commit()  # 不应抛 IntegrityError
    assert db_session.query(User).filter_by(email="same@test.com").count() == 2
