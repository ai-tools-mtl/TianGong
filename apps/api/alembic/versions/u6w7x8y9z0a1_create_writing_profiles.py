"""create writing_profiles table

Revision ID: u6w7x8y9z0a1
Revises: s5d6e7f8g9h1
Create Date: 2026-08-11

新建 writing_profiles 表：用户写作画像（一对一，结构化偏好）。

5 个固定维度字段（profession/tech_domain/proficiency/writing_style/terminology），
由用户在 /settings/profile 显式填写，每次 LLM 生成时全量强注入 system prompt。
user_id UNIQUE 约束保证一对一。

与 user_memory(source=profile) 并存：本表结构化强注入，user_memory 自由文本走语义检索。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "u6w7x8y9z0a1"
down_revision: Union[str, Sequence[str], None] = "s5d6e7f8g9h1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "writing_profiles",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("profession", sa.String(100), nullable=True),
        sa.Column("tech_domain", sa.String(100), nullable=True),
        sa.Column("proficiency", sa.String(20), nullable=True),
        sa.Column("writing_style", sa.Text, nullable=True),
        sa.Column("terminology", sa.Text, nullable=True),
        sa.Column("extras", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_writing_profiles_user"),
    )


def downgrade() -> None:
    op.drop_table("writing_profiles")
