"""Firecrawl 客户端封装 + 凭据解析 + 连通性探活。

封装薄客户端,屏蔽 firecrawl-py SDK 细节,对上层只暴露领域语义方法。
返回 dataclass(不返回 SDK 原始对象),换 SDK/供应商时只改本文件。

配置走纯 env(FIRECRAWL_BASE_URL + FIRECRAWL_API_KEY),指向本地自部署 firecrawl 微服务
(见 docker-compose.yml 的 firecrawl 服务)。与 embedding/rerank 同范式,无 admin 配置页。
可用性 = 服务连通性,由 check_firecrawl_health 探活,启动时 main.py 调用告警。
"""

from dataclasses import dataclass

import httpx

from firecrawl.v2 import FirecrawlClient as _FirecrawlSDK

from app.core.config import get_settings


# ── dataclass ────────────────────────────────────────────────

@dataclass
class ScrapeResult:
    """单页抓取结果。"""
    url: str
    title: str
    markdown: str
    status_code: int
    fetch_failed: bool


@dataclass
class CrawlJobHandle:
    """crawl 任务句柄(start_crawl 立即返回)。"""
    firecrawl_job_id: str


@dataclass
class CrawlStatus:
    """crawl 任务轮询状态。

    status 取值:scraping(进行中) / completed / failed / cancelled。
    进行中 / 失败 / 取消 时 pages 为空。
    """
    status: str
    completed: int
    total: int
    pages: list[ScrapeResult]
    credits_used: int


@dataclass
class ResolvedFirecrawlConfig:
    """解析后的 Firecrawl 配置。"""
    api_key: str
    base_url: str


# ── 客户端 ────────────────────────────────────────────────────

class FirecrawlClient:
    """firecrawl-py SDK(v2 推荐 API)的薄封装。

    SDK 实际方法名(探查自 firecrawl-py 4.32.1,firecrawl.v2.FirecrawlClient):
    - FirecrawlClient(api_key=..., api_url=...)   # 注意是 api_url 不是 base_url
    - scrape(url, formats=[...]) -> Document      # pydantic 模型
    - start_crawl(url, limit=...) -> CrawlResponse  # 含 .id
    - get_crawl_status(job_id) -> CrawlJob        # status / total / completed / credits_used / data

    注意:`from firecrawl import Firecrawl` 拿到的是 v1 旧类(只有 parse 方法),
    会造成 client.scrape() AttributeError 被 try/except 吞成 fetch_failed=True 的 silent failure。
    必须从 firecrawl.v2 显式 import FirecrawlClient。

    对外接口(scrape/start_crawl/check_crawl + dataclass)与 SDK 版本无关:
    换 SDK / 供应商时只改本类内部映射。
    """

    def __init__(self, api_key: str, base_url: str = "http://localhost:3002"):
        # SDK 初始化参数是 api_url(不是 base_url)。本类对外仍叫 base_url,内部转换。
        # _FirecrawlSDK 在模块顶部 import(便于测试 patch app.services.firecrawl_client._FirecrawlSDK)。
        self._sdk = _FirecrawlSDK(api_key=api_key, api_url=base_url)

    def scrape(self, url: str) -> ScrapeResult:
        """同步抓单页。异常时返回 fetch_failed=True(不抛,由上层决定如何处理)。"""
        try:
            doc = self._sdk.scrape(url, formats=["markdown"])
            return self._doc_to_result(doc, url=url)
        except Exception:
            return ScrapeResult(
                url=url, title="", markdown="", status_code=0, fetch_failed=True,
            )

    def start_crawl(self, url: str, *, limit: int) -> CrawlJobHandle:
        """异步发起整站抓取。立即返回 job_id,不阻塞。"""
        resp = self._sdk.start_crawl(url, limit=limit)
        return CrawlJobHandle(firecrawl_job_id=self._get(resp, "id"))

    def check_crawl(self, firecrawl_job_id: str) -> CrawlStatus:
        """查询 crawl 任务状态。进行中 / 失败 / 取消 时 pages 为空。"""
        job = self._sdk.get_crawl_status(firecrawl_job_id)
        status = self._get(job, "status") or "scraping"
        pages: list[ScrapeResult] = []
        if status == "completed":
            data = self._get(job, "data") or []
            for item in data:
                pages.append(self._doc_to_result(item, url=self._get_meta(item, "source_url", "")))
        return CrawlStatus(
            status=status,
            completed=self._get(job, "completed") or 0,
            total=self._get(job, "total") or 0,
            pages=pages,
            credits_used=self._get(job, "credits_used") or 0,
        )

    # ── 内部:从 SDK pydantic 对象提取字段(同时兼容 dict,便于测试 mock)──

    @staticmethod
    def _get(obj, name, default=None):
        """属性 / 字典双兼容取值。"""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    @classmethod
    def _doc_to_result(cls, doc, *, url: str) -> ScrapeResult:
        """SDK Document(pydantic)→ ScrapeResult。doc 为 None 时算 fetch_failed。"""
        if doc is None:
            return ScrapeResult(url=url, title="", markdown="", status_code=0, fetch_failed=True)
        meta = cls._get(doc, "metadata")
        return ScrapeResult(
            url=url or cls._get(meta, "source_url", "") or "",
            title=cls._get(meta, "title", "") or "",
            markdown=cls._get(doc, "markdown", "") or "",
            status_code=cls._get(meta, "status_code", 200) or 200,
            fetch_failed=False,
        )

    @classmethod
    def _get_meta(cls, doc, name, default=None):
        return cls._get(cls._get(doc, "metadata"), name, default)


# ── 凭据解析(纯 env)─────────────────────────────────────────

def resolve_firecrawl_config() -> ResolvedFirecrawlConfig:
    """从 env 读 firecrawl 配置(本地自部署微服务地址 + key)。

    env 总有默认值(base_url=localhost:3002, api_key=fc-local-default-key),
    故总返回 ResolvedFirecrawlConfig。可用性由 check_firecrawl_health 判断。
    """
    s = get_settings()
    return ResolvedFirecrawlConfig(
        api_key=s.firecrawl_api_key,
        base_url=s.firecrawl_base_url,
    )


# ── 连通性探活 ───────────────────────────────────────────────

def check_firecrawl_health(base_url: str | None = None) -> bool:
    """探测 firecrawl 服务是否可达。可达返回 True,不可达/异常返回 False。

    供启动时探活(main.py)和摄入前校验(web_ingestion_service)调用。
    timeout 3s(与 rerank 探活同级),异常一律视为不可达,不抛。
    """
    if base_url is None:
        base_url = get_settings().firecrawl_base_url
    try:
        # firecrawl 根路径返回 200(状态页),作为轻量探活端点。
        r = httpx.get(base_url.rstrip("/") + "/", timeout=3.0)
        return r.status_code < 500
    except Exception:
        return False
