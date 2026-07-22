"""drop agent_skills 表（旧 skill 体系，spec Q5 解耦决定）。

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-22

删除 project-scoped 的 agent_skills 表。旧 AgentSkill 模型 / skill_service /
/projects/{id}/skills 路由 / BUILTIN_SKILLS 常量已在同一任务中同步删除。
新 Skill 体系（admin global / user personal 两档可见性）在 Task 6+ 重建，
完全脱离 project。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 索引名与原始迁移 0c31c3a1e6ad 一致（op.f('ix_agent_skills_project_id')）
    op.drop_index(op.f('ix_agent_skills_project_id'), table_name='agent_skills')
    op.drop_table('agent_skills')


def downgrade() -> None:
    """Downgrade schema: 重建 agent_skills 表（与 0c31c3a1e6ad 完全一致）。"""
    op.create_table('agent_skills',
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('skill_key', sa.String(length=50), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_skills_project_id'), 'agent_skills', ['project_id'], unique=False)
