import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

# 生产用 JSONB（PG 原生、索引优化），sqlite 测试降级为 JSON
_JSONType = JSONB().with_variant(JSON, "sqlite")


class Project(Base, IdMixin, TimestampMixin):
    __tablename__ = "projects"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    # 生命周期阶段：disclosure(MVP) / application / examination / archive
    stage: Mapped[str] = mapped_column(String(20), default="disclosure")
    # 状态：draft / in_progress / completed / archived
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_section_order: Mapped[int] = mapped_column(Integer, default=1)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", _JSONType, nullable=True)
    prior_art_refs: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
