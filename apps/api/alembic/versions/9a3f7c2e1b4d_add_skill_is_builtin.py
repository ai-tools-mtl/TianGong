"""add skills.is_builtin

Revision ID: 9a3f7c2e1b4d
Revises: 4c736cec13b7
Create Date: 2026-07-30

内置 skill：从项目根 assets/skills/ 启动时同步进系统的 global skill，
标记 is_builtin=True 以区分 admin 手建 skill，并在 UI 上禁用编辑/删除
（内容由文件系统管理）。

- is_builtin: Boolean，默认 false（既有 admin/用户 skill 均为 false）
- 走 Boolean 列 + server_default false，纯 ADD COLUMN，幂等
- 用 batch_alter_table 保证 SQLite/PG 兼容（项目测试用 SQLite 内存库）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a3f7c2e1b4d'
down_revision: Union[str, Sequence[str], None] = '4c736cec13b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加 is_builtin 列（默认 false）。"""
    with op.batch_alter_table('skills', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_builtin', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """回滚：删 is_builtin 列。"""
    with op.batch_alter_table('skills', schema=None) as batch_op:
        batch_op.drop_column('is_builtin')
