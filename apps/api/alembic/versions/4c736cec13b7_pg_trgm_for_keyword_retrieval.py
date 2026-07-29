"""pg_trgm for keyword retrieval（中文 BM25 召回修复）

Revision ID: 4c736cec13b7
Revises: b0e8d6d18682
Create Date: 2026-07-29

根因：to_tsvector('simple', ...) / plainto_tsquery('simple', ...) 对中文几乎不分词
（simple 配置按空格切 token，中文无空格），导致关键词路召回接近失效，RRF 融合
退化为纯向量检索。

修复：启用 PG 内置 pg_trgm 扩展，对 knowledge_chunks.content 建 GIN trigram 索引。
检索改用 trigram 相似度（content % query + similarity()），对中文子串匹配效果好。
pg_trgm 是 PG 内置扩展（pgvector/pgvector 镜像已含），无需额外装。

保留旧 tsv 列 + tsv GIN 索引（兼容，不破坏；retriever 不再用 tsv，改用 content trigram）。
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '4c736cec13b7'
down_revision: Union[str, Sequence[str], None] = 'b0e8d6d18682'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """启用 pg_trgm + content trigram 索引 + 全局库 content_hash 部分唯一索引。"""
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    # content 列 trigram 索引（支持 % 操作符 + similarity() 函数，中文子串匹配）
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_content_trgm '
        'ON knowledge_chunks USING gin (content gin_trgm_ops)'
    )
    # 全局库 content_hash 部分唯一索引：根治并发上传同文件的 TOCTOU 竞态
    # （personal 库允许同 hash 多份，故只对 scope='global' 加唯一约束）
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS ix_kf_global_content_hash '
        "ON knowledge_files (content_hash) WHERE scope='global'"
    )


def downgrade() -> None:
    """删 trigram 索引 + 部分唯一索引（保留 pg_trgm 扩展）。"""
    op.execute('DROP INDEX IF EXISTS ix_kf_global_content_hash')
    op.execute('DROP INDEX IF EXISTS ix_knowledge_chunks_content_trgm')
