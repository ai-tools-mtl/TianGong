"""add request_id to llm_call_logs + merge heads

Revision ID: s5l6o7g8i9j0
Revises: 3677d72bd5f8, b7c8d9e0f1a2, c1a2b3d4e5f6, r4c5d6e7f8g9
Create Date: 2026-08-10

两件事：
1. 合并迁移链的 4 个 head（并行开发产生的多分支），让迁移链重新单线。
2. llm_call_logs 加 request_id 列 + 索引：由 RequestIDMiddleware 写入 contextvar，
   helper 落库。实现「服务端日志 ↔ LLM 调用记录」跨表关联——用户报错时拿 request_id
   能同时在运行时日志和本表定位到那次请求。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s5l6o7g8i9j0"
# 合并 4 个 head + 加列（一步到位）
down_revision: Union[str, Sequence[str], None] = (
    "3677d72bd5f8",
    "b7c8d9e0f1a2",
    "c1a2b3d4e5f6",
    "r4c5d6e7f8g9",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_call_logs",
        sa.Column("request_id", sa.String(32), nullable=True),
    )
    op.create_index("ix_llm_call_logs_request_id", "llm_call_logs", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_logs_request_id", table_name="llm_call_logs")
    op.drop_column("llm_call_logs", "request_id")
