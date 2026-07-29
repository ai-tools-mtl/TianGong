"""add user_memories table for long-term memory

Revision ID: e1m2e3m4o5r6
Revises: fbb0392f6703
Create Date: 2026-07-28

列类型严格对齐 IdMixin/TimestampMixin(base.py) + c3d4e5f6a7b8 范式:
- id = sa.Uuid()
- timestamps = sa.DateTime(timezone=True) server_default now() NOT NULL
- embedding = HalfVec(2048), 与 knowledge_chunks 同维

注：原 down_revision=d1h2n3s4w5i6（分叉自 HNSW 迁移）。合并 main 的
rag-hybrid-retrieval + drop-user-embedding-configs 链路后，rebase 到
main 当前 head fbb0392f6703，形成线性迁移链（消除分叉 head）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC as HalfVec


revision: str = "e1m2e3m4o5r6"
down_revision: Union[str, Sequence[str], None] = "fbb0392f6703"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", HalfVec(2048), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="agent"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_user_memories_user_updated", "user_memories", ["user_id", "updated_at"]
    )
    # HNSW 索引（cosine，与 knowledge_chunks 同款参数）
    op.execute(
        "CREATE INDEX ix_user_memories_embedding_hnsw ON user_memories "
        "USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    # HNSW 索引用 raw-SQL DROP IF EXISTS，对齐 d1h2n3s4w5i6 参考。
    op.execute("DROP INDEX IF EXISTS ix_user_memories_embedding_hnsw")
    op.drop_index("ix_user_memories_user_updated", table_name="user_memories")
    op.drop_table("user_memories")
