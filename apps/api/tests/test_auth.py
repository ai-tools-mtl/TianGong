import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.models import Base
from app.services.auth_service import authenticate_user, register_user


@pytest.fixture
def db():
    """每测试独立 sqlite 内存库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def test_authenticate_user_success(db):
    register_user(db, username="alice", password="Pass1234!", name="A")
    user = authenticate_user(db, username="alice", password="Pass1234!")
    assert user is not None
    assert user.username == "alice"


def test_authenticate_user_wrong_password(db):
    register_user(db, username="alice", password="Pass1234!", name="A")
    assert authenticate_user(db, username="alice", password="wrong") is None


def test_authenticate_user_not_found(db):
    assert authenticate_user(db, username="nobody", password="x") is None


def test_register_duplicate_username_raises(db):
    register_user(db, username="alice", password="Pass1234!", name="A")
    with pytest.raises(ConflictError):
        register_user(db, username="alice", password="Pass1234!", name="B")
