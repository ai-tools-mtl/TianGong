"""网页摄入服务:create_job / run_job / recover_pending_jobs + helpers。

scrape 同步返回 KnowledgeFile,crawl 异步建 WebIngestionJob + 后台轮询。
抓回内容标准化成 KnowledgeFile(source_type='external_web'),走现有入库流。

spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 5、7 节。

本文件分多个 Task 逐步填充:
- Task 9(本任务):常量 + URL 校验(SSRF)+ 配额函数
- Task 10:create_job + _scrape_sync + _crawl_async
- Task 11:run_job + _poll_and_ingest + _ingest_crawl_pages
- Task 12:recover_pending_jobs + get_job + list_jobs
"""

import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models import LLMCallLog, WebIngestionJob
from app.services.llm_log_helper import log_firecrawl_call


# ── 常量 ─────────────────────────────────────────────────────

MAX_CRAWL_PAGES_HARD_CAP = 100          # crawl 页数硬上限
CRAWL_TIMEOUT_HOURS = 2                 # crawl 轮询超时
CRAWL_POLL_INTERVAL_SECONDS = 30        # 轮询间隔
DEFAULT_QUOTA_PER_USER_PER_DAY = 200    # 每用户每日配额
MAX_URL_LENGTH = 2048

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {"metadata.google.internal", "169.254.169.254", "localhost"}


# ── URL 校验(SSRF 防护)──────────────────────────────────────

def _decode_ip_octet(part: str) -> int:
    """解析点分 IP 的一段(支持 0x hex / 0o octal 前缀 + 前导 0 octal 编码)。

    单独抽出以便点分形式能用统一逻辑解析每段:0x7f→127、0177→127(octal)、255→255。
    """
    p = part.lower()
    if p.startswith("0x"):
        return int(p, 16)
    if p.startswith("0o"):
        return int(p, 8)
    # 前导 0 + 全 0-7 数字 → 经典 octal SSRF 编码(如 0177 → 127)。
    # 不能用 int(p, 0):Python 3 对前导零十进制一律抛 ValueError。
    if len(p) > 1 and p.startswith("0") and all(c in "01234567" for c in p):
        return int(p, 8)
    return int(p)  # 普通十进制


def _try_parse_ip(hostname: str):
    """尝试把 hostname 解析为 IP(支持 decimal/hex/octal 等非标准编码)。

    SSRF 攻击者常用 http://2130706433(decimal)、http://0x7f000001(hex)、
    http://0177.0.0.1(octal)等编码绕过标准 ipaddress 解析。本函数尽力而为
    地把这些编码还原成标准 IP,供上层做 is_private/is_loopback 判断。

    返回 ipaddress 对象或 None(None 表示不是 IP,是域名)。

    残留风险:DNS rebinding(如 127.0.0.1.nip.io)无法在本地解析——
    依赖 Firecrawl 服务端做第二道 DNS 解析后再校验。
    """
    h = hostname.strip()

    # 1) 标准点分十进制 / IPv6(urlparse 已去掉 IPv6 方括号)
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        pass

    # 2) 纯整数 decimal IP(如 2130706433 = 127.0.0.1)
    if h.isascii() and h.isdigit():
        try:
            n = int(h)
            if 0 <= n < 2 ** 32:
                return ipaddress.ip_address(n)
        except ValueError:
            pass

    # 3) 0x/0o/0b 前缀的单段编码(如 0x7f000001 = 127.0.0.1)
    if h.lower().startswith(("0x", "0o", "0b")):
        try:
            n = int(h, 0)
            if 0 <= n < 2 ** 32:
                return ipaddress.ip_address(n)
        except ValueError:
            pass

    # 4) 点分形式,某段可能是 octal/hex(如 0177.0.0.1 / 0x7f.0.0.1)
    if h.count(".") == 3:
        parts = h.split(".")
        if all(parts):  # 无空段
            try:
                decoded = [_decode_ip_octet(p) for p in parts]
                if all(0 <= d < 256 for d in decoded):
                    return ipaddress.ip_address(".".join(str(d) for d in decoded))
            except ValueError:
                pass

    return None


