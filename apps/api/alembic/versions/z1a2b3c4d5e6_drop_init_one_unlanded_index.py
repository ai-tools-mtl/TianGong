"""drop uq_conversations_init_one_unlanded (conflicts with multi-conversation design)

Revision ID: z1a2b3c4d5e6
Revises: y0z1a2b3c4d5
Create Date: 2026-08-19

t0p1u2v3w4x5 的部分唯一索引（同一 user 的未落地 init 会话最多 1 条）与
ChatGPT 式多会话设计冲突：用户已有一个未落地会话时点「+ 新对话」再建一条
必然撞索引 → IntegrityError → 500（2026-08-19 线上报障根因）。

防双击重复落地的职责收敛到行锁：init_orchestrator 对 conversation 行
FOR UPDATE 后，create_project 以 commit=False 参与同一事务，锁持有到
project_id 标记 commit 完成——并发请求在锁上串行化，无中途释放窗口，
不再需要索引兜底（原索引的存在价值恰来自 create_project 自管 commit
提前释放行锁的窗口）。

同时恢复 t0p1u2v3w4x5 迁移清脏数据时误伤的会话：当时同一 user 的多余
未落地会话被改 kind='init_dup' 以便索引能建起来；多会话本就是合法状态，
改回 'init' 让它们重新出现在助手列表。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "z1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "y0z1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "uq_conversations_init_one_unlanded"


def upgrade() -> None:
    # 必须先删索引再恢复数据：索引还在时，把 init_dup 改回 init 会让同一
    # user 出现第二条未落地 init 会话，当场撞这个索引（同事务 DDL 顺序敏感）。
    op.drop_index(_INDEX_NAME, table_name="conversations")
    op.execute(sa.text("UPDATE conversations SET kind = 'init' WHERE kind = 'init_dup'"))


def downgrade() -> None:
    """重建索引前先把多会话压回单会话（与 t0p1u2v3w4x5 同款清法）。"""
    bind = op.get_bind()
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
    op.create_index(
        _INDEX_NAME,
        "conversations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'init' AND project_id IS NULL"),
        sqlite_where=sa.text("1=0"),
    )
