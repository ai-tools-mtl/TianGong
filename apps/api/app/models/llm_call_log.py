"""LLM 调用日志（仅元数据，设计 8.3 红线：绝不存 prompt/completion 内容）。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType


class LLMCallLog(Base, IdMixin):
    __tablename__ = "llm_call_logs"

    # 无 FK 级联：日志需独立留存；user_id 可空（全局配置时无归属用户概念）
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(50))  # chat/generate/rewrite/review/embed
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(20))  # user/global
    token_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # success/failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 不含内容
    # 上下文压缩观测（spec §5.1）：Snapshot 序列化。nullable（未压缩或旧记录为空）。
    context_meta: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
