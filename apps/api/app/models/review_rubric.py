import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class ReviewRubric(Base, IdMixin, TimestampMixin):
    __tablename__ = "review_rubrics"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(20))  # system / user
    name: Mapped[str] = mapped_column(String(100))
    criteria: Mapped[list] = mapped_column(JSONType)
    is_customized: Mapped[bool] = mapped_column(Boolean, default=False)
