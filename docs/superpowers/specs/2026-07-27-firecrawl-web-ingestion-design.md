# Firecrawl 网页摄入 — 设计文档

> 状态:Draft(v1.0,2026-07-27)
> 作者:ZCode(基于 brainstorming 会话产出)
> 关联:补齐设计文档第 11.2 章「P1 专利检索接口对接」的网页摄入分支;与现有 pgvector RAG 栈互补、不替换。

---

## 1. 目标与范围

### 做什么

给天工知识库增加**网页摄入能力**:用户/admin 贴一个 URL(单页 scrape)或一整个站点(整站 crawl),抓回干净 Markdown → 走现有 `KnowledgeFile` + `KnowledgeChunk` + 审核流 + 检索链路。

- **抓取范围**:单页 scrape + 整站 crawl(带上限防失控)
- **使用者**:用户自助(personal 库)+ admin 批量潢库(global 库)两套入口,底层共享抓取服务
- **凭据**:全局 Firecrawl key(运营方付费,存 `SystemSetting`,加密)
- **质量过滤**:规则层(Markdown 去噪 + 长度阈值 + 语言检测)
- **异步模型**:复用天工现有 BackgroundTasks + 重启恢复模式,但因 crawl 是长任务,改用线程池异步(不阻塞 startup)

### 不做什么(YAGNI,显式排除)

| 排除项 | 理由 |
|---|---|
| Firecrawl 自部署版 | AGPL-3.0 传染,对要商用的天工有风险 → 用云 API |
| LLM 相关性判断 | 规则过滤已够,成本敏感 |
| map 模式(只列 URL 不抓) | 用户/admin 要的是内容入库,不是爬虫工具 |
| 用户自配 Firecrawl key(BYOK) | 单用户大多没 Firecrawl 账号,门槛太高。留作未来扩展点 |
| Celery/ARQ 任务队列 | 现有 BackgroundTasks + 线程池已够,引入 Redis 违背精简栈 |
| 改动现有 RAG 检索/审核/embedding | 本 spec 是纯增量,与后续「检索质量升级」解耦 |
| 配额阈值 SystemSetting 化 | 常量写死即可,后续再调 |

### 依赖关系

- 与设计文档 11.2「P1 专利检索接口对接」**互补**:专利检索查专利数据库,网页摄入抓公开网页,殊途同归都进 `KnowledgeChunk`
- **不动现有代码**:审核流、去重、三域隔离、检索、embedding 全部零改动复用

---

## 2. 总体架构与数据流

### 模块分层

```
┌─────────────────────────────────────────────────────────┐
│  API 层  apps/api/app/api/knowledge.py                  │
│  POST /knowledge/ingest/web       (user/admin 通用)     │
│  GET  /knowledge/ingest/jobs/{id} (查 crawl 任务状态)    │
│  GET  /knowledge/ingest/jobs      (列任务)               │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Service 层  web_ingestion_service.py  (新建)           │
│  - create_job()        入口分叉(scrape 同步/crawl 异步) │
│  - run_job()           BackgroundTask 主循环              │
│  - _poll_and_ingest()  轮询 Firecrawl 状态               │
│  - recover_pending_jobs()  重启恢复扫描                   │
└───────┬───────────────────────┬─────────────────────────┘
        │                       │
        ▼                       ▼
┌──────────────────────┐   ┌─────────────────────────────┐
│ Firecrawl 客户端      │   │  复用现有 knowledge_service  │
│ firecrawl_client.py  │   │  - upload_external (personal)│
│ (新建,封装 SDK)       │   │  - upload_to_global (global) │
│ + resolve_firecrawl_ │   │  → KnowledgeFile + Chunk     │
│   config()           │   │  → 现有审核流/检索零改动       │
└──────────────────────┘   └─────────────────────────────┘
        │
        ▼
┌──────────────────────┐
│ 质量过滤              │
│ parsing/             │
│ content_filter.py    │
│ (新建)                │
└──────────────────────┘
```

### 关键架构决策

**① 抓取任务与内容存储分离(方案 C)**

- 抓取任务的状态机(轮询 Firecrawl、计页数、扣配额)独立成 `WebIngestionJob` 表
- 抓回的内容标准化成 `KnowledgeFile`(`source_type='external_web'`),走现有入库流
- **结果**:审核流、去重、三域隔离、检索全部零改动复用

**② scrape 同步 / crawl 异步**

- 单页 scrape 几秒返回,API 同步等待,直接返回 KnowledgeFile(体验流畅)
- 整站 crawl 是长任务(可能数分钟到数小时),建 WebIngestionJob + BackgroundTask 轮询 → 用户查状态接口

**③ 配额预扣 + 完成时校正**

- 建 job 时预扣(scrape 预扣 1 页,crawl 预扣 max_pages)
- 完成时按实际页数校正(`pages_fetched` - `pages_filtered`)
- 被质量过滤掉的页全额退款(成本不该用户担)

### 流 A:单页 scrape(同步)

```
POST /knowledge/ingest/web {url, mode:scrape, scope:personal}
  → 校验 URL + 配额预扣(1 页)
  → firecrawl_client.scrape(url)         [同步,几秒]
  → filter_content(markdown)             [规则过滤]
  → knowledge_service.upload_external(...)  [复用现有]
  → KnowledgeFile(source_type=external_web) + KnowledgeChunk
  → 配额校正(实际 1 页)+ 返回 file_id
```

### 流 B:整站 crawl(异步)

```
POST /knowledge/ingest/web {url, mode:crawl, scope:global, max_pages:50}
  → 校验 + 配额预扣(max_pages)
  → firecrawl_client.start_crawl(url) → firecrawl_job_id
  → 建 WebIngestionJob(status=running)
  → spawn_background_task(run_job, job_id)  [异步]
  → 立即返回 job_id(前端轮询)

[BackgroundTask 内 run_job]
  while 未超时(默认 2h):
    status = client.check_crawl(firecrawl_job_id)
    if completed:
      for page in status.pages:
        filtered = filter_content(page.markdown)
        if filtered: knowledge_service.upload_to_global(page)  [复用]
      job.status=completed
      配额校正
      return
    if failed: job.status=failed
    sleep(30s)
```

---

## 3. 数据模型

### 新建表:`WebIngestionJob`

**文件**:`apps/api/app/models/web_ingestion_job.py`

对齐天工 ORM 风格:继承 `Base, IdMixin, TimestampMixin`,列类型严格用 `sa.Uuid()` / `DateTime(timezone=True)`,JSON 列用 JSONB-with-variant 兼容 SQLite 测试库(抄 `ee50036c9e86_add_knowledge_chunks_with_pgvector.py`)。

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin
# JSONType 在 base.py 定义,已是 JSONB-with-variant(PG 用 JSONB,SQLite 用 JSON),
# 直接复用 knowledge_chunk.py 同款写法


class WebIngestionJob(Base, IdMixin, TimestampMixin):
    __tablename__ = "web_ingestion_jobs"

    # 发起者
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String(20))  # personal / global

    # 抓取参数
    url: Mapped[str] = mapped_column(String(2048))
    mode: Mapped[str] = mapped_column(String(10))  # scrape / crawl
    max_pages: Mapped[int] = mapped_column(Integer, default=1)  # crawl 上限

    # Firecrawl 远端任务跟踪
    firecrawl_job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 状态机:pending → running → completed / failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    # 抓取结果统计
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    pages_filtered: Mapped[int] = mapped_column(Integer, default=0)  # 被质量过滤掉的
    file_ids: Mapped[list | None] = mapped_column(JSONType, nullable=True)  # 生成的 KF.id 列表

    # 错误与时间
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

