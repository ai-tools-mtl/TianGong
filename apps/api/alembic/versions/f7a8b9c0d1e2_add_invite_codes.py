"""add invite_codes table

内部产品化补齐(差距①):关闭开放注册后,admin 通过邀请码发号或直接创建账号。

新增 invite_codes 表:
- code: 8 位邀请码(unique, index)
- created_by_id: 创建者 admin(SET NULL 兜底删除)
- max_uses / used_count: 用量控制
- expires_at: 过期(nullable=不过期)
- revoked_at: 吊销(nullable=未吊销)

Revision ID: f7a8b9c0d1e2
Revises: d2e3f4a5b6c7
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'invite_codes',
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('max_uses', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('used_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_invite_codes_code'), 'invite_codes', ['code'], unique=True)
    op.create_index(op.f('ix_invite_codes_created_by_id'), 'invite_codes', ['created_by_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_invite_codes_created_by_id'), table_name='invite_codes')
    op.drop_index(op.f('ix_invite_codes_code'), table_name='invite_codes')
    op.drop_table('invite_codes')
