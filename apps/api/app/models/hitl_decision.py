"""HITL 决策审计（借鉴机制批次 C，log-only）。

interrupt 发生时落一行 pending（asked），用户决策后更新为 approve/reject。
**绝不进入模型上下文**——history 从 messages 表按 role/content 重建，
本表仅供审计与 UI 回放；写一条单测钉死这一边界（见 tests/test_hitl_audit.py）。

design 摘要（2026-08-27-harness-mechanisms-adoption-plan.md 批次 C）：
- 双事件形态：ask 与 decide 各留痕，只记 decided 的半套实现看不见「从不回复的
  悬挂审批」，而它们恰是审核卡点的真实信号。
- 每次 ask 新插一行（同一 turn 反复触发同工具的多次询问全量留痕），decide 只翻新
  该 turn 下仍为 pending 的行——重复 decide 幂等。
- fail-open：审计写入失败不阻断对话主流程（调用方 try/except）。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class HitlDecision(Base, IdMixin, TimestampMixin):
    __tablename__ = "hitl_decisions"

    # 该 turn 的锚点消息 = chat 端点的 checkpoint thread 约定里的 user 消息 id
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100))
    # created_at 即 ask 时间（TimestampMixin）；decision 三态：pending/approve/reject
    decision: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
