import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ShareLink(Base, IdMixin, TimestampMixin):
    """项目分享链接（面向未注册访客）。

    token 为 uuid4().hex（32 位十六进制），拼接在公开 URL 里供访客访问。
    permissions 限定访客在 Collabora 中的能力：comment（批注）/ readonly（只读）。
    expires_at 为空表示永不过期。
    """
    __tablename__ = "share_links"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # 32 位十六进制（uuid4().hex），无连字符，URL 安全
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # comment / readonly
    permissions: Mapped[str] = mapped_column(String(20), default="comment")
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