**设计说明**:

1. **status 状态机只有 4 态**:`pending` → `running` → `completed` / `failed`。不引入 `partial`——每页独立入库,部分失败用 `pages_fetched` + `error_message` 表达,不污染状态机。

2. **`file_ids` 用 JSONB 数组,非关联表**:整站 crawl 一对多生成多个 KnowledgeFile,但这是**结果快照不是关联关系**(不建 FK)。`KnowledgeFile` 不知道自己来自哪个 job(避免污染那张表),job 这边记下生成的 file_id 列表供查询。若某 file 被删,job 里的 id 失效但不影响数据完整性。

3. **`pages_fetched` vs `pages_filtered`**:前者是 Firecrawl 实际返回的页数,后者是过质量过滤后剩下的。差值 = 被丢弃的垃圾页数。admin 调质量阈值的关键观测值。

4. **不存抓回的原文**:原文存 minio(走 `KnowledgeFile.object_key`),job 表不冗余——避免双份存储。

### 扩展现有表:`KnowledgeFile`(加 url 字段)

**文件**:`apps/api/app/models/knowledge_file.py`

```python
url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
```

**用途**:
- 检索结果展示来源(「来自 https://...」)
- admin 审核时看原始来源
- 整站 crawl 同 URL 去重(配合现有 SHA256 去重,URL 维度先拒)

**为什么不复用 `filename`**:filename 是展示用的标题(抓回的 `<title>`),URL 是结构化来源,语义不同。docx/pdf 上传时 url=None,不影响现有逻辑。

**`source_type` 新增枚举值**:`external_web`(对齐现有 `external_docx` / `external_pdf` / `disclosure_export` 命名)。

### 迁移文件

**文件**:`apps/api/alembic/versions/<hash>_add_web_ingestion_jobs.py`

抄 `ee50036c9e86_add_knowledge_chunks_with_pgvector.py` 的 autogenerate 风格:
- `revision` 用新 12 位 hex,`down_revision` 指向当前 head `b_split_emb_config`
- `op.create_table("web_ingestion_jobs", ...)` 显式列所有列(列类型严格对齐 `IdMixin`/`TimestampMixin`:id=`sa.Uuid()`,timestamps=`DateTime(timezone=True)` + `server_default=sa.text('now()')` NOT NULL;`file_ids` 列用 `postgresql.JSONB().with_variant(sa.JSON(), 'sqlite')` 兼容双库)
- `op.create_index(...)` 给 `user_id`、`status`、`created_at`
- `op.add_column("knowledge_files", sa.Column("url", sa.String(2048), nullable=True))`
- downgrade 完整对称:`drop_column` + `drop_index` + `drop_table`
- 用 `op.batch_alter_table` 兼容 SQLite

**不建 SystemSetting 迁移**:`firecrawl_*` 是运行时数据(像 `llm_global_*`),首次配置时 upsert 进 `system_settings` 表,不需要 schema 迁移。

### 配额记账:复用 `LLMCallLog`

**不新建配额表**。每次 Firecrawl 调用记一条 `LLMCallLog`:
- `action = "firecrawl"`(新增枚举值)
- `provider = "global"` 或 `"env"`
- `token_prompt / token_completion` = NULL(无 token 概念)
- `duration_ms` = NULL(用 `error` 字段记页数?不,见下)

**`LLMCallLog` 字段不够用的问题**:它没有「页数」字段。两个解法:
- **方案 a(推荐)**:复用 `token_completion` 记 `pages_fetched`(语义略歪但零迁移)
- **方案 b**:新建 `firecrawl_usage_logs` 表(干净但增加表)

**MVP 选 a**:用 `token_completion` 记页数,在 `llm_log_helper.py` 加 `log_firecrawl_call(...)` 函数,文档注释写明该字段语义。配额查询走 admin 后台按 `action='firecrawl'` 聚合 SUM。若后续 admin 看板需要更细,再建独立表(留扩展点)。

---

## 4. Firecrawl 客户端封装与凭据链路

**文件**:`apps/api/app/services/firecrawl_client.py`(新建)

封装薄客户端,屏蔽 SDK 细节,对上层只暴露领域语义方法。

### 客户端接口

```python
from dataclasses import dataclass


@dataclass
class ScrapeResult:
    """单页抓取结果。"""
    url: str
    title: str          # <title>,可能为空
    markdown: str       # 干净正文
    status_code: int    # HTTP 状态码(质量判断用)
    fetch_failed: bool  # 抓取本身失败(网络/404)


@dataclass
class CrawlJobHandle:
    """crawl 任务的句柄(发起后立即返回)。"""
    firecrawl_job_id: str


@dataclass
class CrawlStatus:
    """crawl 任务轮询状态。"""
    status: str         # scrape(进行中) / completed / failed
    completed: int
    total: int
    pages: list[ScrapeResult]  # 仅 status=completed 时有值
    credits_used: int


class FirecrawlClient:
    def __init__(self, api_key: str, base_url: str = "https://api.firecrawl.dev"):
        from firecrawl import Firecrawl
        self._sdk = Firecrawl(api_key=api_key, api_url=base_url)

    def scrape(self, url: str) -> ScrapeResult:
        """同步抓单页。返回结构化结果,异常封装为 fetch_failed=True。"""
        ...

    def start_crawl(self, url: str, *, limit: int) -> CrawlJobHandle:
        """异步发起整站抓取。立即返回 job_id,不阻塞。"""
        ...

    def check_crawl(self, firecrawl_job_id: str) -> CrawlStatus:
        """查询 crawl 任务状态。进行中时 pages 为空。"""
        ...
```

### 设计要点

1. **返回 dataclass,不返回 SDK 原始对象**——上层 service 不依赖 `firecrawl` 包的类型,换 SDK/供应商时只改这一个文件。对齐天工 `ResolvedChatConfig` / `ResolvedEmbeddingConfig` 模式。

2. **`start_crawl` 而非 `crawl`**:用异步发起模式,拿到 `firecrawl_job_id` 存进 `WebIngestionJob`,然后我们的 `poll_crawl()` 按自己节奏轮询。**SDK 自带的 `crawl()` 阻塞模式不能用**——它会在单次 HTTP 调用里等完整站跑完,worker 会被挂住几十分钟。

3. **`check_crawl` 返回 `pages` 仅 completed 时填充**:避免进行中状态把半成品数据拉回来。

### 凭据解析:`resolve_firecrawl_config()`

**位置**:`firecrawl_client.py` 同模块内(职责分离,不挤进 `llm_config_service.py`)。

```python
@dataclass
class ResolvedFirecrawlConfig:
    api_key: str
    base_url: str
    source: str   # "global" / "env"  (无 custom,因为不做 BYOK)


def resolve_firecrawl_config(db: Session) -> ResolvedFirecrawlConfig | None:
    """三级 fallback:全局 SystemSetting → env。无可用配置返回 None。

    与 chat/embedding 不同,Firecrawl 只有「全局」一层。
    不存在用户级配置(不做 BYOK,见 spec 第 1 节)。
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
            from app.services.llm_config_service import decrypt_value
            api_key = decrypt_value(cfg_setting.value["api_key_encrypted"])
            base_url = cfg_setting.value.get("base_url", "https://api.firecrawl.dev")
            return ResolvedFirecrawlConfig(api_key, base_url, source="global")

    # 2) env 兜底
    s = get_settings()
    if s.firecrawl_api_key:
        return ResolvedFirecrawlConfig(
            s.firecrawl_api_key,
            s.firecrawl_base_url or "https://api.firecrawl.dev",
            source="env",
        )

    # 3) 都没有 → None(API 层报「Firecrawl 未配置」)
    return None
```

**与 chat/embedding 凭据链路区别**:

| 维度 | chat/embedding | Firecrawl |
|---|---|---|
| 用户级配置(BYOK) | ✅ 有(`user_llm_configs`) | ❌ 无 |
| 全局配置 | ✅ SystemSetting | ✅ SystemSetting |
| env 兜底 | ✅ | ✅ |
| 成本归属 | 用户 key→用户担 / 全局→运营方担 | 永远运营方担(本 spec 不做 BYOK) |

resolve 函数简化:只查全局 + env 两级,不查用户表。**有意决策,不是漏做**。

### admin 配置 API

新增 admin 端点:
- `GET /admin/console/firecrawl` → 读全局配置(返回脱敏 api_key)
- `PUT /admin/console/firecrawl` → 写全局配置(`firecrawl_enabled` + `firecrawl_config`)

内部函数(放在 `firecrawl_client.py`):
```python
def get_firecrawl_settings(db) -> dict: ...
# 返回 {enabled, api_key_masked, base_url}

def set_firecrawl_settings(db, *, enabled, api_key, base_url, updated_by) -> None: ...
# upsert + encrypt(复用 llm_config_service.encrypt_value/decrypt_value)
```

### env 配置(`config.py` 追加)

```python
# Firecrawl (web ingestion)
firecrawl_api_key: str = ""
firecrawl_base_url: str = "https://api.firecrawl.dev"
firecrawl_enabled: bool = False
```

默认空串/False,未配不崩。env 兜底,真正运行时由 SystemSetting 覆盖(对齐 `glm_api_key` 角色)。

### 加密复用

`encrypt_value` / `decrypt_value` 已在 `llm_config_service.py` 存在(被 chat/embedding 用),**直接复用**,不重写。

### 依赖

`pyproject.toml` 加:`firecrawl-py>=1.0.0`(实现时确认最新稳定版)。

---

## 5. web_ingestion_service 核心逻辑

**文件**:`apps/api/app/services/web_ingestion_service.py`(新建)

对齐 `parse_service.py` 风格:每个公共函数自开独立 Session(BackgroundTasks 在响应返回后跑,请求作用域 session 已关闭),幂等保护开头先查状态。

### 公共函数清单

```python
def create_job(db, *, user, url, mode, scope, max_pages=1) -> WebIngestionJob | KnowledgeFile: ...
def run_job(job_id: str) -> None: ...
def recover_pending_jobs(stale_minutes: int = 10) -> int: ...
def get_job(db, *, job_id, user) -> WebIngestionJob: ...        # API 查询用
def list_jobs(db, *, user) -> list[WebIngestionJob]: ...         # API 列表用
```

### `create_job()`:入口分叉

```python
def create_job(db, *, user, url, mode, scope, max_pages=1):
    # ① 校验
    _validate_url(url)
    if mode == "crawl" and max_pages > MAX_CRAWL_PAGES_HARD_CAP:  # 100
        raise ValidationError(f"max_pages 上限 {MAX_CRAWL_PAGES_HARD_CAP}")
    if scope == "global" and not user.is_admin:
        raise AuthorizationError("仅 admin 可入 global 库")

    # ② 凭据(无配置直接报错,不静默)
    config = resolve_firecrawl_config(db)
    if config is None:
        raise ValidationError("Firecrawl 未配置,请联系管理员")

    # ③ 配额预扣
    _reserve_quota(db, user, mode, max_pages)

    # ④ 分叉
    if mode == "scrape":
        return _scrape_sync(db, user=user, url=url, scope=scope, config=config)
    else:  # crawl
        return _crawl_async(db, user=user, url=url, scope=scope,
                            max_pages=max_pages, config=config)
```

**要点**:
- **scrape 不建 WebIngestionJob**——同步,几秒返回,直接生成 KnowledgeFile。建 job 徒增记录。
- **crawl 建 WebIngestionJob**——需跟踪远端任务状态。
- **URL 校验在 service 层**,不放 API 层——service 可被 admin 脚本/未来 CLI 复用。

### `_scrape_sync()`:单页同步流

```python
def _scrape_sync(db, *, user, url, scope, config) -> KnowledgeFile:
    client = FirecrawlClient(config.api_key, config.base_url)
    result = client.scrape(url)

    # 质量过滤
    filtered = filter_content(result.markdown, result.title)
    if filtered is None:
        _refund_quota(db, user, pages=1)  # 被过滤掉的全额退款
        raise ValidationError("页面内容未通过质量过滤(可能为空白页/导航页/非中英文)")

    # 复用现有入库流(source_type=external_web)
    content_bytes = filtered.markdown.encode("utf-8")
    filename = _derive_filename(filtered.title, url)
    if scope == "global":
        kf = knowledge_service.upload_to_global(
            db, storage=get_storage(), uploader=user,
            filename=filename, content=content_bytes,
            mime="text/markdown", text=filtered.markdown,
        )
    else:
        kf = knowledge_service.upload_external(
            db, storage=get_storage(), user=user,
            filename=filename, content=content_bytes,
            mime="text/markdown", text=filtered.markdown,
        )

    # 记调用日志 + 配额校正(实际 1 页)
    log_firecrawl_call(db, user_id=user.id, mode="scrape",
                       pages=1, source=config.source)
    _set_kf_url(kf, url)  # 给 KnowledgeFile 写 url 字段(现有 upload 不带 url)
    return kf
```

**关键点**:
- `upload_to_global` / `upload_external` 现有签名完全够用——只接受 `filename/content/mime/text`,不关心来源。`source_type='external_web'`,filename 用 `<title>`(无标题时 URL 域名+路径)。
- **现有去重(SHA256)、chunker、embedding、审核流全免费复用**。
- **被过滤就退款**:scrape 失败/质量不过的成本不该用户担。
- **`_set_kf_url`**:现有 `upload_external` / `upload_to_global` 不写 url 字段(本 spec 新增)。两选一:(a) 在 upload 函数加可选参数 `url=None`;(b) 抓完后再 update。**MVP 选 (a)**——改两个函数签名加 `url: str | None = None`,向后兼容。

### `_crawl_async()`:整站异步流

```python
def _crawl_async(db, *, user, url, scope, max_pages, config) -> WebIngestionJob:
    client = FirecrawlClient(config.api_key, config.base_url)

    # ① 立即发起远端任务
    handle = client.start_crawl(url, limit=max_pages)

    # ② 建 job 记录
    job = WebIngestionJob(
        user_id=user.id, scope=scope, url=url, mode="crawl",
        max_pages=max_pages, firecrawl_job_id=handle.firecrawl_job_id,
        status="running",  # 直接 running,远端已启动
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # ③ 启动后台轮询(线程池异步,不阻塞响应)
    from app.core.background import spawn_background_task
    spawn_background_task(run_job, str(job.id))
    return job
```

### `run_job()`:后台轮询主循环

```python
def run_job(job_id: str) -> None:
    """BackgroundTask 入口。自开独立 Session(对称 run_parse_job_standalone)。"""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        job = db.get(WebIngestionJob, uuid.UUID(job_id))
        if job is None or job.status in ("completed", "failed"):
            return  # 幂等:已完成/失败直接退出

        config = resolve_firecrawl_config(db)
        if config is None:
            _mark_failed(db, job, "Firecrawl 配置丢失")
            return

        client = FirecrawlClient(config.api_key, config.base_url)
        _poll_and_ingest(db, job=job, client=client, config=config)
    except Exception as e:
        _mark_failed(db, job, str(e)[:500])  # 截断 500 字(对齐 run_parse_job)
    finally:
        db.close()


def _poll_and_ingest(db, *, job, client, config) -> None:
    from datetime import timedelta
    deadline = utcnow() + timedelta(hours=CRAWL_TIMEOUT_HOURS)  # 默认 2h
    while utcnow() < deadline:
        status = client.check_crawl(job.firecrawl_job_id)

        if status.status == "completed":
            _ingest_crawl_pages(db, job=job, pages=status.pages, config=config)
            job.status = "completed"
            job.completed_at = utcnow()
            job.pages_fetched = len(status.pages)
            db.commit()
            return

        if status.status == "failed":
            _mark_failed(db, job,
                         f"Firecrawl 任务失败(已完成 {status.completed}/{status.total})")
            return

        # 进行中:更新进度,睡一会
        job.pages_fetched = status.completed
        db.commit()
        time.sleep(CRAWL_POLL_INTERVAL_SECONDS)  # 默认 30s

    _mark_failed(db, job, f"轮询超时({CRAWL_TIMEOUT_HOURS}h)")


def _ingest_crawl_pages(db, *, job, pages, config) -> None:
    """整站结果分页入库。每页一个 KnowledgeFile(第 2 节决策)。"""
    file_ids = []
    filtered_count = 0
    for page in pages:
        filtered = filter_content(page.markdown, page.title)
        if filtered is None:
            filtered_count += 1
            continue

        kf = _upload_one_page(db, job=job, page=page, filtered=filtered)
        file_ids.append(str(kf.id))

    job.file_ids = file_ids
    job.pages_filtered = filtered_count
    log_firecrawl_call(db, user_id=job.user_id, mode="crawl",
                       pages=len(pages), source=config.source)
    _correct_quota(db, job)  # 预扣 → 实际校正
```

### `recover_pending_jobs()`:重启恢复(异步)

**关键修正**:不能照抄 `parse_service.recover_pending_jobs` 的同步模式——那个是同步跑(阻塞 startup),对单文件 docx 解析(几秒)没问题,但网页 crawl 轮询可能跑几小时,**同步跑会卡死 startup**。

```python
def recover_pending_jobs(stale_minutes: int = 10) -> int:
    """启动时扫描孤儿 web ingestion 任务。返回重新入队数。
    
    异步 spawn,不阻塞 startup(与 parse_service.recover_pending_jobs 的同步模式不同)。
    """
    from app.core.database import SessionLocal
    from app.core.background import spawn_background_task

    db = SessionLocal()
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)

        orphans = db.scalars(
            select(WebIngestionJob).where(
                or_(
                    (WebIngestionJob.status == "running")
                    & (WebIngestionJob.updated_at < cutoff),
                    (WebIngestionJob.status == "pending")
                    & (WebIngestionJob.created_at < cutoff),
                )
            )
        ).all()

        count = 0
        for job in orphans:
            spawn_background_task(run_job, str(job.id))  # 异步
            count += 1
        return count
    finally:
        db.close()
```

### 线程池基础设施

**文件**:`apps/api/app/core/background.py`(新建)

```python
"""统一异步后台任务 spawn 入口。

供 FastAPI BackgroundTasks 之外的场景使用(如 startup 恢复扫描)。
max_workers=4 防止孤儿任务洪水把进程跑爆。
"""
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg-task")


def spawn_background_task(func, *args, **kwargs):
    """提交异步任务。立即返回,不阻塞调用方。"""
    return _executor.submit(func, *args, **kwargs)
```

`main.py` startup hook 追加(对称现有 `recover_pending_jobs` 调用):
```python
@app.on_event("startup")
def on_startup():
    loguru.logger.info("TianGong API 启动")
    try:
        from app.services.parse_service import recover_pending_jobs as recover_parse
        n = recover_parse()
        if n:
            loguru.logger.info(f"恢复扫描:重新入队 {n} 个解析任务")
    except Exception as e:
        loguru.logger.exception(f"恢复扫描失败(不阻塞启动):{e}")

    # 新增:网页摄入任务恢复
    try:
        from app.services.web_ingestion_service import recover_pending_jobs as recover_web
        n = recover_web()
        if n:
            loguru.logger.info(f"恢复扫描:重新入队 {n} 个网页摄入任务")
    except Exception as e:
        loguru.logger.exception(f"网页摄入恢复扫描失败(不阻塞启动):{e}")
```

### `_mark_failed()` 与错误截断

对齐 `run_parse_job` 的 except 模式:
```python
def _mark_failed(db, job, message: str) -> None:
    job.status = "failed"
    job.error_message = message[:500]   # 截断 500 字
    job.completed_at = utcnow()
    db.commit()
```

### 常量定义(文件头)

```python
MAX_CRAWL_PAGES_HARD_CAP = 100          # crawl 页数硬上限
CRAWL_TIMEOUT_HOURS = 2                 # crawl 轮询超时
CRAWL_POLL_INTERVAL_SECONDS = 30        # 轮询间隔
DEFAULT_QUOTA_PER_USER_PER_DAY = 200    # 每用户每日配额(实现时与 admin 确认)
```

---

## 6. 质量过滤规则

**文件**:`apps/api/app/parsing/content_filter.py`(新建)

放在 `parsing/` 目录——与 `dispatcher.py` / `pdf_parser.py` 同属「内容预处理」职责。

### 设计目标

补的洞:URL 抓回的内容质量参差(导航/广告/boilerplate),直接入库会污染知识库。规则层过滤掉**明显的垃圾页**,不做主观相关性判断(那是 LLM 的活,本 spec 排除)。

### `filter_content()` 接口

```python
from dataclasses import dataclass


@dataclass
class FilteredContent:
    markdown: str   # 去噪后的干净正文
    title: str      # 规范化标题
    word_count: int # 字数(过滤判断 + 配额展示用)


def filter_content(raw_markdown: str, raw_title: str = "") -> FilteredContent | None:
    """规则质量过滤。返回 None 表示该页被拒绝入库。
    
    拒绝原因:
    - 太短(低于最小字数阈值)
    - 语言不符合(非中文/英文页面)
    - 全是 boilerplate(导航/页脚/广告占比过高)
    """
```

### 三层过滤规则(按顺序执行)

#### 规则 1:Markdown 去噪(boilerplate 移除)

基于**结构启发式**,不依赖黑名单域名(网站太多列不完):
- 移除连续 5+ 个 `[text](url)` 形式的链接行(典型导航菜单)
- 移除 markdown 表格外的连续 `---` 分隔线(页脚装饰)
- 移除已知 boilerplate 关键词区块:`Cookie`, `Subscribe`, `Newsletter`, `Sign up`, `Related posts`, `Share this`, `Skip to content`, `Back to top`, `Accept all`
- 移除 HTML 注释残留 `<!-- ... -->`
- 压缩连续空行(3+ → 2)

**不做 NLP 语义去噪**——那是 RAGFlow 级别的深度解析,本 spec 排除。Firecrawl 本身已做相当程度的正文提取,我们只补一层明显垃圾的清扫。

#### 规则 2:长度阈值

```python
MIN_CONTENT_CHARS = 200       # 低于 200 字直接拒(典型空白页/404/登录墙)
MIN_CONTENT_CHARS_ZH = 100    # 中文字符阈值(中文信息密度高,放宽)


def _count_chars(markdown: str) -> tuple[int, int]:
    """返回 (总字符数, 中文字符数)。"""
    cjk = sum(1 for c in markdown if '\u4e00' <= c <= '\u9fff')
    return len(markdown), cjk
```

**双语阈值**:中文信息密度高,1 个中文字 ≈ 2-3 个英文字符信息量,所以中文 100 字 ≥ 英文 200 字。

#### 规则 3:语言检测

**不引入额外依赖**(不用 langdetect,增加依赖且慢),基于字符占比:

```python
def _is_supported_language(markdown: str, cjk_count: int) -> bool:
    """判定页面是否中文/英文为主。
    
    判定逻辑(宽松,避免误杀):
    - CJK 占比 ≥ 5% → 中文(接受)
    - 拉丁字母为主且 CJK < 5% → 英文(接受,专利文献常见英文)
    - 其他脚本(西里尔/阿拉伯/日文假名等)占比 > 30% → 拒绝
    """
```

**为什么宽松接受英文**:专利领域大量技术文档/标准是英文(PCT 申请、IEEE 论文、3GPP 标准等),拒英文会误杀高价值内容。只拒明显非中英的页面。

### 配置化(后续可调)

阈值集中在文件头常量。**MVP 不做 SystemSetting 覆盖**——常量写死,后续若需调,改常量+发版即可。YAGNI。

```python
MIN_CONTENT_CHARS = 200
MIN_CONTENT_CHARS_ZH = 100
BOILERPLATE_KEYWORDS = [
    "Cookie", "Subscribe", "Newsletter", "Sign up", "Related posts",
    "Share this", "Skip to content", "Back to top", "Accept all",
]
MAX_NAV_LINK_RUN = 5
```

### `WebIngestionJob` 字段配合

- `pages_fetched` = Firecrawl 返回的总页数
- `pages_filtered` = `filter_content` 返回 None 的页数

admin 看 `(pages_fetched - pages_filtered) / pages_fetched` 比例,判断过滤是否过激。若某站点过滤率 > 80%,说明阈值需调或该站质量太差。

### 边界情况

| 场景 | 处理 |
|---|---|
| Firecrawl 返回空 markdown(404/网络错) | 规则 2 长度阈值就拒,返回 None |
| 页面是登录墙/付费墙 | 通常返回极短内容,规则 2 拒 |
| 整站全是垃圾页 | `pages_fetched=50, pages_filtered=50` → job 仍 `completed`,但 `file_ids=[]`。用户看到「抓了 50 页全部被过滤」 |
| 中文页带英文导航(混合) | 规则 1 去导航,规则 2/3 判正文部分,通常能通过 |
| 单页 scrape 被过滤 | API 报 `ValidationError`,配额退款 |

### 不做的事(YAGNI 排除)

- ❌ LLM 相关性判断(第 1 节已排除,成本敏感)
- ❌ 图片/表格内容提取(Firecrawl 返回纯 Markdown,本层不处理视觉)
- ❌ 域名黑名单(用结构启发式更通用,黑名单维护成本高)
- ❌ 去重检测(复用 `upload_to_global` 的 SHA256 去重,本层不重复造)

---

## 7. API 端点与配额控制

### 用户/admin 通用端点

**文件**:`apps/api/app/api/knowledge.py` 扩展

#### `POST /knowledge/ingest/web` — 发起网页摄入

```python
class WebIngestRequest(BaseModel):
    url: str
    mode: str = "scrape"       # scrape / crawl
    scope: str = "personal"    # personal / global(global 需 admin)
    max_pages: int = 1         # 仅 crawl 有效


@router.post("/knowledge/ingest/web")
def ingest_web(
    payload: WebIngestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发起网页摄入。scrape 同步返回 file;crawl 异步返回 job_id。"""
    result = web_ingestion_service.create_job(
        db, user=current_user, url=payload.url,
        mode=payload.mode, scope=payload.scope, max_pages=payload.max_pages,
    )
    # result 是 KnowledgeFile(scrape)或 WebIngestionJob(crawl)
    if isinstance(result, KnowledgeFile):
        return {"kind": "file", "file": _file_out(result)}
    return {"kind": "job", "job": _job_out(result)}
```

**响应结构区分 kind**:
- `{"kind": "file", "file": {...}}` — scrape 成功
- `{"kind": "job", "job": {"id": ..., "status": "running", ...}}` — crawl 已启动

#### `GET /knowledge/ingest/jobs/{job_id}` — 查任务状态

```python
@router.get("/knowledge/ingest/jobs/{job_id}")
def get_ingest_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查 crawl 任务状态。越权(非 owner)返回 404,不暴露存在性。"""
    job = web_ingestion_service.get_job(db, job_id=job_id, user=current_user)
    return _job_out(job)
```

#### `GET /knowledge/ingest/jobs` — 列任务

```python
@router.get("/knowledge/ingest/jobs")
def list_ingest_jobs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出本人的网页摄入任务。"""
    jobs = web_ingestion_service.list_jobs(db, user=current_user)
    return [_job_out(j) for j in jobs]
```

### `_job_out()` 输出格式

```python
def _job_out(job: WebIngestionJob) -> dict:
    return {
        "id": str(job.id),
        "url": job.url,
        "mode": job.mode,
        "scope": job.scope,
        "status": job.status,
        "pages_fetched": job.pages_fetched,
        "pages_filtered": job.pages_filtered,
        "file_ids": job.file_ids,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
```

### admin 配置端点

**文件**:`apps/api/app/api/admin.py`(或对应 admin 路由文件)扩展

```python
@router.get("/admin/console/firecrawl")
def get_firecrawl_config(
    admin: User = Depends(get_admin_user),  # 复用现有 admin 守卫
    db: Session = Depends(get_db),
):
    """读全局 Firecrawl 配置(api_key 脱敏)。"""
    return firecrawl_client.get_firecrawl_settings(db)


@router.put("/admin/console/firecrawl")
def set_firecrawl_config(
    payload: FirecrawlConfigRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """写全局 Firecrawl 配置。"""
    firecrawl_client.set_firecrawl_settings(
        db, enabled=payload.enabled, api_key=payload.api_key,
        base_url=payload.base_url, updated_by=admin.id,
    )
    return {"ok": True}


class FirecrawlConfigRequest(BaseModel):
    enabled: bool
    api_key: str = ""              # 空串表示不修改
    base_url: str = "https://api.firecrawl.dev"
```

### 配额控制

#### 配额模型

- **每用户每日配额**:`DEFAULT_QUOTA_PER_USER_PER_DAY = 200` 页(实现时与 admin 确认)
- **统计维度**:按 `LLMCallLog.action='firecrawl'` + `user_id` + 当日 SUM(`token_completion`)记的页数
- **crawl 预扣 max_pages,完成时按实际页数校正**

#### `_reserve_quota()` / `_correct_quota()` / `_refund_quota()`

```python
def _reserve_quota(db, user, mode, max_pages) -> None:
    """预扣配额。超额报错。"""
    pages = 1 if mode == "scrape" else max_pages
    used_today = _used_pages_today(db, user.id)
    if used_today + pages > DEFAULT_QUOTA_PER_USER_PER_DAY:
        raise ValidationError(
            f"今日配额已用尽({used_today}/{DEFAULT_QUOTA_PER_USER_PER_DAY}),"
            f"本次需 {pages} 页"
        )
    # 预扣记一条 pending 日志(实际计数见 _correct_quota)
    log_firecrawl_call(db, user_id=user.id, mode=mode, pages=pages,
                       source="global", status="reserved")


def _correct_quota(db, job) -> None:
    """crawl 完成时按实际页数校正。预扣的多退少补。"""
    actual = job.pages_fetched - job.pages_filtered  # 实际入库的
    reserved = job.max_pages
    delta = actual - reserved
    if delta != 0:
        log_firecrawl_call(db, user_id=job.user_id, mode="crawl",
                           pages=delta, source="global", status="correction")


def _refund_quota(db, user, pages) -> None:
    """scrape 被过滤/失败时退款。"""
    log_firecrawl_call(db, user_id=user.id, mode="scrape",
                       pages=-pages, source="global", status="refund")


def _used_pages_today(db, user_id) -> int:
    """查询当日已用页数(SUM token_completion,action=firecrawl)。"""
    from datetime import datetime, timezone
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    result = db.scalar(
        select(func.coalesce(func.sum(LLMCallLog.token_completion), 0)).where(
            (LLMCallLog.action == "firecrawl")
            & (LLMCallLog.user_id == user_id)
            & (LLMCallLog.created_at >= today_start)
        )
    )
    return int(result or 0)
```

#### `log_firecrawl_call()` helper

**文件**:`apps/api/app/services/llm_log_helper.py` 扩展

```python
def log_firecrawl_call(
    db: Session, *,
    user_id, mode: str, pages: int,
    source: str = "global",
    status: str = "success",
) -> None:
    """写一条 Firecrawl 调用元数据日志。失败不抛(日志不应影响主流程)。
    
    pages 存在 token_completion 字段(语义复用:无 token 概念,
    借该字段记页数;配额查询按 action='firecrawl' 聚合)。
    pages 可为负(退款/校正)。
    """
    try:
        db.add(LLMCallLog(
            user_id=user_id,
            action="firecrawl",
            model=f"firecrawl-{mode}",   # scrape/crawl
            provider=source,             # global/env
            token_completion=pages,
            status=status,
        ))
        db.commit()
    except Exception:
        db.rollback()
```

### URL 校验

**文件**:`web_ingestion_service.py` 内部函数

```python
from urllib.parse import urlparse
import ipaddress

ALLOWED_SCHEMES = {"http", "https"}


def _validate_url(url: str) -> None:
    """校验 URL:协议白名单 + 长度 + 拒内网 IP(SSRF 防护)。"""
    if len(url) > 2048:
        raise ValidationError("URL 过长")
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValidationError(f"不支持的协议:{parsed.scheme}(仅 http/https)")
    if not parsed.hostname:
        raise ValidationError("URL 缺少主机名")
    
    # SSRF 防护:拒内网 IP / loopback
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            raise ValidationError("不允许访问内网地址")
    except ValueError:
        pass  # 非 IP(域名),允许
    
    # 拒常见元数据端点(SSRF 常见目标)
    blocked_hosts = {"metadata.google.internal", "169.254.169.254"}
    if parsed.hostname.lower() in blocked_hosts:
        raise ValidationError("不允许访问该地址")
```

**SSRF 防护是关键安全项**——用户贴 `http://169.254.169.254/...` 抓云元数据是经典攻击。本校验在 service 层强制执行。

---

## 8. 错误处理与边界

### 错误分类与处理策略

| 错误类型 | 处理 | 用户感知 |
|---|---|---|
| Firecrawl 未配置 | `create_job` 报 `ValidationError` | 「Firecrawl 未配置,请联系管理员」 |
| URL 校验失败 | `create_job` 报 `ValidationError` | 具体原因(协议错/内网/超长) |
| 非管理员入 global | `create_job` 报 `AuthorizationError` | 「仅 admin 可入 global 库」 |
| 配额不足 | `create_job` 报 `ValidationError` | 「今日配额已用尽(N/M)」 |
| scrape 抓取失败 | `_scrape_sync` 报 `ValidationError`,退款 | 「页面抓取失败」+ 退款 |
| scrape 内容被过滤 | `_scrape_sync` 报 `ValidationError`,退款 | 「内容未通过质量过滤」+ 退款 |
| crawl 远端任务失败 | `run_job` → `_mark_failed` | job.status=failed,error_message |
| crawl 轮询超时(2h) | `_mark_failed("轮询超时")` | job.status=failed |
| crawl BackgroundTask 异常 | `run_job` except → `_mark_failed`,截断 500 字 | job.status=failed |
| Firecrawl API 限流(429) | 客户端重试 3 次(指数退避),仍失败抛 | job.status=failed |
| Firecrawl API 鉴权失败(401) | 不重试,直接抛 | job.status=failed,「Firecrawl key 失效」 |

### 客户端重试策略

`FirecrawlClient` 内部对 429 / 5xx 重试:

```python
MAX_RETRIES = 3
RETRY_DELAYS = [1, 4, 16]  # 指数退避(秒)


def _with_retry(func):
    """装饰器:对 429/5xx 重试,401/4xx 不重试。"""
    for attempt, delay in enumerate(RETRY_DELAYS, 1):
        try:
            return func()
        except FirecrawlRateLimitError:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(delay)
        except FirecrawlAuthError:
            raise  # 鉴权错不重试
```

### 幂等保证

- **`run_job` 开头检查 status**:若 `completed`/`failed` 直接 return,防止重启恢复重复跑
- **`upload_to_global` SHA256 去重**:整站 crawl 中若两页内容完全相同,只入一次(现有逻辑)
- **`submit_for_review` 幂等**:已有 pending 工单返回旧的(现有逻辑)
- **同 URL 二次抓取**:**不去重**——用户可能想刷新内容。若需去重,后续在 `create_job` 加 `KnowledgeFile.url` 查重(扩展点,不在 MVP)

### 资源边界

| 边界 | 值 | 处理 |
|---|---|---|
| 单 URL 长度 | 2048 字符 | 超长拒 |
| crawl max_pages 硬上限 | 100 | 超过拒(防失控) |
| crawl 轮询超时 | 2 小时 | 超时标 failed |
| 轮询间隔 | 30 秒 | 平衡响应性与 API 调用 |
| 线程池 | max_workers=4 | 防孤儿任务洪水 |
| 错误信息截断 | 500 字符 | 对齐 `run_parse_job` |
| 单页 Markdown 长度 | 无硬限 | 由 chunker 切片处理 |

### SSRF 防护(关键安全)

见第 7 节 `_validate_url`。必须拒:
- 内网 IP(10.x / 172.16-31.x / 192.168.x)
- Loopback(127.x / ::1)
- 链路本地(169.254.x,含云元数据 169.254.169.254)
- 受保留 IP 段
- 已知元数据端点(`metadata.google.internal` 等)

### 不阻塞 startup

`recover_pending_jobs` 用线程池异步 spawn,不阻塞 startup。即使所有 crawl 任务都是孤儿,也只在线程池里跑,startup 立即返回。

### 日志健壮性(对齐现有红线)

`log_firecrawl_call` 内部 try/except + rollback,**日志失败绝不影响主流程**(对齐 `llm_log_helper.py` 现有红线)。

---

## 9. 测试策略

### 测试分层

| 层级 | 文件 | 重点 |
|---|---|---|
| 单元:`content_filter` | `tests/test_content_filter.py` | 三层规则各自的边界 |
| 单元:`_validate_url` | `tests/test_web_ingestion_service.py` | SSRF 防护 |
| 单元:`firecrawl_client` | `tests/test_firecrawl_client.py` | dataclass 映射 + 重试 |
| 单元:`resolve_firecrawl_config` | 同上 | 三级 fallback |
| 集成:`create_job` scrape 流 | `tests/test_web_ingestion_api.py` | mock client,验证 KF 入库 |
| 集成:`create_job` crawl 流 | 同上 | mock client,验证 job 创建 |
| 集成:`run_job` 轮询 | 同上 | mock check_crawl 多态返回 |
| 集成:`recover_pending_jobs` | 同上 | 异步 spawn + 幂等 |

### 关键测试用例

#### `content_filter` 单元测试

```python
def test_filter_rejects_short_content():
    """低于阈值的页面被拒。"""
    assert filter_content("太短", title="x") is None
    assert filter_content("a" * 199, title="x") is None

def test_filter_accepts_chinese_above_threshold():
    """中文 100 字以上接受。"""
    md = "专利" * 50  # 100 字
    result = filter_content(md, title="测试")
    assert result is not None
    assert result.word_count >= 100

def test_filter_strips_navigation_links():
    """连续 5+ 链接行被移除。"""
    nav = "\n".join(f"[item{i}](/page{i})" for i in range(10))
    body = "正文" * 100
    result = filter_content(nav + "\n\n" + body, title="x")
    assert result is not None
    assert "item0" not in result.markdown  # 导航被移除
    assert "正文" in result.markdown

def test_filter_rejects_non_chinese_english():
    """纯俄文/阿拉伯文页面被拒。"""
    russian = "Привет мир " * 50
    assert filter_content(russian, title="x") is None

def test_filter_accepts_english_tech_doc():
    """英文技术文档(无 CJK)接受。"""
    en = "This patent describes a method " * 20  # > 200 字符
    result = filter_content(en, title="Patent")
    assert result is not None
```

#### `_validate_url` SSRF 测试

```python
@pytest.mark.parametrize("url,should_pass", [
    ("https://example.com", True),
    ("http://example.com/path", True),
    ("ftp://example.com", False),                # 协议错
    ("http://127.0.0.1/admin", False),           # loopback
    ("http://10.0.0.1/internal", False),         # 内网
    ("http://192.168.1.1", False),               # 内网
    ("http://169.254.169.254/latest/meta-data", False),  # 云元数据
    ("http://metadata.google.internal", False),  # GCE 元数据
    ("http://[::1]", False),                     # IPv6 loopback
])
def test_validate_url_ssrf_protection(url, should_pass):
    if should_pass:
        _validate_url(url)  # 不抛
    else:
        with pytest.raises(ValidationError):
            _validate_url(url)
```

#### `resolve_firecrawl_config` 三级 fallback

```python
def test_resolve_prefers_global_over_env(db):
    """全局配置优先于 env。"""
    # 设全局 SystemSetting
    set_firecrawl_settings(db, enabled=True, api_key="fc-global", ...)
    # 设 env
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-env")
    config = resolve_firecrawl_config(db)
    assert config.api_key == "fc-global"
    assert config.source == "global"

def test_resolve_falls_back_to_env_when_global_disabled(db):
    """全局禁用时回落 env。"""
    set_firecrawl_settings(db, enabled=False, ...)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-env")
    config = resolve_firecrawl_config(db)
    assert config.api_key == "fc-env"
    assert config.source == "env"

def test_resolve_returns_none_when_unconfigured(db):
    """都没配置返回 None。"""
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    assert resolve_firecrawl_config(db) is None
```

#### `create_job` scrape 集成测试

```python
def test_scrape_sync_ingests_to_personal(db, mock_firecrawl_client, user):
    """scrape 同步流:mock 返回有效 markdown,验证 KF 入 personal 库。"""
    mock_firecrawl_client.scrape.return_value = ScrapeResult(
        url="https://example.com/patent",
        title="测试专利",
        markdown="专利正文" * 100,
        status_code=200, fetch_failed=False,
    )
    kf = web_ingestion_service.create_job(
        db, user=user, url="https://example.com/patent",
        mode="scrape", scope="personal",
    )
    assert isinstance(kf, KnowledgeFile)
    assert kf.scope == "personal"
    assert kf.source_type == "external_web"
    assert kf.url == "https://example.com/patent"
    # 验证 chunk 已写入
    chunks = db.query(KnowledgeChunk).filter_by(file_id=kf.id).all()
    assert len(chunks) > 0

def test_scrape_filtered_refunds_quota(db, mock_firecrawl_client, user):
    """scrape 内容被过滤时配额退款。"""
    mock_firecrawl_client.scrape.return_value = ScrapeResult(
        url="...", title="x", markdown="太短",  # 触发长度过滤
        status_code=200, fetch_failed=False,
    )
    with pytest.raises(ValidationError):
        create_job(db, user=user, url="...", mode="scrape", scope="personal")
    # 验证当日使用量仍为 0(预扣 1 + 退款 -1 = 0)
    assert _used_pages_today(db, user.id) == 0

def test_scrape_to_global_requires_admin(db, user_regular):
    """非 admin 入 global 报 AuthorizationError。"""
    with pytest.raises(AuthorizationError):
        create_job(db, user=user_regular, url="https://example.com",
                   mode="scrape", scope="global")
```

#### `run_job` crawl 轮询测试

```python
def test_run_job_polls_until_completed(db, mock_firecrawl_client, user):
    """crawl 任务:前两次返回进行中,第三次返回 completed。"""
    job = _create_test_job(db, user=user, mode="crawl")
    mock_firecrawl_client.check_crawl.side_effect = [
        CrawlStatus(status="scrape", completed=5, total=50, pages=[], credits_used=0),
        CrawlStatus(status="scrape", completed=20, total=50, pages=[], credits_used=0),
        CrawlStatus(status="completed", completed=50, total=50,
                    pages=[_make_page("p1"), _make_page("p2")], credits_used=50),
    ]
    web_ingestion_service.run_job(str(job.id))
    
    db.refresh(job)
    assert job.status == "completed"
    assert job.pages_fetched == 2
    assert len(job.file_ids) == 2

def test_run_job_marks_failed_on_firecrawl_failure(db, mock_firecrawl_client, user):
    """Firecrawl 远端失败时 job 标 failed。"""
    job = _create_test_job(db, user=user, mode="crawl")
    mock_firecrawl_client.check_crawl.return_value = CrawlStatus(
        status="failed", completed=10, total=50, pages=[], credits_used=10,
    )
    web_ingestion_service.run_job(str(job.id))
    
    db.refresh(job)
    assert job.status == "failed"
    assert "Firecrawl 任务失败" in job.error_message

def test_run_job_idempotent_on_completed(db, mock_firecrawl_client, user):
    """已 completed 的 job 重跑无副作用。"""
    job = _create_test_job(db, user=user, mode="crawl", status="completed")
    web_ingestion_service.run_job(str(job.id))
    # check_crawl 不应被调用
    mock_firecrawl_client.check_crawl.assert_not_called()
```

#### `recover_pending_jobs` 测试

```python
def test_recover_spawns_background_tasks(db, monkeypatch, user):
    """孤儿任务被 spawn 到线程池。"""
    spawned = []
    monkeypatch.setattr(
        "app.core.background.spawn_background_task",
        lambda func, *args: spawned.append((func.__name__, args)),
    )
    # 建一个 1 小时前的 running 孤儿
    old_job = _create_test_job(db, user=user, mode="crawl", status="running",
                               updated_at=utcnow() - timedelta(hours=1))
    count = web_ingestion_service.recover_pending_jobs()
    assert count == 1
    assert spawned == [("run_job", (str(old_job.id),))]
```

### 测试基础设施

- **SQLite 内存库**(对齐天工现有测试约定 GOTCHAS G2):`WebIngestionJob` 表用 JSONB-with-variant,SQLite 下变 JSON
- **mock FirecrawlClient**:用 `unittest.mock.MagicMock`,不真打 Firecrawl API
- **`spawn_background_task` mock**:测试里同步执行(不真起线程),验证 spawn 调用即可
- **`time.sleep` mock**:轮询测试里把 sleep 替换成 no-op,避免测试跑 30 秒

### 不测的(YAGNI)

- ❌ 真打 Firecrawl API(集成测试留 manual,成本敏感)
- ❌ 前端 UI(本 spec 只覆盖后端,前端是后续 spec)
- ❌ admin 配置 UI(同上)
- ❌ 配额计费的精确结算(逻辑简单,单测覆盖 SUM 即可)

---

## 10. 实施清单(给 writing-plans 的输入)

### 新增文件(7 个)

| 文件 | 职责 | 估算行数 |
|---|---|---|
| `apps/api/app/models/web_ingestion_job.py` | WebIngestionJob ORM | ~40 |
| `apps/api/alembic/versions/<hash>_add_web_ingestion_jobs.py` | 建表 + 加 url 列迁移 | ~80 |
| `apps/api/app/services/firecrawl_client.py` | FirecrawlClient + resolve + admin get/set | ~150 |
| `apps/api/app/services/web_ingestion_service.py` | create_job / run_job / recover / 入库 | ~250 |
| `apps/api/app/parsing/content_filter.py` | filter_content 三层规则 | ~120 |
| `apps/api/app/core/background.py` | ThreadPoolExecutor spawn | ~20 |
| `tests/test_web_ingestion.py` | 全部测试(合并多文件) | ~300 |

### 改动文件(9 个)

| 文件 | 改动 |
|---|---|
| `apps/api/pyproject.toml` | 加 `firecrawl-py` 依赖 |
| `apps/api/app/core/config.py` | 加 3 个 firecrawl env 字段 |
| `apps/api/app/models/__init__.py` | 导出 `WebIngestionJob` |
| `apps/api/app/models/knowledge_file.py` | 加 `url` 字段 |
| `apps/api/app/services/knowledge_service.py` | `upload_to_global` / `upload_external` 加 `url: str \| None = None` 参数 |
| `apps/api/app/services/llm_log_helper.py` | 加 `log_firecrawl_call` |
| `apps/api/app/api/knowledge.py` | 加 3 个端点 + `_job_out` |
| `apps/api/app/api/admin.py`(或对应) | 加 2 个 firecrawl 配置端点 |
| `apps/api/app/main.py` | startup hook 加 web 恢复扫描 |

### 验收标准

1. ✅ 用户可 POST URL → scrape 同步返回 file,crawl 异步返回 job_id
2. ✅ crawl 完成后 `GET /jobs/{id}` 看到 completed + file_ids
3. ✅ admin 配 Firecrawl key 后用户立即能用(全局配置生效)
4. ✅ SSRF 防护生效(127.0.0.1 / 169.254.169.254 被拒)
5. ✅ 配额预扣 + 校正 + 退款逻辑正确(被过滤页面退款)
6. ✅ 重启后 running 孤儿任务被异步恢复
7. ✅ 全部单测 + 集成测试通过
8. ✅ 现有审核流/检索/embedding 零回归

### 后续扩展点(不在本 spec)

- 前端 UI:个人库/全局库加「贴 URL 入库」入口 + crawl 进度展示(独立 spec)
- admin 配额看板:聚合 `LLMCallLog.action='firecrawl'` 统计(独立 spec)
- BYOK 模式:用户自配 Firecrawl key(若用户反馈全局 key 成本压力大)
- 同 URL 去重:`create_job` 加 `KnowledgeFile.url` 查重
- 阈值 SystemSetting 化:admin 可调过滤规则(若默认值不合适)

---

## 附录 A:与现有模块的对照表

| 模式 | 现有 | 本 spec | 对齐点 |
|---|---|---|---|
| 全局配置 | `llm_global_chat_config` | `firecrawl_config` + `firecrawl_enabled` | SystemSetting upsert |
| 凭据加密 | `encrypt_value/decrypt_value` | 同 | 直接复用 |
| env 兜底 | `_build_env_chat_config` | `resolve_firecrawl_config` 的 env 分支 | 同 |
| 调用日志 | `log_chat_call / log_embed_call` | `log_firecrawl_call` | 同模式,新 action |
| 异步任务 | `run_parse_job_standalone` | `run_job` | 自开 Session |
| 重启恢复 | `recover_pending_jobs`(同步) | `recover_pending_jobs`(异步) | 同思路,异步化 |
| 错误截断 | `run_parse_job` 500 字 | `_mark_failed` 500 字 | 同 |
| 文件入库 | `upload_to_global/upload_external` | 直接调用 | **零改动复用** |
| 三域隔离 | `scope` 列 | 继承 | **零改动复用** |
| 审核工单 | `submit_for_review` | 继承(网页来源文件可上报) | **零改动复用** |

## 附录 B:与 OpenDCAI 系列项目对照(回应原评估)

| 项目 | 本 spec 的处理 |
|---|---|
| **Firecrawl** | ✅ 直接融入(云 API + 官方 SDK,补零能力缺口) |
| RAGFlow | 借鉴深度解析思路(本 spec 未实现 OCR/版面分析,留作后续) |
| One-Eval | 思路借鉴(审查稳定性测试留作后续 spec) |
| DataFlow / DataMind / DataFlow-Skills / OpenWorldLib | 不融入(领域不匹配 / 与 pgvector 冲突 / 不可 import / 世界模型无关) |
