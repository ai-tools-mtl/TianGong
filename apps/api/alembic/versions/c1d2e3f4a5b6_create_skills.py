"""create_skills

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5g6
Create Date: 2026-07-22 18:28:33.373839

建 skills 表（agent-skills 计划 Task 2）。

两档可见性通过两个 partial unique index 实现（spec §5.1）：
- global 档（owner_id 恒 NULL）：对 name 唯一，WHERE scope='global'
- personal 档（owner_id 必填）：对 (owner_id, name) 唯一，WHERE scope='personal'

SQL NULL 视为 distinct，无法用单一复合索引覆盖 global 档，故必须 partial index。
两个 WHERE 子句（sqlite_where + postgresql_where）确保 sqlite 测试 + PG 生产均可移植。

status 列带 server_default='draft'：与 templates.status 一致，确保裸 SQL 插入
（不经 ORM default）时仍落 draft，不进 runtime 可见集合。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5g6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('skills',
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
    sa.Column('minio_prefix', sa.String(length=255), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_skills_owner_id'), 'skills', ['owner_id'], unique=False)
    op.create_index('uix_skill_global_name', 'skills', ['name'], unique=True, sqlite_where=sa.text("scope = 'global'"), postgresql_where=sa.text("scope = 'global'"))
    op.create_index('uix_skill_personal_owner_name', 'skills', ['owner_id', 'name'], unique=True, sqlite_where=sa.text("scope = 'personal'"), postgresql_where=sa.text("scope = 'personal'"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uix_skill_personal_owner_name', table_name='skills')
    op.drop_index('uix_skill_global_name', table_name='skills')
    op.drop_index(op.f('ix_skills_owner_id'), table_name='skills')
    op.drop_table('skills')
