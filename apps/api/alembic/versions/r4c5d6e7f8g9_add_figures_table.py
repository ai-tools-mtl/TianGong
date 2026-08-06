"""add figures table

Revision ID: r4c5d6e7f8g9
Revises: a65e423571e9
Create Date: 2026-08-06

新增 figures 表：AI 生成的专利附图（drawio XML 源 + 渲染产物 PNG 关联）。
- 渲染产物 PNG 复用现有 attachments 记录，figures.attachment_id 关联它
  （ondelete SET NULL：附件删除时保留 XML 源，可重新生成）
- drawio_xml：可编辑源文件，支持「重新生成」「导出回 draw.io 编辑」
- prompt：生成时的用户描述；diagram_type：图类型（flowchart/architecture/...）

专利交底书的「附图说明」章节（seed order=7, key=drawings）支持 AI 一键生成附图。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r4c5d6e7f8g9"
down_revision: Union[str, Sequence[str], None] = "a65e423571e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "figures",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("section_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sections.id", ondelete="CASCADE"), nullable=True),
        sa.Column("attachment_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.Column("drawio_xml", sa.Text, nullable=False),
        sa.Column("diagram_type", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  onupdate=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("figures")
