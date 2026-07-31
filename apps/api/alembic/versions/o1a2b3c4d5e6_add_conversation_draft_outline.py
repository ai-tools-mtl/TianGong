"""add conversation.draft_outline + merge heads

Revision ID: o1a2b3c4d5e6
Revises: 3677d72bd5f8, b7c8d9e0f1a2
Create Date: 2026-07-31

为 conversations 加 draft_outline 字段（init 助手「右侧文档实时预览」草稿态）：
- draft_outline: JSONB，存轻量 LLM 每轮提取的 8 章结构化要点
  {key: {"title": str, "content": str}}，content 为 Markdown。
- 草稿专用，按扳机落地后才转为正式 section；不提前建项目，不改核心落地流程。

同时作为 merge 节点：把两条并行开发的 head
（3677d72bd5f8 context_meta 压缩特性 / b7c8d9e0f1a2 assistant 对话特性）
汇成单一线性链，消除分叉。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import JSONType


revision: str = "o1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = ("3677d72bd5f8", "b7c8d9e0f1a2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("draft_outline", JSONType, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "draft_outline")
