import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class ProjectTerm(Base, IdMixin, TimestampMixin):
    """项目级术语表（T2 spec §3.3.1）。

    一件专利一套术语体系，天然归属案件（D4：项目级而非用户级/全局库）。
    机器可检查的强约束：variants（禁用变体）可被 terms/check 规则路扫描，
    与 WritingProfile.terminology（用户级自由文本软偏好）并存——项目级优先。

    注入：context_assembler 每次 chat/generate/revise 装配时现查（动态生效），
    仅 enabled 条目，上限 100 条（超限截断 + warning）。
    """
    __tablename__ = "project_terms"
    __table_args__ = (
        UniqueConstraint("project_id", "term", name="uq_project_terms_project_term"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # 标准术语（唯一正确写法，写作必须使用）
    term: Mapped[str] = mapped_column(String(100), nullable=False)
    # 术语定义（注入上下文，建议简短；超 200 字由注入层截断）
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 禁用变体/同义词/错别字列表（JSONB；规则路子串扫描对象——命中即提示误用）
    variants: Mapped[list | None] = mapped_column("variants", JSONType, nullable=False, default=list)
    # 停用条目不注入、不参与检查
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # manual：用户手填；ai：AI 抽取候选勾选入库
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
