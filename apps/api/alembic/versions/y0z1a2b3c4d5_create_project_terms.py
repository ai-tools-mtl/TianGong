"""create project_terms table（T2 批3：项目级术语表，spec §3.3.1）

一件专利一套术语体系：term（标准术语）+ variants（禁用变体，JSONB）+
definition（注入用定义）+ enabled（停用不注入不检查）。
注入位置：context_assembler 已写章节层之后、知识库 RAG 层之前（spec §3.3.3）。

Revision ID: y0z1a2b3c4d5
Revises: w8x9y0z1a2b3
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'y0z1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'w8x9y0z1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'project_terms',
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('term', sa.String(length=100), nullable=False),
        sa.Column('definition', sa.Text(), nullable=True),
        sa.Column('variants', JSONB(), nullable=False, server_default='[]'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='manual'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'term', name='uq_project_terms_project_term'),
    )
    op.create_index(op.f('ix_project_terms_project_id'), 'project_terms', ['project_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_project_terms_project_id'), table_name='project_terms')
    op.drop_table('project_terms')
