"""add tsv tsvector column + GIN index on knowledge_chunks

Revision ID: e3r4a5g6t7s8v
Revises: d1h2n3s4w5i6
Create Date: 2026-07-28

spec: docs/superpowers/specs/2026-07-27-ragflow-borrow-design.md §5.3 阶段1
为 BM25 关键词路召回加 tsvector 列 + GIN 索引。
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'e3r4a5g6t7s8v'
down_revision: Union[str, Sequence[str], None] = 'd1h2n3s4w5i6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN tsv tsvector")
    op.execute("CREATE INDEX ix_knowledge_chunks_tsv_gin ON knowledge_chunks USING gin (tsv)")
    # 回填存量数据
    op.execute("UPDATE knowledge_chunks SET tsv = to_tsvector('simple', coalesce(content, ''))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_tsv_gin")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS tsv")
