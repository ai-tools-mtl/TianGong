"""G3 rerank 配置 service（spec §5.3, D6）。

镜像 embedding 配置的解析模式：统一走固定的 bge-reranker-v2-m3 本地微服务
（Infinity，OpenAI 兼容的 /rerank 端点），连接信息从环境变量读
（rerank_enabled/rerank_base_url/rerank_model/rerank_api_key）。

不再支持 SystemSetting 全局配置 / 加密存储。用户/admin 不可配 rerank。
与 embedding 的唯一不对称：rerank 是 fail-open 设计（挂了降级原序），
故保留 rerank_enabled 开关供运维降级；embedding 无开关因其挂了 RAG 直接崩。

db / user_id 参数保留仅为避免动调用方签名，内部一律返回 env 配置。
"""
from app.core.config import get_settings
from app.rag.reranker import RerankConfig


def resolve_rerank_config(db=None, *, user_id=None) -> RerankConfig:
    """返回 rerank 配置。统一读环境变量（rerank_*）。

    不再从 SystemSetting 读取。db / user_id 参数保留仅为兼容调用方签名
    （retriever.py 传 user_id），内部忽略，永不为 None。

    rerank_enabled=False 时返回 disabled 配置（fail-open 跳过 rerank）。
    """
    s = get_settings()
    return RerankConfig(
        enabled=s.rerank_enabled,
        base_url=s.rerank_base_url,
        api_key=s.rerank_api_key,
        model=s.rerank_model,
    )
