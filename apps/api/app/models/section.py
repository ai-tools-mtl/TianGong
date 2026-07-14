import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class Section(Base, IdMixin, TimestampMixin):
    __tablename__ = "sections"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    template_section_id: Mapped[str] = mapped_column(String(100))
    order: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # Tiptap JSON
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="empty")  # empty/drafting/confirmed
    # 乐观锁版本号：每次 PATCH 成功 +1；并发更新冲突返回 409（设计 13.4）
    version: Mapped[int] = mapped_column(Integer, default=1)
