"""腾讯 ima 检索源客户端（实时外部检索源，不落库）。

两步检索（经真实凭据联调确认的官方 OpenAPI 流程）：
  ① search_knowledge_base —— 知识库发现层：返回与 query 相关的知识库列表
     （含「我加入的订阅知识库」），每条含 kb_id / kb_name / base_type。
  ② search_knowledge —— 文档检索层：传入 knowledge_base_id，返回该库内的
     文档片段（title / highlight_content / media_id）。

社区文档把两步混为一谈是误导：search_knowledge_base 只返回库元信息，
highlight_content 实际在 search_knowledge 的返回里。

与 reranker 同属 fail-open 设计——任何失败（超时/网络/鉴权）静默返回 []，
绝不阻断本地 RAG 主链路。

鉴权格式：ima 官方自定义 header（ima-openapi-clientid / ima-openapi-apikey）。
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.core.config import get_settings
from app.services.ima_config_service import ResolvedIMAConfig

logger = logging.getLogger(__name__)

# ima 片段在 prompt 里的固定相关度（低于本地 RAG 的真实分，让 rerank/排序倾向本地结果）
IMA_FALLBACK_SCORE = 0.5
# 两步检索：第一步空 query 列出所有可见库（含订阅库），第二步对每个库做文档检索。
# search_knowledge_base 只能按"库名/描述"匹配库，无法按内容发现库，故必须全库 fan-out
# 才不漏内容。用线程池并发控制延迟；每库 limit=1 控制总片段数。
DOC_PER_KB = 1
MAX_WORKERS = 8


def _build_headers(config: ResolvedIMAConfig) -> dict[str, str]:
    """构造请求头（ima 官方自定义鉴权 header）。"""
    return {
        "ima-openapi-clientid": config.client_id,
        "ima-openapi-apikey": config.api_key,
        "Content-Type": "application/json",
    }


def search_ima(
    query: str, config: ResolvedIMAConfig, *, top_k: int = 3, strict: bool = False,
) -> list[dict]:
    """两步检索 ima 知识库（含订阅库），返回文档片段列表。

    返回统一形状：[{title, content, kb_name}]，content 为 highlight 片段
    （highlight 为空时退化为 title，保证有可读内容）。
    默认 fail-open：任何异常静默返回 []（检索主链路绝不能因 ima 挂掉而失败）。
    strict=True 时绕过降级，失败直接抛错——供 admin 连通性测试用。
    """
    if not query.strip():
        return []
    settings = get_settings()
    try:
        # 第一步：空 query 列出所有可见库（含订阅库）——search_knowledge_base 按
        # 库名/描述匹配，不能用具体 query（会漏掉名字不含 query 的库）。
        kb_list = _search_knowledge_base(config, settings)
        if not kb_list:
            return []
        # 第二步：对全部库用真实 query 并发检索文档片段（fan-out）。
        # 并发控制延迟；每库 DOC_PER_KB 条，汇总后截断 top_k。
        def _fetch(kb):
            docs = _search_knowledge(query, kb["kb_id"], config, settings, limit=DOC_PER_KB)
            return kb, docs

        snippets: list[dict] = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for kb, docs in pool.map(_fetch, kb_list):
                for d in docs:
                    snippets.append({
                        "title": d.get("title") or kb.get("kb_name") or "腾讯 ima",
                        "content": d.get("highlight_content") or d.get("title") or "",
                        "kb_name": kb.get("kb_name") or "腾讯 ima",
                    })
        return snippets[:top_k]
    except Exception as e:
        if strict:
            raise  # 测试连通性场景：失败必须抛，让调用方拿到真实错误
        logger.warning("ima 检索调用失败，降级返回空（不影响本地 RAG）: %s", e)
        return []


def _search_knowledge_base(
    config: ResolvedIMAConfig, settings,
) -> list[dict]:
    """第一步：search_knowledge_base 用空 query 列出所有可见库（含订阅库）。

    空 query 时 ima 返回账号下全部可见知识库（含「我加入的订阅知识库」）。
    返回 [{kb_id, kb_name, base_type, ...}]。
    """
    resp = httpx.post(
        settings.ima_search_kb_url,
        headers=_build_headers(config),
        json={"query": "", "cursor": "", "limit": 20},
        timeout=settings.ima_search_timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, None):  # 非 0 表示业务错误（如鉴权失败 200002）
        raise RuntimeError(f"ima search_knowledge_base 失败: {data.get('msg')}")
    items = _extract_info_list(data)
    return [it for it in items if isinstance(it, dict) and it.get("kb_id")]


def _search_knowledge(
    query: str, kb_id: str, config: ResolvedIMAConfig, settings, *, limit: int,
) -> list[dict]:
    """第二步：search_knowledge 在指定库内检索文档片段。

    需要 knowledge_base_id 参数（来自第一步）。返回 [{title, highlight_content, media_id}]。
    """
    resp = httpx.post(
        settings.ima_search_doc_url,
        headers=_build_headers(config),
        json={"knowledge_base_id": kb_id, "query": query, "limit": limit},
        timeout=settings.ima_search_timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, None):
        # 单个库检索失败不致命（如该库无权限），记日志跳过
        logger.info("ima search_knowledge 库 %s 返回: %s", kb_id[:8], data.get("msg"))
        return []
    return [it for it in _extract_info_list(data) if isinstance(it, dict)]


def _extract_info_list(data: dict) -> list[dict]:
    """从 ima 返回里提取 info_list（兼容多种包装）。"""
    d = data.get("data") or {}
    if isinstance(d, dict):
        items = d.get("info_list")
        if isinstance(items, list):
            return items
    # 兜底：直接 data 是 list
    if isinstance(data, list):
        return data
    return []
