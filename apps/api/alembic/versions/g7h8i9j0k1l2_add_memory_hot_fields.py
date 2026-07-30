"""add hit_count/last_hit_at to user_memories for hot eviction

Revision ID: g7h8i9j0k1l2
Revises: e371fa7db6da
Create Date: 2026-07-30

为 user_memories 加热度字段（v1.1 记忆淘汰）：
- hit_count: 被 search_memories 命中的累计次数
- last_hit_at: 最近一次命中时间（NULL = 从未命中/刚创建）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "e371fa7db6da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_memories",
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "user_memories",
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_memories", "last_hit_at")
    op.drop_column("user_memories", "hit_count")
