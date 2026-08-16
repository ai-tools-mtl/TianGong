"""add cross_section_issues + section_issues to review_records

Revision ID: v7w8x9y0z1b2
Revises: s5d6e7f8g9h1
Create Date: 2026-08-11

为 review_records 加两列：
- cross_section_issues：跨章节一致性检查结果（术语不一致/引用错位/逻辑矛盾）
- section_issues：问题按章节定位聚合

两者均 JSONB，default '[]'，已有 review_records 行迁移不失败。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "v7w8x9y0z1b2"
down_revision: Union[str, Sequence[str], None] = "s5d6e7f8g9h1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "review_records",
        sa.Column(
            "cross_section_issues",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "review_records",
        sa.Column(
            "section_issues",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("review_records", "section_issues")
    op.drop_column("review_records", "cross_section_issues")
