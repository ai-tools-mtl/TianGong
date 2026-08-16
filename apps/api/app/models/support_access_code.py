"""经授权临时查看授权码（设计 §8.3 完整版）。

用户主动求助时生成一次性短码发给管理员；管理员凭码在限时窗口内查看
该用户指定项目的只读视图，全程写审计日志。与游客浏览（ShareLink 公开
token）正交：那个面向匿名访客、可多次访问、无审计；这个面向 admin、
一次性核销 + 换后限时查看窗口 + 每次访问审计。

生命周期：生成（默认 30 分钟有效）→ admin 核销（redeemed_at+redeemed_by，
仅一次，核销即开 30 分钟查看窗口 view_expires_at）→ 窗口内该 admin 可
反复查看 → 过期/吊销终结。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class SupportAccessCode(Base, IdMixin, TimestampMixin):
    __tablename__ = "support_access_codes"

    # 8 位大写字母+数字（剔除易混淆 0O1I，同 InviteCode 字母表），unique
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 目标项目（被查看的交底书项目）
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 发起人 = 求助用户本人（owner）。CASCADE：用户删除连带其授权码
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 码本身的有效期（生成时刻起算，默认 30 分钟；未被核销即失效）
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 核销时间（admin 首次凭码查看）。一次性语义：非空后不可再核销
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 核销的 admin。查看窗口只对该 admin 开放
    redeemed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # 查看窗口截止（核销时刻起算，默认 30 分钟）
    view_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 吊销时间（用户可随时撤销对 admin 的授权）
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
