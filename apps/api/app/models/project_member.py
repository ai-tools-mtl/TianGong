import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ProjectMember(Base, IdMixin, TimestampMixin):
    """项目协作者（注册用户，reviewer 角色）。

    owner 通过邮箱邀请已注册用户加入项目，获得 comment 权限（可批注）。
    与 ShareLink（访客链接）互补：前者面向注册用户，后者面向未注册访客。
    """
    __tablename__ = "project_members"
    __table_args__ = (
        # 同一项目内同一用户只能有一条记录
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 角色：reviewer（默认）/ 预留 editor
    role: Mapped[str] = mapped_column(String(20), default="reviewer")
