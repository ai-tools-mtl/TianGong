import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class Template(Base, IdMixin, TimestampMixin):
    __tablename__ = "templates"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    structure: Mapped[list] = mapped_column(JSONType)   # TemplateSection 数组
    styles: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    numbering: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
