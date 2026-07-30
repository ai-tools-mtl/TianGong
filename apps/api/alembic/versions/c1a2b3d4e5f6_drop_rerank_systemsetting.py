"""drop rag_rerank_config SystemSetting 行（rerank 改走 env + 本地 Infinity 微服务）

Revision ID: c1a2b3d4e5f6
Revises: 9a3f7c2e1b4d
Create Date: 2026-07-30

rerank 不再支持 admin 全局配置（SystemSetting key='rag_rerank_config'），
统一走固定的 bge-reranker-v2-m3 本地微服务（Infinity，OpenAI 兼容 /rerank 端点），
连接信息从 env 读（rerank_base_url / rerank_model / rerank_api_key / rerank_enabled），
与 embedding 配置对称。详见 core/config.py 的 rerank_* 字段。

本迁移：
- DELETE system_settings 中 key='rag_rerank_config' 的数据行（SystemSetting 是通用
  KV 表，删一行数据不属于 schema 变更，但与本次配置迁移强相关，随迁移一并清理）
- 不动表结构（system_settings 表本身保留，供其它配置继续使用）

旧 rerank 凭据（若有）直接丢弃——rerank 已改本地无 key，旧云 key 无意义。
downgrade 不恢复数据（数据已删且无备份语义）。
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9a3f7c2e1b4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除 system_settings 里的 rag_rerank_config 行（rerank 迁到 env 后的死数据）。"""
    op.execute(
        "DELETE FROM system_settings WHERE key = 'rag_rerank_config'"
    )


def downgrade() -> None:
    """不恢复——旧 rerank 云配置已无意义（改走本地无 key 微服务）。

    若需回滚到 admin SystemSetting 模式，需配合代码回滚，数据无法重建。
    """
    pass
