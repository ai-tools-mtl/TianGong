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
    # 请求链路追踪：由 RequestIDMiddleware 写入 contextvar，helper 落库。
    # 可空（历史数据 / 非请求上下文的后台任务）。实现「日志 ↔ LLM 调用记录」跨表关联。
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    token_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 批次 A（A-3）：prompt 中命中供应商前缀缓存的 token 数（DeepSeek cache hit /
    # OpenAI cached_tokens 形态）。provider 不回传时为 None——prefix cache 改造的
    # 验收与成本观测指标来源。
    token_prompt_cached: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # success/failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 不含内容
    # 上下文压缩观测（spec §5.1）：Snapshot 序列化。nullable（未压缩或旧记录为空）。
    context_meta: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
