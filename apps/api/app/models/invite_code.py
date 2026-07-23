"""邀请码（内部产品化：关闭开放注册，admin 发号）。

内部小团队场景：开放注册关闭后，新账号两种途径——
1. admin 在后台直接创建（POST /admin/users）
2. admin 生成邀请码发给同事，同事凭码自助注册

生命周期：生成 → 核销（注册时 used_count+1）→ 可吊销（revoked_at）。
max_uses 控制单码可用次数（默认 1，可设多次用）。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class InviteCode(Base, IdMixin, TimestampMixin):
    __tablename__ = "invite_codes"

    # 8 位大写字母+数字（剔除易混淆 0O1I），unique
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 创建者（admin）。SET NULL：admin 删除后邀请码仍可追溯
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 最大可用次数，默认 1
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    # 已用次数
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    # 过期时间，nullable（不过期）；默认由 service 层填 7 天后
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 吊销时间，nullable（未吊销）
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
