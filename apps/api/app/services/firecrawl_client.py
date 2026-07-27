"""Firecrawl 客户端封装 + 凭据解析 + admin 配置 get/set。

封装薄客户端,屏蔽 firecrawl-py SDK 细节,对上层只暴露领域语义方法。
返回 dataclass(不返回 SDK 原始对象),换 SDK/供应商时只改本文件。

凭据解析三级 fallback:全局 SystemSetting(firecrawl_enabled + firecrawl_config)
→ env(FIRECRAWL_API_KEY)。无可用配置返回 None。

spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 4 节。
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from firecrawl.v2 import FirecrawlClient as _FirecrawlSDK

from app.core.config import get_settings
from app.core.security import decrypt_value, encrypt_value
from app.models import SystemSetting
from app.services.llm_config_service import _mask_key


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
    source: str   # "global" / "env"


_DEFAULT_BASE_URL = "https://api.firecrawl.dev"


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

    def __init__(self, api_key: str, base_url: str = _DEFAULT_BASE_URL):
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


# ── 凭据解析 ─────────────────────────────────────────────────

def resolve_firecrawl_config(db: Session) -> ResolvedFirecrawlConfig | None:
    """三级 fallback:全局 SystemSetting → env。无可用配置返回 None。

    全局条件:firecrawl_enabled.value.enabled is True AND
              firecrawl_config.value.api_key_encrypted 非空。
    """
    # 1) 全局 SystemSetting
    enabled_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "firecrawl_enabled")
    )
    if enabled_setting and enabled_setting.value.get("enabled") is True:
        cfg_setting = db.scalar(
            select(SystemSetting).where(SystemSetting.key == "firecrawl_config")
        )
        if cfg_setting and cfg_setting.value.get("api_key_encrypted"):
            api_key = decrypt_value(cfg_setting.value["api_key_encrypted"])
            base_url = cfg_setting.value.get("base_url") or _DEFAULT_BASE_URL
            return ResolvedFirecrawlConfig(
                api_key=api_key, base_url=base_url, source="global",
            )
    # 2) env 兜底
    s = get_settings()
    if s.firecrawl_api_key:
        return ResolvedFirecrawlConfig(
            api_key=s.firecrawl_api_key,
            base_url=s.firecrawl_base_url or _DEFAULT_BASE_URL,
            source="env",
        )
    return None


# ── admin 配置 get/set ───────────────────────────────────────

def get_firecrawl_settings(db: Session) -> dict:
    """读全局配置(api_key 脱敏)。未配置时返回安全默认值。"""
    enabled_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "firecrawl_enabled")
    )
    cfg_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "firecrawl_config")
    )
    api_key_masked = ""
    if cfg_setting and cfg_setting.value.get("api_key_encrypted"):
        try:
            api_key_masked = _mask_key(decrypt_value(cfg_setting.value["api_key_encrypted"]))
        except Exception:
            api_key_masked = ""
    return {
        "enabled": bool(enabled_setting and enabled_setting.value.get("enabled")),
        "api_key_masked": api_key_masked,
        "base_url": cfg_setting.value.get("base_url", "") if cfg_setting else "",
    }


def set_firecrawl_settings(
    db: Session, *,
    enabled: bool,
    api_key: str = "",
    base_url: str | None = None,
    updated_by=None,
) -> None:
    """upsert 全局配置。

    - enabled:总是写。
    - api_key 空串表示不修改现有 key(保留)。
    - base_url 为 None 表示不改;非 None(含空串)则覆盖。
    - 仅当 api_key 或 base_url 至少一项被显式提供时,才写 firecrawl_config 行。
    """
    # 1) enabled 开关
    enabled_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "firecrawl_enabled")
    )
    if enabled_setting:
        enabled_setting.value = {"enabled": enabled}
    else:
        db.add(SystemSetting(
            key="firecrawl_enabled", value={"enabled": enabled},
            updated_by=updated_by,
        ))

    # 2) config 行(api_key / base_url)
    if api_key or base_url is not None:
        cfg_setting = db.scalar(
            select(SystemSetting).where(SystemSetting.key == "firecrawl_config")
        )
        current = cfg_setting.value if cfg_setting else {}
        new_value = {
            "base_url": base_url if base_url is not None
            else current.get("base_url", _DEFAULT_BASE_URL),
        }
        if api_key:
            new_value["api_key_encrypted"] = encrypt_value(api_key)
        elif current.get("api_key_encrypted"):
            # 保留已有 key(不覆盖)
            new_value["api_key_encrypted"] = current["api_key_encrypted"]
        if cfg_setting:
            cfg_setting.value = new_value
        else:
            db.add(SystemSetting(
                key="firecrawl_config", value=new_value, updated_by=updated_by,
            ))
    db.commit()
