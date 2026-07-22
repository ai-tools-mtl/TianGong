# apps/api/app/models/skill.py
"""Agent Skill 模型（spec 合规，两档可见性）。

替代旧 AgentSkill（project-scoped 覆盖）。新模型：skill 定义本身归属
admin 全局（scope=global, owner_id=NULL）或用户个人（scope=personal）。
详见 spec §5.1。
"""
import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

# 可见性两档
SCOPE_GLOBAL = "global"
SCOPE_PERSONAL = "personal"

# 状态：draft 不进 runtime，active 进
STATUS_DRAFT = "draft"
STATUS_ACTIVE = "active"


class Skill(Base, IdMixin, TimestampMixin):
    """一个 Agent Skill = 一份 spec 合规的 SKILL.md 目录树 + 元数据。

    - scope/owner_id 联合表达可见性：global 时 owner_id=NULL，personal 时必填。
    - status=draft 不进 runtime 可见集合（admin/用户编辑中不喂 agent）。
    - minio_prefix 指向 MinIO 中该 skill 的目录前缀（SKILL.md + scripts/ + ...）。
    """
    __tablename__ = "skills"
    __table_args__ = (
        # 同一 scope + owner 下 name 唯一（global 时 owner_id 视为 NULL 统一）
        Index("uix_skill_scope_owner_name", "scope", "owner_id", "name", unique=True),
    )

    name: Mapped[str] = mapped_column(String(64))  # spec name, [a-z0-9-], ≤64
    description: Mapped[str] = mapped_column(Text)  # ≤1024，单行（触发条件）
    scope: Mapped[str] = mapped_column(String(20))  # global / personal
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=STATUS_DRAFT)
    minio_prefix: Mapped[str] = mapped_column(String(255))
