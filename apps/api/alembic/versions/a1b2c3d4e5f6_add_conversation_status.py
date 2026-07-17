"""add conversation status column

Revision ID: a1b2c3d4e5f6
Revises: e7f8a9b0c1d2
Create Date: 2026-07-17 12:00:00.000000

为 conversations 表新增 status 列（draft/active），并：
1. 把已有会话的 title 默认值从「新对话」改为「新会话」
2. 已有会话（title != '新会话'）标记为 active，否则 draft
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 加 status 列，默认 draft（新会话草稿态）
    op.add_column(
        'conversations',
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
    )
    op.create_index('ix_conversations_status', 'conversations', ['status'])

    # 2. 改 title 默认值从「新对话」为「新会话」
    op.alter_column(
        'conversations', 'title',
        server_default="'新会话'::character varying",
    )

    # 3. 已有会话：有实际标题的标记 active，标题仍是「新对话」/「新会话」的保持 draft
    op.execute(
        "UPDATE conversations SET status = 'active' WHERE title NOT IN ('新对话', '新会话')"
    )


def downgrade() -> None:
    op.drop_index('ix_conversations_status', table_name='conversations')
    op.drop_column('conversations', 'status')
    op.alter_column(
        'conversations', 'title',
        server_default="'新对话'::character varying",
    )
