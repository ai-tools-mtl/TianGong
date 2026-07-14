from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.core.security import hash_password, verify_password
from app.models import User


def register_user(db: Session, *, email: str, password: str, name: str) -> User:
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise ConflictError(f"邮箱 {email} 已注册")
    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        return None
    if user.status != "active":
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def update_last_login(db: Session, user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
