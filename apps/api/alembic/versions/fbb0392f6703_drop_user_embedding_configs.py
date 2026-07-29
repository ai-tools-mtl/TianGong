"""drop user_embedding_configs（embedding 改走固定 bge-m3 微服务）

Revision ID: fbb0392f6703
Revises: f4g5i6n7t8e9
Create Date: 2026-07-28

embedding 不再支持用户自配/全局配置，统一走固定的 bge-m3 微服务
（OpenAI 兼容协议，连接信息从 env 读，见 core/config.py 的
embedding_base_url / embedding_model / embedding_api_key）。

本迁移：
- DROP TABLE user_embedding_configs（b_split_emb_config 建的表）
- 不动 system_settings 里 llm_global_embedding_config 数据行（初始阶段库基本为空，
  且 SystemSetting 是通用 KV 表，删数据行不属于 schema 迁移范畴）

初始设计阶段，不保数据：user_embedding_configs 里的用户自配 embedding 凭据直接丢弃。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fbb0392f6703'
down_revision: Union[str, Sequence[str], None] = 'f4g5i6n7t8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop user_embedding_configs table."""
    op.drop_index(
        op.f('ix_user_embedding_configs_user_id'),
        table_name='user_embedding_configs',
    )
    op.drop_table('user_embedding_configs')


def downgrade() -> None:
    """Recreate user_embedding_configs table（镜像 b_split_emb_config 的建表逻辑）。"""
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
    op.create_index(
        op.f('ix_user_embedding_configs_user_id'),
        'user_embedding_configs', ['user_id'], unique=False,
    )
