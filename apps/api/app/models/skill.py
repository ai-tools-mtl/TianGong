# apps/api/app/models/skill.py
"""Agent Skill 模型（spec 合规，两档可见性）。

替代旧 AgentSkill（project-scoped 覆盖）。新模型：skill 定义本身归属
admin 全局（scope=global, owner_id=NULL）或用户个人（scope=personal）。
详见 spec §5.1。
"""
import uuid

from sqlalchemy import ForeignKey, Index, String, Text, text
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
    - 唯一性通过两个 partial index 实现（SQL NULL 视为 distinct，无法用单一复合
      索引覆盖 global 档）：global 对 name 唯一、personal 对 (owner_id, name) 唯一。
    """
    __tablename__ = "skills"
    __table_args__ = (
        # global skill：owner_id 恒为 NULL，SQL 标准里 NULL 视为 distinct，
        # 故用 partial index 在 scope='global' 时对 name 单独唯一
        Index(
            "uix_skill_global_name",
            "name",
            unique=True,
            sqlite_where=text("scope = 'global'"),
            postgresql_where=text("scope = 'global'"),
        ),
        # personal skill：owner_id 非 NULL，partial index 在 scope='personal' 时
        # 对 (owner_id, name) 唯一
        Index(
            "uix_skill_personal_owner_name",
            "owner_id", "name",
            unique=True,
            sqlite_where=text("scope = 'personal'"),
            postgresql_where=text("scope = 'personal'"),
        ),
    )

    name: Mapped[str] = mapped_column(String(64))  # spec name, [a-z0-9-], ≤64
    description: Mapped[str] = mapped_column(Text)  # ≤1024，单行（触发条件）
    scope: Mapped[str] = mapped_column(String(20))  # global / personal
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=STATUS_DRAFT)
    minio_prefix: Mapped[str] = mapped_column(String(255))
