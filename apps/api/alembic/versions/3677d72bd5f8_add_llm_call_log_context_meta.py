"""add llm_call_log context_meta

Revision ID: 3677d72bd5f8
Revises: e371fa7db6da
Create Date: 2026-07-31 09:07:18.363567

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import JSONType


# revision identifiers, used by Alembic.
revision: str = '3677d72bd5f8'
down_revision: Union[str, Sequence[str], None] = 'e371fa7db6da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 上下文压缩观测（spec §5.1）：Snapshot 序列化列。nullable（未压缩或旧记录为空）。
    # 用 JSONType（= JSONB().with_variant(JSON, "sqlite")，GOTCHAS G2）让 SQLite 测试可用。
    # 注意 JSONType 已是实例（with_variant 的返回值），不能再加 ()（否则 "JSONB object is not callable"）。
    op.add_column('llm_call_logs', sa.Column('context_meta', JSONType, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('llm_call_logs', 'context_meta')
