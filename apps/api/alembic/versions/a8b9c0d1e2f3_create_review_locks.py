"""create review_locks (DB-level review mutex)

Revision ID: a8b9c0d1e2f3
Revises: z1a2b3c4d5e6
Create Date: 2026-08-25

审查进行中互斥原为 review_service 进程内 dict——单进程 uvicorn 下可靠，
但多 worker 部署时各进程各一份互不可见，同项目可并发双跑（重复 LLM 调用
+ 同轮次重复落库）。升级为 DB 行标记：

- project_id 主键：一个项目一行锁，INSERT 撞主键即冲突；
- stale 抢占用条件 UPDATE（WHERE last_touch < 阈值），rowcount 判定成败，
  原子性由数据库保证（PG 行锁 / SQLite 写串行），跨进程可靠；
- owner_token 守卫心跳与释放：stale 抢占后，原僵死进程的迟到心跳/释放
  不能误续/误删新持有者的锁。

进程崩溃时锁行残留，超 900s 无心跳即被下一次占坑抢占（宁过期不死锁）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "z1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_locks",
        sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_token", sa.String(36), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("last_touch", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("review_locks")
