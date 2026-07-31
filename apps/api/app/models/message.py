import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class Message(Base, IdMixin, TimestampMixin):
    __tablename__ = "messages"

    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    # agent 透明化元数据（Task 23 + 思考过程透传）：
    #   { "tool_events": [{"kind":"call"|"result","name",...}], "thinking": str }
    # tool_events 记录本轮工具调用/返回序列；thinking 存模型推理过程。
    # 仅 assistant 消息可能非空，user 恒为 NULL。可空——旧消息无此列、
    # 无 agent loop 的路径（rewrite）也不填。JSONType 跨方言（GOTCHAS G2）。
    meta: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
