"""add hnsw index on knowledge_chunks.embedding (halfvec)

Revision ID: d1h2n3s4w5i6
Revises: c3d4e5f6a7b8
Create Date: 2026-07-28

给 knowledge_chunks.embedding 列建 HNSW 索引（cosine 距离）。
spec: docs/superpowers/specs/2026-07-27-ragflow-borrow-design.md §5.1 (G1, D1 + D1.1)

⚠️ D1.1（2026-07-28 实施时发现）：
pgvector HNSW/IVFFlat 对 vector 类型有 2000 维硬上限，智谱 embedding-3 原生 2048 维超限。
解法：列类型 vector(2048) → halfvec(2048)（halfvec 支持 4000 维，float16 存储减半，
对 cosine 影响可忽略，pgvector 0.8.5 实测可用）。不降维、不改 EMBEDDING_DIM。

参数（D6：写死常量，不暴露 admin）：
- m=16, ef_construction=64（pgvector 官方推荐）
- ef_search 在查询时 SET LOCAL（见 retriever.py）

注意：
- 手写迁移（autogenerate 不感知向量索引 + halfvec 类型转换）
- 不动 vector extension（ee50036c9e86 已 CREATE EXTENSION，幂等不重复）
- downgrade 只 drop index + 回滚列类型，不 drop extension
- halfvec 用 halfvec_cosine_ops（与 vector_cosine_ops 平行）
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd1h2n3s4w5i6'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 防御性 CREATE EXTENSION（幂等，ee50036c9e86 已建过）
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    # D1.1: 列类型 vector(2048) → halfvec(2048)（解决 pgvector HNSW 2000 维上限）
    op.execute('ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE halfvec(2048) USING embedding::halfvec(2048)')
    # HNSW 索引：halfvec 用 halfvec_cosine_ops（与 retriever.cosine_distance 操作符对齐）
    op.execute(
        'CREATE INDEX ix_knowledge_chunks_embedding_hnsw '
        'ON knowledge_chunks USING hnsw (embedding halfvec_cosine_ops) '
        'WITH (m = 16, ef_construction = 64)'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw')
    # 回滚列类型到 vector(2048)
    op.execute('ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE vector(2048) USING embedding::vector(2048)')
    # 不 drop vector extension（其他表/列可能依赖）
