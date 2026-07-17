"""add conversations table + messages.conversation_id

Revision ID: e7f8a9b0c1d2
Revises: 4ab0b6e7413c
Create Date: 2026-07-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = '4ab0b6e7413c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建 conversations 表
    op.create_table(
        'conversations',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('section_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(255), server_default='新对话', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_conversations_section_id', 'conversations', ['section_id'])

    # 2. 为每个有消息的 section 创建默认 conversation
    op.execute("""
        INSERT INTO conversations (id, section_id, title, created_at, updated_at)
        SELECT gen_random_uuid(), section_id, '历史对话', MIN(created_at), MIN(created_at)
        FROM messages
        GROUP BY section_id
    """)

    # 3. messages 加 conversation_id 列（先 nullable，回填后再 NOT NULL）
    op.add_column('messages', sa.Column('conversation_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])

    # 4. 回填：每个 message 关联到其 section 的默认 conversation
    op.execute("""
        UPDATE messages m
        SET conversation_id = c.id
        FROM conversations c
        WHERE m.section_id = c.section_id AND c.title = '历史对话'
    """)

    # 5. 设为 NOT NULL
    op.alter_column('messages', 'conversation_id', nullable=False)

    # 6. 加 FK
    op.create_foreign_key('fk_messages_conversation_id', 'messages', 'conversations', ['conversation_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('fk_messages_conversation_id', 'messages', type_='foreignkey')
    op.drop_index('ix_messages_conversation_id', table_name='messages')
    op.drop_column('messages', 'conversation_id')
    op.drop_index('ix_conversations_section_id', table_name='conversations')
    op.drop_table('conversations')
