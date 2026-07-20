import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ParseJob(Base, IdMixin, TimestampMixin):
    __tablename__ = "parse_jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    source_path: Mapped[str] = mapped_column(String(512))
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 标记解析出的 Template 是否为系统模板（refactor/admin-ia-phase3 切片 B）。
    # admin 上传内置模板时置 True，run_parse_job 据此设 template.is_system=True + status='draft'。
    # 普通用户上传默认 False（现状）。
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
