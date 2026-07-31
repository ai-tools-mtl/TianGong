"""assistant conversations: kind/project_id/user_id + section_id nullable

Revision ID: b7c8d9e0f1a2
Revises: a55afec3993e
Create Date: 2026-07-31

顶层 init 会话：Conversation.section_id 改可空（init 会话不挂 section），
加 kind（project/init）、project_id（落地标记）、user_id（归属）。
Message.section_id 同改可空。老数据 backfill kind='project' + user_id。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # conversations: 加列 + section_id 改 nullable
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=20), nullable=False, server_default='project'))
        batch_op.add_column(sa.Column('project_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
        batch_op.add_column(sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
        batch_op.alter_column('section_id', existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)
    op.create_index('ix_conversations_kind', 'conversations', ['kind'])
    op.create_index('ix_conversations_project_id', 'conversations', ['project_id'])
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])
    op.create_foreign_key('fk_conversations_project_id', 'conversations', 'projects', ['project_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_conversations_user_id', 'conversations', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # messages: section_id 改 nullable
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('section_id', existing_type=sa.Uuid(), nullable=True)

    # backfill user_id：老会话由 section_id → project → user 反查
    op.execute(
        "UPDATE conversations c SET user_id = p.user_id "
        "FROM sections s, projects p "
        "WHERE c.section_id = s.id AND s.project_id = p.id AND c.user_id IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint('fk_conversations_user_id', 'conversations', type_='foreignkey')
    op.drop_constraint('fk_conversations_project_id', 'conversations', type_='foreignkey')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_index('ix_conversations_project_id', table_name='conversations')
    op.drop_index('ix_conversations_kind', table_name='conversations')
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('section_id', existing_type=sa.Uuid(), nullable=False)
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.alter_column('section_id', existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=False)
        batch_op.drop_column('user_id')
        batch_op.drop_column('project_id')
        batch_op.drop_column('kind')
