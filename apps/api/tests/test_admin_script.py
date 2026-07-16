import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import verify_password
from app.models import Base, User
from scripts.create_admin import create_admin


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    session = S()
    yield session
    session.close()


def test_create_admin_creates_admin_user(db):
    create_admin(db, username="admin", password="AdminPass1!")
    user = db.scalar(select(User).where(User.username == "admin"))
    assert user is not None
    assert user.role == "admin"
    assert user.is_superuser is True
    assert user.status == "active"


def test_create_admin_idempotent(db):
    create_admin(db, username="admin", password="AdminPass1!")
    create_admin(db, username="admin", password="Different2!")
    user = db.scalar(select(User).where(User.username == "admin"))
    # 密码不被覆盖（幂等）
    assert verify_password("AdminPass1!", user.password_hash)
