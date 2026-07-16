"""知识库上报审核工单(计划 T5)。

双审核流共用此表,靠 source_type 区分(关键约束 2):
- disclosure_export: 归档交底书 → 全局
- external: 外部导入素材 → 全局
状态机:pending → approved / rejected(借鉴 parse_job 状态机模式)。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class KnowledgeReview(Base, IdMixin, TimestampMixin):
    __tablename__ = "knowledge_reviews"

    submitter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(30))
    # disclosure_export(归档流) / external(外部导入流)
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_files.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending / approved / rejected
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
