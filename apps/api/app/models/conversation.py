import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Conversation(Base, IdMixin, TimestampMixin):
    """AI 对话会话（一个 section 下可有多个会话，类似 ChatGPT 会话列表）。"""
    __tablename__ = "conversations"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="新对话")
