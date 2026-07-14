import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class SectionVersion(Base, IdMixin, TimestampMixin):
    __tablename__ = "section_versions"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(20), default="manual")  # auto / manual
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
