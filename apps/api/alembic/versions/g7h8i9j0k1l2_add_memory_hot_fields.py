"""add hit_count/last_hit_at to user_memories for hot eviction

Revision ID: g7h8i9j0k1l2
Revises: a55afec3993e
Create Date: 2026-07-30

为 user_memories 加热度字段（v1.1 记忆淘汰）：
- hit_count: 被 search_memories 命中的累计次数
- last_hit_at: 最近一次命中时间（NULL = 从未命中/刚创建）

注：原 down_revision=e371fa7db6da，merge main 时该节点已并入 a55afec3993e
（mcp_servers + drop_rerank 的 merge head）。改接 a55afec3993e 消除分叉，
形成单一线性链：... → a55afec3993e → g7h8i9j0k1l2。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "a55afec3993e"
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
