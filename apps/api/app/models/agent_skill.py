import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class AgentSkill(Base, IdMixin, TimestampMixin):
    """项目级技能开关。每行 = 某项目对某 builtin 技能的覆盖；缺行 = 用默认。"""
    __tablename__ = "agent_skills"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    skill_key: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
