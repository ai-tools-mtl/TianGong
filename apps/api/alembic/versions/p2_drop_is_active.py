"""p2 drop user_llm_configs.is_active

阶段 2 Task 2.1：resolve_llm_config 改为按 source 解析 + grant 授权，
不再需要 is_active 列（旧「用户自配(is_active=True) > 全局 > env」三级优先级
已废弃；现在显式 source 指定使用哪条配置，或 fallback 取首行）。

batch_alter_table drop_column 兼容 sqlite（无原生 ALTER COLUMN DROP）与 PG。

Revision ID: d2b3c4d5e6f7
Revises: c1a2b3c4d5e6
Create Date: 2026-07-16 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop is_active column from user_llm_configs."""
    with op.batch_alter_table('user_llm_configs', schema=None) as batch_op:
        batch_op.drop_column('is_active')


def downgrade() -> None:
    """Restore is_active column (default True)."""
    with op.batch_alter_table('user_llm_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
