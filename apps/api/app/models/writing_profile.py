import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import UniqueConstraint

from app.models.base import Base, IdMixin, JSONType, TimestampMixin

# 专业水平三档（影响表达密度指令：novice 通俗化 / intermediate 默认 / expert 高密度术语）
PROFICIENCY_NOVICE = "novice"            # 初学者（发明人/技术新人）
PROFICIENCY_INTERMEDIATE = "intermediate"  # 一般技术人员
PROFICIENCY_EXPERT = "expert"            # 专家（专利代理人/律师）


class WritingProfile(Base, IdMixin, TimestampMixin):
    """用户写作画像（一对一，用户显式维护的结构化偏好）。

    与 user_memory(source=profile) 的区别：
    - 本表：结构化字段（5 个固定维度），用户在 /settings/profile 显式填写，
      每次 LLM 生成时全量强注入 system prompt（不走语义检索，保证稳定生效）。
    - user_memory：自由文本记忆（agent 自动/手动），走语义检索按相关性注入。

    设计依据：MVP 设计 §10.8 画像四维度（writing_style/tech_domain/terminology/preference）
    + prompt-content spec §S2-3 专业水平维度。本表为结构化落地，与 user_memory 并存。

    一对一：user_id UNIQUE 约束，每用户至多一条记录。
    """
    __tablename__ = "writing_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_writing_profiles_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 职业身份（如「专利代理人」「发明人」「研发工程师」），驱动表达密度指令
    profession: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 技术领域（如「机械」「半导体」「新能源电池」），帮 agent 理解领域语境
    tech_domain: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 专业水平三档，驱动术语密度：novice 通俗 / intermediate 默认 / expert 高密度
    proficiency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 写作风格偏好（自由文本，如「简洁直接，少用形容词」「详尽覆盖每个细节」）
    writing_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 术语偏好（自由文本，如「用 5G 不用蜂窝」「权利要求用「所述」」）
    terminology: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 扩展自由字段（预留，暂不用）
    extras: Mapped[dict | None] = mapped_column("extras", JSONType, nullable=True)
