"""split embedding config: 新建 user_embedding_configs 表 + 删 user_llm_configs.embedding_model

Revision ID: b_split_emb_config
Revises: f7a8b9c0d1e2
Create Date: 2026-07-24

开发阶段（D3 决策）：纯 schema 变更，不保数据。
- 老的 user_llm_configs.embedding_model 数据直接丢弃（用户重建到新表）。
- UserEmbeddingConfig model 见 app/models/user_embedding_config.py（Task 1）。
- 列类型严格对齐 IdMixin / TimestampMixin（base.py）：id=sa.Uuid()，
  timestamps=sa.DateTime(timezone=True) server_default now() NOT NULL，
  风格镜像 a20f16f0da4e_add_user_llm_configs.py，保证后续 alembic autogenerate 不报伪 diff。

注意：本迁移故意留下「旧代码仍读 cfg.embedding_model」的破损态——
Tasks 3-8 才会改写 resolve / ResolvedLLMConfig / API 路由的调用方。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b_split_emb_config'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── 1. 新建 user_embedding_configs 表 ──
    # 与 user_llm_configs 同构，去掉 provider / embedding_model（语义是 embedding 凭据）。
    # 列类型镜像 a20f16f0da4e（user_llm_configs 建表迁移）——IdMixin.id=sa.Uuid()，
    # TimestampMixin timestamps=DateTime(timezone=True) server_default now() NOT NULL。
    op.create_table(
        'user_embedding_configs',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('base_url', sa.String(length=255), nullable=False),
        sa.Column('api_key_encrypted', sa.String(length=512), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # model 里 user_id 上 index=True，对应普通（非 unique）index
    op.create_index(
        op.f('ix_user_embedding_configs_user_id'),
        'user_embedding_configs', ['user_id'], unique=False,
    )

    # ── 2. 删 user_llm_configs.embedding_model 列（迁移到 user_embedding_configs）──
    # 开发阶段不保数据；老 embedding_model 值丢弃。
    with op.batch_alter_table('user_llm_configs', schema=None) as batch_op:
        batch_op.drop_column('embedding_model')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user_llm_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('embedding_model', sa.String(length=100), nullable=True))

    op.drop_index(op.f('ix_user_embedding_configs_user_id'), table_name='user_embedding_configs')
    op.drop_table('user_embedding_configs')
