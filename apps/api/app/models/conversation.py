import enum
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ConversationStatus(str, enum.Enum):
    """会话状态：
    - draft：刚创建的草稿会话（占位标题「新会话」），首条对话后转 active
    - active：已产生对话的正式会话（标题已由 LLM 总结或用户重命名）
    """
    draft = "draft"
    active = "active"


class Conversation(Base, IdMixin, TimestampMixin):
    """AI 对话会话（一个 section 下可有多个会话，类似 ChatGPT 会话列表）。"""
    __tablename__ = "conversations"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    status: Mapped[str] = mapped_column(
        String(20), default=ConversationStatus.draft.value, index=True
    )
