"""add chunk intervention fields (keywords/questions/weight/edited_text/locked)

Revision ID: f4g5i6n7t8e9
Revises: e3r4a5g6t7s8v
Create Date: 2026-07-28

spec: docs/superpowers/specs/2026-07-27-ragflow-borrow-design.md §5.4 (G4, D3)
G4 分块干预字段（独立列，可建索引）：
- keywords JSON：检索加权关键词（参与关键词路召回）
- questions JSON：预设问题（参与关键词路召回）
- weight Float：召回分数乘子（默认 1.0）
- edited_text Text：admin 手动改写文本（None=用原 content）
- locked Boolean：锁定后重新 ingest 不覆盖
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4g5i6n7t8e9'
down_revision: Union[str, Sequence[str], None] = 'e3r4a5g6t7s8v'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('knowledge_chunks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('keywords', sa.dialects.postgresql.JSONB().with_variant(sa.JSON(), 'sqlite'), nullable=True))
        batch_op.add_column(sa.Column('questions', sa.dialects.postgresql.JSONB().with_variant(sa.JSON(), 'sqlite'), nullable=True))
        batch_op.add_column(sa.Column('weight', sa.Float(), nullable=True, server_default='1.0'))
        batch_op.add_column(sa.Column('edited_text', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    with op.batch_alter_table('knowledge_chunks', schema=None) as batch_op:
        batch_op.drop_column('locked')
        batch_op.drop_column('edited_text')
        batch_op.drop_column('weight')
        batch_op.drop_column('questions')
        batch_op.drop_column('keywords')
