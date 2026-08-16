"""add unique index on conversations for init landing dedup

Revision ID: t0p1u2v3w4x5
Revises: s5d6e7f8g9h1
Create Date: 2026-08-11

P0-1 修复 init generate 双击重复落地（数据正确性）。

根因：assistant.py 的 generate 端点只做读时检查 conv.project_id is not None，
init_orchestrator.py 的 create_project(自管 commit) + conversation.project_id=...; db.commit()
两步非原子。用户双击扳机 → 两个并发请求同时通过读时检查 → 建两个项目 + 两组 8 章。

修复：加部分唯一索引——同一 user 的未落地 init 会话（project_id IS NULL）最多 1 条。
第二个请求把 project_id 填上时唯一约束冲突 → IntegrityError → 端点转 ConflictError。

PG 专属语法（CREATE UNIQUE INDEX ... WHERE）——SQLite 不支持部分唯一索引，
但本迁移在生产 PG 跑；SQLite 测试库用兼容表（见 conftest.py），不走此迁移。

幂等性：migrate 前先清理历史脏数据——同一 user 若已有多条未落地 init 会话，
保留最新一条（按 created_at desc），其余把 project_id 指向一个哨兵值避开唯一约束。
正常无脏数据时清理跳过（0 行）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t0p1u2v3w4x5"
down_revision: Union[str, Sequence[str], None] = "s5d6e7f8g9h1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 索引名：语义化前缀 uq_（unique），后跟表+约束含义
_INDEX_NAME = "uq_conversations_init_one_unlanded"


def upgrade() -> None:
    """建部分唯一索引前先清脏数据，保证索引创建不冲突。"""
    bind = op.get_bind()

    # 清理历史脏数据：同一 user 若有多条未落地 init 会话，保留最新一条。
    # 改写方式：把多余会话的 kind 置为 'init_dup'——避开部分唯一索引的
    # kind='init' 条件。原先的写法是把 project_id 指向哨兵 UUID，但
    # project_id 有 FK 约束（fk_conversations_project_id），哨兵值不存在
    # 必触发 ForeignKeyViolation（有重复数据的库无法完成迁移）；
    # 改 kind 不碰外键且保留数据。用纯 SQL 子查询批量处理，避免逐条循环。
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("""
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) AS rn
                FROM conversations
                WHERE kind = 'init' AND project_id IS NULL
            )
            UPDATE conversations
            SET kind = 'init_dup'
            FROM ranked
            WHERE conversations.id = ranked.id AND ranked.rn > 1
        """))

    # 部分唯一索引：同一 user 只能有 1 条「未落地的 init 会话」。
    # 注意：SQLite 不支持部分唯一索引的 WHERE 子句——但本迁移仅在 PG 跑，
    # 测试库用 conftest.py 的兼容表，Base.metadata.create 直接建表，不走 alembic。
    op.create_index(
        _INDEX_NAME,
        "conversations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'init' AND project_id IS NULL"),
        sqlite_where=sa.text("1=0"),  # SQLite 永不匹配，等效禁用（测试不走此路径）
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="conversations")
