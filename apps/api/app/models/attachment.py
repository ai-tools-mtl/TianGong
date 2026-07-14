import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Attachment(Base, IdMixin, TimestampMixin):
    """附件/附图（设计 3.2）。本地存储，UUID 命名防路径遍历。"""
    __tablename__ = "attachments"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))  # 原始文件名（仅展示）
    storage_path: Mapped[str] = mapped_column(String(512))  # UUID 存储名
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
