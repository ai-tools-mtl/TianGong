"""AI 输出反馈（借鉴机制批次 H）。

用户对持久化的 assistant 消息给 👍/👎 + 归因标签 + 可选备注；同人同消息
upsert 覆盖（内测期信号新鲜度优先，简化统计口径）。

定位红线：
- 反馈是**信号不是控制器**——不自动触发审查、不驱动 prompt 自动调优（人在环）。
- 与 eval 的衔接只留锚点：坏评聚集的消息是未来 samples.py 候选，人工挑选，
  不自动搬运。
- log-only：不进入模型上下文（与 hitl_decisions 同一戒律）。
"""
import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin

# 归因标签封闭集（前端快选；服务端白名单校验）
ALLOWED_FEEDBACK_TAGS = ("错字", "事实", "格式", "没帮助")


class MessageFeedback(Base, IdMixin, TimestampMixin):
    __tablename__ = "message_feedbacks"
    __table_args__ = (
        # 同人同消息一行：重复评价 upsert 覆盖，不留历史（内测期口径）
        UniqueConstraint("message_id", "user_id", name="uq_feedback_message_user"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    # 无 FK（同 LLMCallLog 口径）：用户删除后反馈行独立留存供聚合
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    rating: Mapped[str] = mapped_column(String(10))  # good / bad
    # JSON 数组，元素 ∈ ALLOWED_FEEDBACK_TAGS；good 评价通常为空
    tags: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
