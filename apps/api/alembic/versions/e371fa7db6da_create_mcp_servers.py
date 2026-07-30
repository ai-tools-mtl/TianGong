"""create mcp_servers

Revision ID: e371fa7db6da
Revises: 9a3f7c2e1b4d
Create Date: 2026-07-30 11:23:11.197357

创建 MCP server 配置表（admin 全局作用域）。
spec: docs/superpowers/specs/2026-07-30-admin-mcp-config-design.md §2

注：autogenerate 还检测到对 knowledge_chunks / knowledge_files /
user_memories 上若干 PG 专有索引（gin_trgm_ops / hnsw / gin / partial）
的「drop」意图——这些索引由更早的迁移（4c736cec13b7、d1h2n3s4w5i6、
e1m2e3m4o5r6、e3r4a5g6t7s8v、f1x2e3m4b5g6）通过 raw SQL 建立，ORM 无法
建模 PG 专有索引类型，故 alembic 总是想 drop 它们。这是本项目已知的
autogenerate 伪 diff（d1h2n3s4w5i6 的 docstring 已记录同类现象），
并非本任务引入的环境漂移，已从迁移中剔除，确保本迁移只创建 mcp_servers。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e371fa7db6da'
down_revision: Union[str, Sequence[str], None] = '9a3f7c2e1b4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'mcp_servers',
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('transport', sa.String(length=20), nullable=False),
        sa.Column('command', sa.String(length=255), nullable=True),
        sa.Column('args', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('headers_encrypted', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True),
        sa.Column('env_encrypted', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True),
        # enabled: 模型侧 default=True（Python），DB 侧给 server_default=sa.true()
        # （编译为 `true`：PG 接受为 boolean 字面量，sqlite 也接受），
        # 避免 NOT NULL 无默认导致历史行插入失败。与仓库 9a3f7c2e1b4d 的
        # sa.false() 惯例一致（PG 不接受 `DEFAULT 1` 隐式转 boolean，故不用 1/0）。
        sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_mcp_servers_name', 'mcp_servers', ['name'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_mcp_servers_name', table_name='mcp_servers')
    op.drop_table('mcp_servers')
