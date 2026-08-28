"""批次 H（借鉴机制）：message_feedbacks 反馈表

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c9
Create Date: 2026-08-27
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSON 列沿用项目双方言类型（GOTCHAS G2：JSONB().with_variant(JSON, "sqlite")）
    from app.models.base import JSONType

    op.create_table(
        "message_feedbacks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.String(10), nullable=False),
        sa.Column("tags", JSONType, nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_feedback_message_user"),
    )
    op.create_index(op.f("ix_message_feedbacks_message_id"), "message_feedbacks", ["message_id"])
    op.create_index(op.f("ix_message_feedbacks_user_id"), "message_feedbacks", ["user_id"])


def downgrade() -> None:
    op.drop_table("message_feedbacks")
