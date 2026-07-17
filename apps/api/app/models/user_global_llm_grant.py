"""用户全局 LLM Key 白名单授权（P2）。

admin 配置一把全局 Key 后，逐用户授权才能使用。
撤销 = 写 revoked_at（保留行，留审计痕迹）。
user_id unique：一个用户最多一条有效授权。
admin 角色免授权（代码层 role=='admin' 判断，不进此表）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class UserGlobalLLMGrant(Base, IdMixin, TimestampMixin):
    __tablename__ = "user_global_llm_grants"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
