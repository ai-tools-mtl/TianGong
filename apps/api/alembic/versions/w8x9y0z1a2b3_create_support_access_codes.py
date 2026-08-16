"""create support_access_codes table（设计 §8.3 完整版：经授权临时查看）

用户求助时生成一次性短码；admin 凭码核销后获得限时只读查看窗口，全程审计。
与 share_links（游客公开浏览）正交：一次性核销 + 换后限时窗口 + 每次访问审计。

Revision ID: w8x9y0z1a2b3
Revises: 697a84b2b359
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'w8x9y0z1a2b3'
down_revision: Union[str, Sequence[str], None] = '697a84b2b359'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'support_access_codes',
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('redeemed_by', sa.Uuid(), nullable=True),
        sa.Column('view_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['redeemed_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_support_access_codes_code'), 'support_access_codes', ['code'], unique=True)
    op.create_index(op.f('ix_support_access_codes_project_id'), 'support_access_codes', ['project_id'], unique=False)
    op.create_index(op.f('ix_support_access_codes_created_by'), 'support_access_codes', ['created_by'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_support_access_codes_created_by'), table_name='support_access_codes')
    op.drop_index(op.f('ix_support_access_codes_project_id'), table_name='support_access_codes')
    op.drop_index(op.f('ix_support_access_codes_code'), table_name='support_access_codes')
    op.drop_table('support_access_codes')
