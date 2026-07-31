"""add messages.meta column

Revision ID: q3b4c5d6e7f8
Revises: o1a2b3c4d5e6
Create Date: 2026-07-31

为 messages 表加 meta 字段（agent 透明化元数据，类 zcode 工具调用提示 + 思考过程）：
- meta: JSONB，存 { "tool_events": [...], "thinking": str }
  - tool_events：本轮 agent 工具调用/返回序列（call/result + name + args/result）
  - thinking：模型推理过程（GLM/DeepSeek reasoning_content），全文存（用户选了保留）
- 仅 assistant 消息可能非空；user 恒 NULL；可空（旧消息 / rewrite 路径无）。
- 历史回灌时前端据此恢复工具卡片 + 思考块展示。

字段名用 meta 而非 metadata：SQLAlchemy declarative 模型中 metadata 是保留属性
（Base.metadata），直接用 metadata 列名会冲突。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base import JSONType


revision: str = "q3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "o1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("meta", JSONType, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "meta")
