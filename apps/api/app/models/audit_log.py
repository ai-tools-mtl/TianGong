"""审计日志：管理员操作记录（设计 8.2⑤）。

detail 绝不存 api_key 等敏感明文（脱敏在 service 层强制）。
actor_email 冗余存储：用户删除后审计仍可查。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType


class AuditLog(Base, IdMixin):
    __tablename__ = "audit_logs"

    # FK SET NULL：用户删除后审计保留，actor_email 冗余兜底
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_email: Mapped[str] = mapped_column(String(255))  # 冗余，防用户删除后查不到
    action: Mapped[str] = mapped_column(String(100))  # ban_user/reset_password/set_global_llm/...
    target_type: Mapped[str] = mapped_column(String(50))  # user/system_setting
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # 变更摘要，脱敏后
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
