"""add figure.style column

Revision ID: s5d6e7f8g9h1
Revises: s5l6o7g8i9j0
Create Date: 2026-08-10

为 figures 表加 style 列（风格预设：patent-bw/clean-color/technical）。
patent-bw（专利黑白）为默认，符合中国专利局《专利审查指南》正式申请标准。
NOT NULL + server_default 保证已有 figures 行迁移不失败。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s5d6e7f8g9h1"
down_revision: Union[str, Sequence[str], None] = "s5l6o7g8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "figures",
        sa.Column("style", sa.String(30), nullable=False, server_default="patent-bw"),
    )


def downgrade() -> None:
    op.drop_column("figures", "style")
