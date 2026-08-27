"""批次 A（A-3）：llm_call_logs 增加 token_prompt_cached 列

Revision ID: b2c3d4e5f6a7
Revises: b3c4d5e6f7g8
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "b3c4d5e6f7g8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 供应商前缀缓存命中 token 数（nullable：历史数据 / provider 未回传均无值）
    op.add_column(
        "llm_call_logs",
        sa.Column("token_prompt_cached", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_call_logs", "token_prompt_cached")
