"""腾讯 ima 检索源客户端（实时外部检索源，不落库）。

调用 ima 官方 search_knowledge_base 端点，返回 highlight 片段。
与 reranker 同属 fail-open 设计——任何失败（超时/网络/鉴权）静默返回 []，
绝不阻断本地 RAG 主链路。

鉴权格式：ima 官方自定义 header（经联调确认，参考社区 Trae MCP 实践）：
  ima-openapi-clientid / ima-openapi-apikey
非标准 Authorization Bearer。端点地址/超时经 ima_search_base_url / ima_search_timeout 配置。
"""
import logging

import httpx

from app.core.config import get_settings
from app.services.ima_config_service import ResolvedIMAConfig

logger = logging.getLogger(__name__)

# ima 片段在 prompt 里的固定相关度（低于本地 RAG 的真实分，让 rerank/排序倾向本地结果）
IMA_FALLBACK_SCORE = 0.5


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
    """调用 ima 知识库检索，返回片段列表。

    返回统一形状：[{title, content, url?}]，content 为 highlight 片段。
    默认 fail-open：任何异常静默返回 []（检索主链路绝不能因 ima 挂掉而失败）。
    strict=True 时绕过降级，失败直接抛错——供 admin/设置页连通性测试用，
    否则降级会让"鉴权失败"也返回空列表，test 端点无法区分"失败"与"成功但无命中"。
    """
    if not query.strip():
        # 空 query 在 strict 下也直接返回空（不算错误）
        return []
    settings = get_settings()
    try:
        resp = httpx.post(
            settings.ima_search_base_url,
            headers=_build_headers(config),
            json={
                "query": query,
                "cursor": "",
                "limit": top_k,
            },
            timeout=settings.ima_search_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return _parse_ima_results(data)
    except Exception as e:
        if strict:
            raise  # 测试连通性场景：失败必须抛，让调用方拿到真实错误
        logger.warning("ima 检索调用失败，降级返回空（不影响本地 RAG）: %s", e)
        return []


def _parse_ima_results(data: dict) -> list[dict]:
    """解析 ima 返回为统一片段结构。

    ima search_knowledge_base 返回字段（社区 skill 文档）：
    media_id / title / parent_folder_id / highlight_content
    无全文，仅高亮片段。这里统一成 {title, content, url?}。
    """
    # 兼容几种可能的返回结构：{"results": [...]} / {"data": [...]} / [...]
    items = (
        data.get("results")
        or data.get("data")
        or data.get("items")
        or (data if isinstance(data, list) else [])
    )
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        content = it.get("highlight_content") or it.get("content") or it.get("snippet")
        if not content:
            continue
        out.append({
            "title": it.get("title") or "腾讯 ima",
            "content": content,
            "url": it.get("url"),
        })
    return out