def _validate_url(url: str) -> None:
    """校验 URL:协议白名单 + 长度 + 拒内网 IP(SSRF 防护)。"""
    if not url or len(url) > MAX_URL_LENGTH:
        raise ValidationError("URL 为空或过长")
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValidationError(f"不支持的协议:{parsed.scheme}(仅 http/https)")
    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("URL 缺少主机名")
    if hostname.lower() in BLOCKED_HOSTS:
        raise ValidationError("不允许访问该地址")
    # 拒内网 IP / loopback(含非标准编码:decimal/octal/hex)
    normalized_ip = _try_parse_ip(hostname)
    if normalized_ip is not None and (
        normalized_ip.is_private
        or normalized_ip.is_loopback
        or normalized_ip.is_reserved
        or normalized_ip.is_link_local
    ):
        raise ValidationError("不允许访问内网地址")


# ── 配额 ─────────────────────────────────────────────────────

def _used_pages_today(db: Session, user_id) -> int:
    """查询当日已用页数(SUM token_completion,action=firecrawl)。

    时间用 UTC,对齐 LLMCallLog.created_at 的 server_default now()(DB 写入即 UTC)。
    """
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    result = db.scalar(
        select(func.coalesce(func.sum(LLMCallLog.token_completion), 0)).where(
            (LLMCallLog.action == "firecrawl")
            & (LLMCallLog.user_id == user_id)
            & (LLMCallLog.created_at >= today_start)
        )
    )
    return int(result or 0)


def _reserve_quota(db: Session, *, user, mode: str, max_pages: int) -> None:
    """预扣配额。超额报错。

    scrape 预扣 1 页,crawl 预扣 max_pages。
    """
    pages = 1 if mode == "scrape" else max_pages
    used = _used_pages_today(db, user.id)
    if used + pages > DEFAULT_QUOTA_PER_USER_PER_DAY:
        raise ValidationError(
            f"今日配额已用尽({used}/{DEFAULT_QUOTA_PER_USER_PER_DAY}),"
            f"本次需 {pages} 页"
        )
    log_firecrawl_call(
        db, user_id=user.id, mode=mode, pages=pages,
        source="global", status="reserved",
    )


def _refund_quota(db: Session, *, user, pages: int) -> None:
    """退款(负 pages)。被质量过滤掉的页面退还配额。"""
    log_firecrawl_call(
        db, user_id=user.id, mode="scrape",
        pages=-pages, source="global", status="refund",
    )


def _correct_quota(db: Session, *, job: WebIngestionJob) -> None:
    """crawl 完成时按实际页数校正。多退少补。

    预扣的是 max_pages,实际有效页 = pages_fetched - pages_filtered;
    差额 delta 写一条 correction 日志(可正可负)。
    """
    actual = job.pages_fetched - job.pages_filtered
    reserved = job.max_pages
    delta = actual - reserved
    if delta != 0:
        log_firecrawl_call(
            db, user_id=job.user_id, mode="crawl",
            pages=delta, source="global", status="correction",
        )


# ── 主入口 ───────────────────────────────────────────────────

from app.core.background import spawn_background_task  # noqa: E402
from app.core.exceptions import AuthorizationError  # noqa: E402
from app.core.storage import get_storage  # noqa: E402
from app.models import KnowledgeFile  # noqa: E402
from app.parsing.content_filter import filter_content  # noqa: E402
from app.services import knowledge_service  # noqa: E402
from app.services.firecrawl_client import (  # noqa: E402
    FirecrawlClient, ResolvedFirecrawlConfig, resolve_firecrawl_config,
)


