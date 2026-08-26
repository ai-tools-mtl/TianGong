"""add figures.number（图号系统 V1）

Revision ID: b3c4d5e6f7g8
Revises: a8b9c0d1e2f3
Create Date: 2026-08-26

《专利审查指南》要求图按顺序编号。加项目内连续图号（1 起）：
- 存量按 created_at 顺序回填；
- 唯一约束 (project_id, number) 兜底并发分配（服务端 max+1 分配 + 删除重排）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7g8"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("figures", sa.Column("number", sa.Integer(), nullable=True))
    # 回填：每项目按创建顺序 1..n
    op.execute(sa.text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY project_id ORDER BY created_at, id
                   ) AS rn
            FROM figures
        )
        UPDATE figures SET number = ranked.rn FROM ranked WHERE figures.id = ranked.id
    """))
    op.alter_column("figures", "number", nullable=False)
    op.create_unique_constraint(
        "uq_figures_project_number", "figures", ["project_id", "number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_figures_project_number", "figures", type_="unique")
    op.drop_column("figures", "number")
