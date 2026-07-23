"""p2 grants table + user_llm_config multi-config

阶段 2 地基（Task 2.0）：
1. 新增 user_global_llm_grants 表——用户级全局 LLM Key 白名单授权。
   admin 配一把全局 Key，逐用户授权（grant）才能用；撤销写 revoked_at。
   user_id unique（一用户最多一条有效授权）。
2. user_llm_configs 去 user_id unique（一用户可有多条自定义配置）+ 新增 name 列。

注意：a20f16f0da4e 当初把 user_id 的 unique 约束实现为 unique index
（ix_user_llm_configs_user_id, unique=True）。去 unique = drop 该 unique index
再重建为普通 index。name 为 NOT NULL，对历史行无值，故先 DELETE 旧行
（drop-rebuild 共识：自定义配置可丢弃）再 add nullable 最后 alter 到 NOT NULL，
兼容 sqlite（batch_alter_table）与 PG。

is_active 本迁移不触碰（Task 2.1 在重写 resolve 时再移除）。

Revision ID: c1a2b3c4d5e6
Revises: fa75b47f596f
Create Date: 2026-07-16 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'fa75b47f596f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── 1. user_global_llm_grants 表 ──
    op.create_table(
        'user_global_llm_grants',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('granted_by', sa.Uuid(), nullable=True),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['granted_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_user_global_llm_grants_user_id'), 'user_global_llm_grants', ['user_id'], unique=True)

    # ── 2. user_llm_configs 去 unique + 加 name ──
    # 旧自定义配置行无 name 值；drop-rebuild 共识下直接清空（Task 2.0 地基，数据可丢）。
    op.execute("DELETE FROM user_llm_configs")

    with op.batch_alter_table('user_llm_configs', schema=None) as batch_op:
        # a20f16f0da4e 当初以 unique index 形式落地 user_id 唯一性，先 drop 它
        batch_op.drop_index('ix_user_llm_configs_user_id')
        # 先以 nullable 增加（兼容已有行清空后的空表）
        batch_op.add_column(sa.Column('name', sa.String(length=50), nullable=True))

    # 重建为普通（非 unique）index —— 一个用户可有多条自定义配置
    op.create_index(
        op.f('ix_user_llm_configs_user_id'),
        'user_llm_configs', ['user_id'], unique=False,
    )

    # 数据已清空，安全收紧为 NOT NULL
    with op.batch_alter_table('user_llm_configs', schema=None) as batch_op:
        batch_op.alter_column('name', existing_type=sa.String(length=50),
                              nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # 回退 user_llm_configs：name → 去 unique 恢复
    with op.batch_alter_table('user_llm_configs', schema=None) as batch_op:
        batch_op.alter_column('name', existing_type=sa.String(length=50),
                              nullable=True)

    op.drop_index(op.f('ix_user_llm_configs_user_id'), table_name='user_llm_configs')
    with op.batch_alter_table('user_llm_configs', schema=None) as batch_op:
        batch_op.drop_column('name')

    # 恢复 user_id unique index
    op.create_index(
        op.f('ix_user_llm_configs_user_id'),
        'user_llm_configs', ['user_id'], unique=True,
    )

    # 回退 user_global_llm_grants
    op.drop_index(op.f('ix_user_global_llm_grants_user_id'), table_name='user_global_llm_grants')
    op.drop_table('user_global_llm_grants')
