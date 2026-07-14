import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class UserLLMConfig(Base, IdMixin, TimestampMixin):
    __tablename__ = "user_llm_configs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), default="custom")
    base_url: Mapped[str] = mapped_column(String(255))
    api_key_encrypted: Mapped[str] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(100))
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
