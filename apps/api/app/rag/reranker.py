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


def rerank(query: str, documents: list[str], *, config: RerankConfig, strict: bool = False) -> list[tuple[int, float]]:
    """对 documents 按 query 重排，返回 top_n 个 (索引, relevance_score)（按相关性降序）。

    返回索引而非文本：调用方据此按列表位置取回 candidate，位置天然一一对应，
    不会因 documents 内存在重复文本而把多条 candidate 合并成一条（旧实现用文本
    建 dict 当匹配键时有此 bug）。回传 relevance_score 让调用方把精排分写回
    candidate 作为最终展示分（旧实现最终分用的是 rerank 之前的 RRF 分，调参时
    误判 rerank 效果）。

    D5 降级：config.enabled=False 或 API 失败时，原样返回
    [(i, 0.0) for i in range(len(documents))]（即原序、无精排分，不抛错）。
    strict=True 时绕过降级，API 失败直接抛错——供 admin 测试连通性端点使用，
    否则降级会让"API 挂了"也返回成功，test 端点失去诊断意义。
    """
    if not config.enabled or not documents:
        return [(i, 0.0) for i in range(len(documents))]

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
        return [(r["index"], float(r["relevance_score"])) for r in results[:config.top_n]]
    except Exception as e:
        if strict:
            raise  # 测试连通性场景：失败必须抛，让调用方知道 API 不通
        # D5：失败降级，不报错（检索不能因 rerank 挂掉而整体失败）
        logger.warning("rerank 调用失败，降级返回原序: %s", e)
        return [(i, 0.0) for i in range(len(documents))]
