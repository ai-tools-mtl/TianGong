import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class ReviewRecord(Base, IdMixin, TimestampMixin):
    __tablename__ = "review_records"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    rubric_snapshot: Mapped[list] = mapped_column(JSONType)
    round: Mapped[int] = mapped_column(Integer, default=1)
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    previous_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dimension_scores: Mapped[list] = mapped_column(JSONType)
    resolved_issues: Mapped[list] = mapped_column(JSONType, default=list)
    remaining_issues: Mapped[list] = mapped_column(JSONType, default=list)
