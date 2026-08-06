"""add user_ima_configs

Revision ID: u1m2a3s4o5u6
Revises: o1a2b3c4d5e6
Create Date: 2026-07-31 12:00:00.000000

新增用户腾讯 ima 检索源凭据表（单配置语义，user_id 唯一）。
用于 ima 知识库作为实时外部检索源。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'u1m2a3s4o5u6'
down_revision: Union[str, Sequence[str], None] = 'o1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_ima_configs',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('client_id_encrypted', sa.String(length=512), nullable=False),
        sa.Column('api_key_encrypted', sa.String(length=512), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_user_ima_configs_user_id'),
        'user_ima_configs', ['user_id'], unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_ima_configs_user_id'), table_name='user_ima_configs')
    op.drop_table('user_ima_configs')
