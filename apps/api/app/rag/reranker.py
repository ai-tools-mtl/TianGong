"""G3 rerank client（spec §5.3 阶段3，D5 可开关 + 失败降级）。

httpx 直连 rerank API（非 OpenAI 标准端点，不走 LangChain，抄 list_provider_models 模式）。
首选智谱 rerank API，失败时降级返回原序（D5）——检索不能因 rerank 挂掉而整体失败。
"""
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RerankConfig:
    """rerank 配置（Task 3.3 的 resolve_rerank_config 会构建此对象）。"""
    enabled: bool
    base_url: str
    api_key: str
    model: str
    top_n: int = 3


def rerank(query: str, documents: list[str], *, config: RerankConfig) -> list[str]:
    """对 documents 按 query 重排，返回 top_n 个文本。

    D5 降级：config.enabled=False 或 API 失败时，原样返回 documents（不抛错）。
    """
    if not config.enabled or not documents:
        return documents

    try:
        resp = httpx.post(
            f"{config.base_url}/rerank",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json={
                "model": config.model,
                "query": query,
                "documents": documents,
                "top": config.top_n,
                "return_documents": False,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # 智谱 rerank 返回 {"results": [{"index": N, "relevance_score": F}, ...]}
        results = sorted(data.get("results", []), key=lambda r: -r["relevance_score"])
        return [documents[r["index"]] for r in results[:config.top_n]]
    except Exception as e:
        # D5：失败降级，不报错（检索不能因 rerank 挂掉而整体失败）
        logger.warning("rerank 调用失败，降级返回原序: %s", e)
        return documents
