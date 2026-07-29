"""align embedding columns to bge-m3 1024 dims

Revision ID: f1x2e3m4b5g6
Revises: e1m2e3m4o5r6
Create Date: 2026-07-29

修复预存 bug：embedding 列定义为 halfvec(2048)（源自早期智谱 embedding-3 假设），
但 main 已改用统一 bge-m3 微服务（输出 1024 维）。维度不匹配导致写入抛
DataException: expected 2048 dimensions, not 1024。

knowledge_chunks 表因 0 数据未触发；user_memories 是第一个真实写入路径踩雷。

同时修两个表（knowledge_chunks + user_memories），消除系统级潜伏 bug。
模型侧 EMBEDDING_DIM 常量已同步改为 1024（knowledge_chunk.py + user_memory.py）。

操作（两表同款）：
  1. DROP HNSW 索引（索引依赖列类型，改维度前必须先 drop）
  2. ALTER COLUMN embedding TYPE halfvec(1024)
  3. 重建 HNSW 索引（halfvec_cosine_ops, m=16, ef_construction=64，与 d1h2n3s4w5i6 同款）

数据安全：ALTER COLUMN TYPE 会全表重写 + ACCESS EXCLUSIVE 锁。
  knowledge_chunks 当前 0 行；user_memories 同样接近 0（刚上线）。可安全执行。
  生产若有大量数据需评估停机窗口。

downgrade 回滚到 halfvec(2048)（恢复分叉前状态）。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f1x2e3m4b5g6"
down_revision: Union[str, Sequence[str], None] = "e1m2e3m4o5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 两表共用：drop HNSW → ALTER 维度 → 重建 HNSW
_TABLES = [
    ("knowledge_chunks", "ix_knowledge_chunks_embedding_hnsw"),
    ("user_memories", "ix_user_memories_embedding_hnsw"),
]


def upgrade() -> None:
    for table, hnsw_idx in _TABLES:
        # 1. drop HNSW 索引（依赖列类型，改维度前必须先 drop）
        op.execute(f"DROP INDEX IF EXISTS {hnsw_idx}")
        # 2. 改列维度 2048 → 1024（USING 显式 cast 避免歧义）
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN embedding TYPE halfvec(1024) "
            f"USING embedding::halfvec(1024)"
        )
        # 3. 重建 HNSW 索引（cosine，参数同 d1h2n3s4w5i6）
        op.execute(
            f"CREATE INDEX {hnsw_idx} ON {table} "
            f"USING hnsw (embedding halfvec_cosine_ops) "
            f"WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    for table, hnsw_idx in _TABLES:
        op.execute(f"DROP INDEX IF EXISTS {hnsw_idx}")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN embedding TYPE halfvec(2048) "
            f"USING embedding::halfvec(2048)"
        )
        op.execute(
            f"CREATE INDEX {hnsw_idx} ON {table} "
            f"USING hnsw (embedding halfvec_cosine_ops) "
            f"WITH (m = 16, ef_construction = 64)"
        )
