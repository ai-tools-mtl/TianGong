import enum
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ConversationStatus(str, enum.Enum):
    """会话状态：
    - draft：刚创建的草稿会话（占位标题「新会话」），首条对话后转 active
    - active：已产生对话的正式会话（标题已由 LLM 总结或用户重命名）
    """
    draft = "draft"
    active = "active"


# 会话类型
KIND_PROJECT = "project"
KIND_INIT = "init"


class Conversation(Base, IdMixin, TimestampMixin):
    """AI 对话会话。

    两类：
    - kind='project'：项目内对话，挂 section_id（兼容旧逻辑）。
    - kind='init'：项目初始化对话（顶层会话），section_id=NULL，user_id 记归属；
      project_id 在落地成项目后填上（落地后从助手列表消失）。
    """
    __tablename__ = "conversations"

    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    status: Mapped[str] = mapped_column(
        String(20), default=ConversationStatus.draft.value, index=True
    )
    # 会话类型：project（项目内）/ init（初始化助手顶层会话）
    kind: Mapped[str] = mapped_column(String(20), default="project")
    # init 会话落地成项目后记下（落地后列表 WHERE project_id IS NULL 不再命中）
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 顶层 init 会话归属（init 会话无 section 可反查，必须直接记 user_id）
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