def create_job(
    db: Session, *, user, url: str, mode: str, scope: str, max_pages: int = 1,
):
    """发起网页摄入。scrape 同步返回 KnowledgeFile,crawl 异步返回 WebIngestionJob。

    校验顺序(关键:URL → mode → max_pages → scope/admin → 凭据 → 配额预扣 → 分叉)
    所有校验都在配额预扣之前——避免预扣后才发现参数错,被迫退款。
    """
    # ① 校验
    _validate_url(url)
    if mode not in ("scrape", "crawl"):
        raise ValidationError(f"不支持的模式:{mode}")
    if mode == "crawl" and max_pages > MAX_CRAWL_PAGES_HARD_CAP:
        raise ValidationError(f"max_pages 上限 {MAX_CRAWL_PAGES_HARD_CAP}")
    if scope == "global" and getattr(user, "role", None) != "admin":
        raise AuthorizationError("仅 admin 可入 global 库")

    # ② 凭据(无配置直接报错,不静默)
    config = resolve_firecrawl_config(db)
    if config is None:
        raise ValidationError("Firecrawl 未配置,请联系管理员")

    # ③ 配额预扣(scrape 预扣 1 页,crawl 预扣 max_pages)
    _reserve_quota(db, user=user, mode=mode, max_pages=max_pages)

    # ④ 分叉
    if mode == "scrape":
        return _scrape_sync(
            db, user=user, url=url, scope=scope, config=config,
        )
    return _crawl_async(
        db, user=user, url=url, scope=scope,
        max_pages=max_pages, config=config,
    )


def _derive_filename(title: str, url: str) -> str:
    """从标题或 URL 推导展示用文件名(.md)。"""
    if title:
        # 文件名安全:去掉 Windows/Linux 非法字符
        safe = "".join(c for c in title if c not in '\\/:*?"<>|')[:80]
        return f"{safe}.md" if safe else "webpage.md"
    parsed = urlparse(url)
    base = parsed.path.strip("/").replace("/", "_") or parsed.netloc
    return f"{base[:80]}.md"


def _scrape_sync(
    db: Session, *, user, url: str, scope: str,
    config: ResolvedFirecrawlConfig,
) -> KnowledgeFile:
    """单页同步流:scrape → filter → upload。

    抓取失败 / 质量过滤未通过时退款(负 pages 日志),保持净用量准确。
    """
    client = FirecrawlClient(config.api_key, config.base_url)
    result = client.scrape(url)

    # 抓取失败(SDK 异常 / 4xx / 5xx 全部由 client 归一成 fetch_failed=True)
    if result.fetch_failed:
        _refund_quota(db, user=user, pages=1)
        raise ValidationError("页面抓取失败")

    # 质量过滤(空白页 / 导航页 / 非中英文)
    filtered = filter_content(result.markdown, result.title)
    if filtered is None:
        _refund_quota(db, user=user, pages=1)
        raise ValidationError("页面内容未通过质量过滤(可能为空白页/导航页/非中英文)")

    content_bytes = filtered.markdown.encode("utf-8")
    filename = _derive_filename(filtered.title, url)
    storage = get_storage()

    if scope == "global":
        kf = knowledge_service.upload_to_global(
            db, storage=storage, uploader=user,
            filename=filename, content=content_bytes,
            mime="text/markdown", text=filtered.markdown, url=url,
        )
    else:
        kf = knowledge_service.upload_external(
            db, storage=storage, user=user,
            filename=filename, content=content_bytes,
            mime="text/markdown", text=filtered.markdown, url=url,
        )
    return kf


def _crawl_async(
    db: Session, *, user, url: str, scope: str, max_pages: int,
    config: ResolvedFirecrawlConfig,
) -> WebIngestionJob:
    """整站异步流:start_crawl(非阻塞)→ 建 WebIngestionJob → spawn 轮询任务。

    start_crawl 立即返回 firecrawl job_id;真正抓页 + 入库由 run_job 异步做。
    """
    client = FirecrawlClient(config.api_key, config.base_url)
    handle = client.start_crawl(url, limit=max_pages)

    job = WebIngestionJob(
        user_id=user.id, scope=scope, url=url, mode="crawl",
        max_pages=max_pages, firecrawl_job_id=handle.firecrawl_job_id,
        status="running",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    spawn_background_task(run_job, str(job.id))
    return job


# ── run_job / _poll_and_ingest / recover_pending_jobs ────────
# (Task 11/12 实现)


def run_job(job_id: str) -> None:
    """BackgroundTask 入口:轮询 Firecrawl + 入库。Task 11 实现。

    占位为 NotImplementedError——Task 10 的测试里 spawn_background_task 被 mock,
    run_job 不会被真调,占位安全。Task 11 替换为真实实现。
    """
    raise NotImplementedError("run_job 在 Task 11 实现")
