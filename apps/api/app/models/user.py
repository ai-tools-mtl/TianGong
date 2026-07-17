import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # 登录标识
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)  # 可选联系方式
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))

    # 角色：user / admin（MVP）；预留 org_admin（P2+）
    role: Mapped[str] = mapped_column(String(20), default="user")
    # 状态：active / disabled
    status: Mapped[str] = mapped_column(String(20), default="active")
    # 所属组织（预留，MVP 为 NULL）
    org_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # 首个超管标记（命令行创建）
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
