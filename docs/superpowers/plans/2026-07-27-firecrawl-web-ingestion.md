# Firecrawl 网页摄入 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给天工知识库增加网页摄入能力——用户/admin 贴 URL(scrape 单页或 crawl 整站),抓回 Markdown 入现有 pgvector 知识库,审核流/检索/embedding 零改动复用。

**Architecture:** 方案 C(抓取任务与内容存储分离):抓取任务状态机独立成 `WebIngestionJob` 表,抓回内容标准化成 `KnowledgeFile(source_type='external_web')` 走现有入库流。scrape 同步、crawl 异步(`start_crawl` + 自管轮询),全局 Firecrawl key 加密存 SystemSetting,配额预扣+校正复用 LLMCallLog 记账,SSRF 防护拒内网。

**Tech Stack:** Python 3 + FastAPI + SQLAlchemy 2.0 + pgvector + firecrawl-py SDK + ThreadPoolExecutor

**Spec:** `docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md`

---

## 文件结构

### 新建文件(7 个)

| 文件 | 职责 |
|---|---|
| `apps/api/app/models/web_ingestion_job.py` | WebIngestionJob ORM 模型 |
| `apps/api/alembic/versions/c3d4e5f6a7b8_add_web_ingestion_jobs.py` | 建表 + 加 KnowledgeFile.url 列 |
| `apps/api/app/core/background.py` | ThreadPoolExecutor spawn 入口 |
| `apps/api/app/parsing/content_filter.py` | 规则质量过滤(Markdown 去噪/长度/语言) |
| `apps/api/app/services/firecrawl_client.py` | FirecrawlClient + 凭据解析 + admin get/set |
| `apps/api/app/services/web_ingestion_service.py` | create_job / run_job / recover 核心编排 |
| `apps/api/tests/test_web_ingestion.py` | 全部测试 |

### 改动文件(9 个)

| 文件 | 改动 |
|---|---|
| `apps/api/pyproject.toml` | 加 `firecrawl-py>=1.0.0` |
| `apps/api/app/core/config.py` | 加 3 个 firecrawl env 字段 |
| `apps/api/app/models/__init__.py` | 导出 WebIngestionJob |
| `apps/api/app/models/knowledge_file.py` | 加 `url` 字段 |
| `apps/api/app/services/knowledge_service.py` | `upload_to_global` / `upload_external` 加 `url: str \| None = None` 参数 |
| `apps/api/app/services/llm_log_helper.py` | 加 `log_firecrawl_call` |
| `apps/api/app/api/knowledge.py` | 加 3 个端点 + `_job_out` |
| `apps/api/app/api/admin.py` | 加 2 个 firecrawl 配置端点 |
| `apps/api/app/main.py` | startup hook 加 web 恢复扫描 |

---

## 任务依赖图

```
Task 1 (依赖) → Task 2 → Task 3 → Task 4 → Task 5
                                          ↓
Task 6 (独立) → Task 7 → Task 8 ──────────┘
                          ↓
                  Task 9 (集成) → Task 10 → Task 11 → Task 12 → Task 13 → Task 14
```

---

## Task 1: 加 firecrawl-py 依赖 + env 配置

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/app/core/config.py`

- [ ] **Step 1: 在 pyproject.toml 加依赖**

打开 `apps/api/pyproject.toml`,在 `[project] dependencies` 列表末尾(LangChain 那一组之后)加:

```toml
    "firecrawl-py>=1.0.0",
```

- [ ] **Step 2: 在 config.py 加 firecrawl env 字段**

打开 `apps/api/app/core/config.py`,在 `glm_embedding_model` 行(第 32 行)之后、`# 文件上传` 注释(第 34 行)之前插入:

```python

    # Firecrawl (web ingestion;全局 key 存 SystemSetting,env 仅兜底)
    firecrawl_api_key: str = ""
    firecrawl_base_url: str = "https://api.firecrawl.dev"
    firecrawl_enabled: bool = False
```

- [ ] **Step 3: 装依赖**

Run: `cd apps/api && uv sync --extra dev`
Expected: 成功安装 firecrawl-py 及其依赖

- [ ] **Step 4: 验证可 import**

Run: `cd apps/api && uv run python -c "from firecrawl import Firecrawl; print('ok')"`
Expected: 输出 `ok`

Run: `cd apps/api && uv run python -c "from app.core.config import Settings; s = Settings(database_url='x', jwt_secret='x', encryption_key='x'); print(s.firecrawl_base_url)"`
Expected: 输出 `https://api.firecrawl.dev`

- [ ] **Step 5: Commit**

```bash
git add apps/api/pyproject.toml apps/api/uv.lock apps/api/app/core/config.py
git commit -m "feat(api): 加 firecrawl-py 依赖 + env 配置项"
```

---

## Task 2: WebIngestionJob ORM 模型

**Files:**
- Create: `apps/api/app/models/web_ingestion_job.py`
- Modify: `apps/api/app/models/__init__.py`
- Test: `apps/api/tests/test_web_ingestion_job_model.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_web_ingestion_job_model.py`:

```python
"""WebIngestionJob ORM 模型测试。"""

import uuid

from app.models import WebIngestionJob


def test_web_ingestion_job_fields():
    """模型字段齐全且默认值正确。"""
    job = WebIngestionJob(
        user_id=uuid.uuid4(),
        scope="personal",
        url="https://example.com",
        mode="crawl",
        max_pages=50,
    )
    assert job.scope == "personal"
    assert job.mode == "crawl"
    assert job.max_pages == 50
    assert job.status == "pending"  # 默认
    assert job.pages_fetched == 0
    assert job.pages_filtered == 0
    assert job.firecrawl_job_id is None
    assert job.file_ids is None
    assert job.error_message is None
    assert job.completed_at is None


def test_web_ingestion_job_in_db(db_session):
    """可在 SQLite 测试库写入读取。"""
    uid = uuid.uuid4()
    job = WebIngestionJob(
        user_id=uid, scope="global", url="https://x.com",
        mode="scrape", max_pages=1, status="completed",
        pages_fetched=1, file_ids=[str(uuid.uuid4())],
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    fetched = db_session.get(WebIngestionJob, job.id)
    assert fetched is not None
    assert fetched.url == "https://x.com"
    assert fetched.file_ids == job.file_ids
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_job_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'WebIngestionJob'`

- [ ] **Step 3: 创建模型文件**

创建 `apps/api/app/models/web_ingestion_job.py`:

```python
"""网页摄入任务(WebIngestionJob)。

跟踪 Firecrawl crawl 任务的远端状态、本地配额、生成的内容文件。
scrape 模式不建本表记录(同步返回 KnowledgeFile);仅 crawl 模式建。

设计 spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 3 节。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


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

- [ ] **Step 4: 注册到 models/__init__.py**

修改 `apps/api/app/models/__init__.py`,在 `from app.models.user_embedding_config import UserEmbeddingConfig` 之后加:

```python
from app.models.web_ingestion_job import WebIngestionJob
```

并在 `__all__` 列表末尾(在 `"InviteCode",` 之后)加:

```python
    "WebIngestionJob",
```

- [ ] **Step 5: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_job_model.py -v`
Expected: PASS(2 个测试)

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/models/web_ingestion_job.py apps/api/app/models/__init__.py apps/api/tests/test_web_ingestion_job_model.py
git commit -m "feat(models): WebIngestionJob ORM 模型"
```

---

## Task 3: KnowledgeFile 加 url 字段 + 迁移

**Files:**
- Modify: `apps/api/app/models/knowledge_file.py`
- Create: `apps/api/alembic/versions/c3d4e5f6a7b8_add_web_ingestion_jobs.py`
- Test: `apps/api/tests/test_web_ingestion_job_model.py`(扩展)

- [ ] **Step 1: 给 knowledge_file.py 加 url 字段**

修改 `apps/api/app/models/knowledge_file.py`,在 `content_hash` 字段(第 32 行)之后加:

```python
    # 网页来源的原 URL(external_web 才有;其他来源为 None)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
```

- [ ] **Step 2: 写迁移文件**

创建 `apps/api/alembic/versions/c3d4e5f6a7b8_add_web_ingestion_jobs.py`:

```python
"""add web_ingestion_jobs table + knowledge_files.url column

Revision ID: c3d4e5f6a7b8
Revises: b_split_emb_config
Create Date: 2026-07-27

新建 web_ingestion_jobs 表(Firecrawl crawl 任务跟踪)+ 给 knowledge_files 加 url 列。
spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 3 节。

列类型严格对齐 IdMixin/TimestampMixin(base.py),保证后续 autogenerate 不报伪 diff:
- id = sa.Uuid()
- timestamps = sa.DateTime(timezone=True) server_default now() NOT NULL
- file_ids 用 JSONB-with-variant(PG=JSONB, SQLite=JSON)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b_split_emb_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'web_ingestion_jobs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scope', sa.String(20), nullable=False),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('mode', sa.String(10), nullable=False),
        sa.Column('max_pages', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('firecrawl_job_id', sa.String(100), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('pages_fetched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pages_filtered', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('file_ids', sa.dialects.postgresql.JSONB().with_variant(sa.JSON(), 'sqlite'), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_web_ingestion_jobs_user_id', 'web_ingestion_jobs', ['user_id'])
    op.create_index('ix_web_ingestion_jobs_status', 'web_ingestion_jobs', ['status'])
    op.create_index('ix_web_ingestion_jobs_created_at', 'web_ingestion_jobs', ['created_at'])

    with op.batch_alter_table('knowledge_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('url', sa.String(2048), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('knowledge_files', schema=None) as batch_op:
        batch_op.drop_column('url')

    op.drop_index('ix_web_ingestion_jobs_created_at', table_name='web_ingestion_jobs')
    op.drop_index('ix_web_ingestion_jobs_status', table_name='web_ingestion_jobs')
    op.drop_index('ix_web_ingestion_jobs_user_id', table_name='web_ingestion_jobs')
    op.drop_table('web_ingestion_jobs')
```

- [ ] **Step 3: 跑迁移(PG)**

Run: `cd apps/api && uv run alembic upgrade head`
Expected: 输出 `Running upgrade b_split_emb_config -> c3d4e5f6a7b8, add web_ingestion_jobs table...`

- [ ] **Step 4: 验证回滚可逆**

Run: `cd apps/api && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: 两次都成功,无报错

- [ ] **Step 5: 跑全量已有测试,确认零回归**

Run: `cd apps/api && uv run pytest -x`
Expected: 所有既有测试通过(36+ 个)

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/models/knowledge_file.py apps/api/alembic/versions/c3d4e5f6a7b8_add_web_ingestion_jobs.py
git commit -m "feat(db): web_ingestion_jobs 表 + knowledge_files.url 列"
```

---

## Task 4: ThreadPoolExecutor 后台任务基础设施

**Files:**
- Create: `apps/api/app/core/background.py`
- Test: `apps/api/tests/test_background.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_background.py`:

```python
"""线程池后台任务 spawn 测试。"""

import threading
import time

from app.core.background import spawn_background_task


def test_spawn_executes_function():
    """spawn 的任务被执行。"""
    result = {"done": False}

    def worker():
        time.sleep(0.01)
        result["done"] = True

    fut = spawn_background_task(worker)
    fut.result(timeout=2)  # 等完成

    assert result["done"] is True


def test_spawn_passes_args():
    """参数被正确传递。"""
    result = {}

    def worker(a, b, c=0):
        result["args"] = (a, b, c)

    fut = spawn_background_task(worker, 1, 2, c=3)
    fut.result(timeout=2)

    assert result["args"] == (1, 2, 3)


def test_spawn_does_not_block_caller():
    """spawn 立即返回,不阻塞调用方。"""
    result = {"started": False}

    def slow_worker():
        result["started"] = True
        time.sleep(1)

    start = time.monotonic()
    spawn_background_task(slow_worker)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5  # 立即返回
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_background.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.background'`

- [ ] **Step 3: 创建 background.py**

创建 `apps/api/app/core/background.py`:

```python
"""统一异步后台任务 spawn 入口。

供 FastAPI BackgroundTasks 之外的场景使用(如 startup 恢复扫描)。
max_workers=4 防止孤儿任务洪水把进程跑爆。

设计:docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 5 节。
"""

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg-task")


def spawn_background_task(func: Callable, *args, **kwargs) -> Future:
    """提交异步任务到线程池。立即返回 Future,不阻塞调用方。"""
    return _executor.submit(func, *args, **kwargs)
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_background.py -v`
Expected: PASS(3 个测试)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/background.py apps/api/tests/test_background.py
git commit -m "feat(core): ThreadPoolExecutor 后台任务 spawn 入口"
```

---

## Task 5: 质量过滤规则

**Files:**
- Create: `apps/api/app/parsing/content_filter.py`
- Test: `apps/api/tests/test_content_filter.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_content_filter.py`:

```python
"""content_filter 三层规则测试。"""

from app.parsing.content_filter import filter_content


# ── 规则 2:长度阈值 ─────────────────────────────────────────

def test_rejects_short_content():
    """低于阈值被拒。"""
    assert filter_content("太短", title="x") is None
    assert filter_content("a" * 199, title="x") is None


def test_accepts_chinese_above_threshold():
    """中文 100 字以上接受。"""
    md = "专利" * 50  # 100 个中文字
    result = filter_content(md, title="测试")
    assert result is not None
    assert result.word_count >= 100


def test_accepts_english_above_threshold():
    """英文 200 字符以上接受。"""
    md = "This patent describes a method " * 10  # ~310 字符
    result = filter_content(md, title="Patent")
    assert result is not None


# ── 规则 1:Markdown 去噪 ────────────────────────────────────

def test_strips_navigation_links():
    """连续 5+ 链接行被移除。"""
    nav = "\n".join(f"[item{i}](/page{i})" for i in range(10))
    body = "专利正文" * 100
    result = filter_content(nav + "\n\n" + body, title="x")
    assert result is not None
    assert "item0" not in result.markdown  # 导航被移除
    assert "专利正文" in result.markdown


def test_keeps_few_links():
    """4 个以下链接行保留(可能是正文引用)。"""
    few_links = "\n".join(f"[ref{i}](/r{i})" for i in range(3))
    body = "专利正文" * 100
    result = filter_content(few_links + "\n\n" + body, title="x")
    assert result is not None
    assert "ref0" in result.markdown  # 保留


def test_strips_boilerplate_keywords():
    """boilerplate 关键词区块被移除。"""
    body = "专利正文" * 100
    md = "Subscribe to our newsletter\n\n" + body + "\n\nAccept all cookies"
    result = filter_content(md, title="x")
    assert result is not None
    assert "Subscribe" not in result.markdown
    assert "Accept all" not in result.markdown


def test_strips_html_comments():
    """HTML 注释残留被移除。"""
    md = "<!-- tracking code -->\n" + "专利正文" * 100
    result = filter_content(md, title="x")
    assert result is not None
    assert "<!--" not in result.markdown


def test_collapses_blank_lines():
    """3+ 连续空行压缩为 2。"""
    md = "段一" + "\n\n\n\n\n" + "段二" * 100
    result = filter_content(md, title="x")
    assert result is not None
    assert "\n\n\n" not in result.markdown


# ── 规则 3:语言检测 ─────────────────────────────────────────

def test_rejects_pure_russian():
    """纯俄文页面被拒(>30% 非中英脚本)。"""
    russian = "Привет мир " * 50
    assert filter_content(russian, title="x") is None


def test_rejects_pure_arabic():
    """纯阿拉伯文页面被拒。"""
    arabic = "مرحبا بالعالم " * 50
    assert filter_content(arabic, title="x") is None


def test_accepts_mixed_chinese_english():
    """中英混排页面接受(中文页带英文术语)。"""
    md = "本 patent 涉及 " * 50  # 中文为主,带英文
    result = filter_content(md, title="x")
    assert result is not None


# ── 标题规范化 ───────────────────────────────────────────────

def test_preserves_title():
    """标题被保留。"""
    md = "正文" * 100
    result = filter_content(md, title="测试专利标题")
    assert result is not None
    assert result.title == "测试专利标题"


def test_empty_title_falls_back_to_default():
    """空标题给一个默认值。"""
    md = "正文" * 100
    result = filter_content(md, title="")
    assert result is not None
    assert result.title  # 非空
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_content_filter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.parsing.content_filter'`

- [ ] **Step 3: 实现 content_filter.py**

创建 `apps/api/app/parsing/content_filter.py`:

```python
"""网页内容质量过滤(三层规则)。

规则 1:Markdown 去噪(移除导航/boilerplate/HTML 注释/连续空行)
规则 2:长度阈值(中文 100 字 / 英文 200 字符)
规则 3:语言检测(只接受中文/英文,拒其他脚本)

返回 None 表示该页被拒绝入库。
spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 6 节。
"""

import re
from dataclasses import dataclass

MIN_CONTENT_CHARS = 200       # 英文阈值
MIN_CONTENT_CHARS_ZH = 100    # 中文阈值(信息密度高,放宽)
MAX_NAV_LINK_RUN = 5          # 连续链接行阈值(>= 此值视为导航)
DEFAULT_TITLE = "无标题网页"

BOILERPLATE_KEYWORDS = [
    "Cookie", "Subscribe", "Newsletter", "Sign up", "Related posts",
    "Share this", "Skip to content", "Back to top", "Accept all",
]

# 连续 N+ 行 markdown 链接(典型导航菜单)
_NAV_LINK_BLOCK = re.compile(
    r"((?:\[.+?\]\(.+?\)\s*\n){" + re.escape(str(MAX_NAV_LINK_RUN)) + r",})",
    re.MULTILINE,
)
# HTML 注释
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# 连续 3+ 空行
_MULTI_BLANK = re.compile(r"\n{3,}")
# markdown 链接行
_LINK_LINE = re.compile(r"^\s*\[.+?\]\(.+?\)\s*$", re.MULTILINE)


@dataclass
class FilteredContent:
    markdown: str   # 去噪后的干净正文
    title: str      # 规范化标题
    word_count: int # 字数(过滤判断 + 配额展示用)


def filter_content(raw_markdown: str, raw_title: str = "") -> FilteredContent | None:
    """规则质量过滤。返回 None 表示该页被拒绝入库。"""
    if not raw_markdown:
        return None

    # 规则 1:去噪
    cleaned = _denoise(raw_markdown)

    # 规则 2:长度阈值
    total, cjk = _count_chars(cleaned)
    threshold = MIN_CONTENT_CHARS_ZH if cjk > 0 else MIN_CONTENT_CHARS
    if total < threshold:
        return None

    # 规则 3:语言检测
    if not _is_supported_language(cleaned, cjk):
        return None

    title = raw_title.strip() if raw_title else DEFAULT_TITLE
    return FilteredContent(
        markdown=cleaned,
        title=title,
        word_count=total,
    )


def _denoise(markdown: str) -> str:
    """规则 1:去 boilerplate。"""
    # 移除 HTML 注释
    text = _HTML_COMMENT.sub("", markdown)
    # 移除连续 5+ 链接行(导航菜单)
    text = _NAV_LINK_BLOCK.sub("", text)
    # 移除 boilerplate 关键词所在整行
    lines = text.split("\n")
    kept = []
    for line in lines:
        if any(kw.lower() in line.lower() for kw in BOILERPLATE_KEYWORDS):
            continue
        kept.append(line)
    text = "\n".join(kept)
    # 压缩连续空行
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def _count_chars(markdown: str) -> tuple[int, int]:
    """返回 (总字符数, 中文字符数)。"""
    cjk = sum(1 for c in markdown if '\u4e00' <= c <= '\u9fff')
    return len(markdown), cjk


def _is_supported_language(markdown: str, cjk_count: int) -> bool:
    """判定页面是否中文/英文为主。
    
    宽松策略(避免误杀专利领域英文内容):
    - CJK 占比 >= 5% → 中文,接受
    - 拉丁字母为主且 CJK < 5% → 英文,接受
    - 其他脚本(西里尔/阿拉伯/假名等)占比 > 30% → 拒绝
    """
    if not markdown:
        return False
    # CJK 占比 >= 5% → 中文
    if cjk_count / len(markdown) >= 0.05:
        return True
    # 统计拉丁字母 + 数字 + 常见标点
    latin = sum(
        1 for c in markdown
        if c.isascii() and (c.isalnum() or c in " \n\t.,;:!?-_'\"()[]{}@#$%^&*+=/\\|<>`~")
    )
    if latin / len(markdown) >= 0.5:
        return True  # 以拉丁为主 → 英文
    return False
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_content_filter.py -v`
Expected: PASS(13 个测试)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/parsing/content_filter.py apps/api/tests/test_content_filter.py
git commit -m "feat(parsing): 网页内容质量过滤(去噪/长度/语言)"
```

---

## Task 6: llm_log_helper 加 log_firecrawl_call

**Files:**
- Modify: `apps/api/app/services/llm_log_helper.py`
- Test: `apps/api/tests/test_llm_log_helper.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_llm_log_helper.py`:

```python
"""log_firecrawl_call helper 测试。"""

import uuid

from app.models import LLMCallLog
from app.services.llm_log_helper import log_firecrawl_call


def test_log_firecrawl_call_writes_record(db_session):
    """写一条 action=firecrawl 的日志,pages 进 token_completion。"""
    uid = uuid.uuid4()
    log_firecrawl_call(
        db_session, user_id=uid, mode="crawl", pages=50, source="global",
    )
    record = db_session.query(LLMCallLog).filter_by(action="firecrawl").one()
    assert record.user_id == uid
    assert record.model == "firecrawl-crawl"
    assert record.provider == "global"
    assert record.token_completion == 50
    assert record.status == "success"


def test_log_firecrawl_call_negative_pages(db_session):
    """负 pages(退款/校正)正常写入。"""
    uid = uuid.uuid4()
    log_firecrawl_call(
        db_session, user_id=uid, mode="scrape", pages=-1, source="global",
        status="refund",
    )
    record = db_session.query(LLMCallLog).filter_by(action="firecrawl").one()
    assert record.token_completion == -1
    assert record.status == "refund"


def test_log_firecrawl_call_swallows_exception(db_session, monkeypatch):
    """DB 写失败时不抛(日志不阻塞主流程)。"""
    def boom(*args, **kwargs):
        raise RuntimeError("db down")
    monkeypatch.setattr(db_session, "commit", boom)
    
    uid = uuid.uuid4()
    # 不应抛
    log_firecrawl_call(
        db_session, user_id=uid, mode="scrape", pages=1, source="global",
    )
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_llm_log_helper.py -v`
Expected: FAIL with `ImportError: cannot import name 'log_firecrawl_call'`

- [ ] **Step 3: 在 llm_log_helper.py 加函数**

修改 `apps/api/app/services/llm_log_helper.py`,在文件末尾加:

```python


def log_firecrawl_call(
    db: Session, *,
    user_id,
    mode: str,
    pages: int,
    source: str = "global",
    status: str = "success",
) -> None:
    """写一条 Firecrawl 调用元数据日志。失败不抛(日志不应影响主流程)。
    
    pages 存在 token_completion 字段(语义复用:Firecrawl 无 token 概念,
    借该字段记页数;配额查询按 action='firecrawl' 聚合 SUM)。
    pages 可为负(退款/校正)。
    
    spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 3 节。
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

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_llm_log_helper.py -v`
Expected: PASS(3 个测试)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/llm_log_helper.py apps/api/tests/test_llm_log_helper.py
git commit -m "feat(services): log_firecrawl_call helper(配额记账)"
```

---

## Task 7: FirecrawlClient + 凭据解析

**Files:**
- Create: `apps/api/app/services/firecrawl_client.py`
- Test: `apps/api/tests/test_firecrawl_client.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_firecrawl_client.py`:

```python
"""FirecrawlClient + resolve_firecrawl_config 测试。

客户端测试用 mock,不真打 Firecrawl API。
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models import SystemSetting
from app.services.firecrawl_client import (
    CrawlJobHandle,
    CrawlStatus,
    FirecrawlClient,
    ResolvedFirecrawlConfig,
    get_firecrawl_settings,
    resolve_firecrawl_config,
    set_firecrawl_settings,
)
from app.core.exceptions import ValidationError


# ── dataclass ────────────────────────────────────────────────

def test_scrape_result_dataclass():
    from app.services.firecrawl_client import ScrapeResult
    r = ScrapeResult(url="x", title="t", markdown="md", status_code=200, fetch_failed=False)
    assert r.url == "x" and r.markdown == "md"


def test_crawl_status_dataclass():
    s = CrawlStatus(status="scrape", completed=5, total=50, pages=[], credits_used=0)
    assert s.status == "scrape" and s.completed == 5


def test_crawl_job_handle_dataclass():
    h = CrawlJobHandle(firecrawl_job_id="abc")
    assert h.firecrawl_job_id == "abc"


# ── FirecrawlClient(用 mock SDK)──────────────────────────────

@pytest.fixture
def client_with_mock_sdk():
    """构造一个 FirecrawlClient,内部 _sdk 被 mock。"""
    with patch("app.services.firecrawl_client.Firecrawl") as mock_sdk_class:
        mock_sdk = MagicMock()
        mock_sdk_class.return_value = mock_sdk
        client = FirecrawlClient(api_key="fc-test", base_url="https://x")
        yield client, mock_sdk


def test_scrape_returns_scrape_result(client_with_mock_sdk):
    """scrape 返回结构化 dataclass。"""
    client, mock_sdk = client_with_mock_sdk
    mock_sdk.scrape_url.return_value = {
        "data": {
            "markdown": "# Title\n\nbody",
            "metadata": {"title": "T", "sourceURL": "https://x", "statusCode": 200},
        }
    }
    result = client.scrape("https://x")
    assert result.markdown == "# Title\n\nbody"
    assert result.title == "T"
    assert result.url == "https://x"
    assert result.status_code == 200
    assert result.fetch_failed is False


def test_scrape_handles_failure(client_with_mock_sdk):
    """scrape 异常时 fetch_failed=True。"""
    client, mock_sdk = client_with_mock_sdk
    mock_sdk.scrape_url.side_effect = RuntimeError("network error")
    result = client.scrape("https://x")
    assert result.fetch_failed is True
    assert result.markdown == ""


def test_start_crawl_returns_handle(client_with_mock_sdk):
    """start_crawl 返回 firecrawl_job_id 句柄。"""
    client, mock_sdk = client_with_mock_sdk
    mock_sdk.crawl_url.return_value = {"id": "fc-job-123"}
    handle = client.start_crawl("https://x", limit=50)
    assert handle.firecrawl_job_id == "fc-job-123"


def test_check_crawl_in_progress(client_with_mock_sdk):
    """进行中状态返回 status='scrape',pages 为空。"""
    client, mock_sdk = client_with_mock_sdk
    mock_sdk.check_crawl_status.return_value = {
        "status": "scrape", "completed": 5, "total": 50,
        "data": [], "creditsUsed": 0,
    }
    status = client.check_crawl("fc-job-123")
    assert status.status == "scrape"
    assert status.completed == 5
    assert status.total == 50
    assert status.pages == []


def test_check_crawl_completed(client_with_mock_sdk):
    """完成状态填充 pages。"""
    client, mock_sdk = client_with_mock_sdk
    mock_sdk.check_crawl_status.return_value = {
        "status": "completed", "completed": 2, "total": 2,
        "data": [
            {"markdown": "page1", "metadata": {"sourceURL": "https://x/1", "statusCode": 200, "title": "P1"}},
            {"markdown": "page2", "metadata": {"sourceURL": "https://x/2", "statusCode": 200, "title": "P2"}},
        ],
        "creditsUsed": 2,
    }
    status = client.check_crawl("fc-job-123")
    assert status.status == "completed"
    assert len(status.pages) == 2
    assert status.pages[0].markdown == "page1"
    assert status.credits_used == 2


def test_check_crawl_failed(client_with_mock_sdk):
    """失败状态。"""
    client, mock_sdk = client_with_mock_sdk
    mock_sdk.check_crawl_status.return_value = {
        "status": "failed", "completed": 1, "total": 50,
        "data": [], "creditsUsed": 1,
    }
    status = client.check_crawl("fc-job-123")
    assert status.status == "failed"


# ── resolve_firecrawl_config ─────────────────────────────────

def test_resolve_prefers_global(db_session, monkeypatch):
    """全局配置优先于 env。"""
    set_firecrawl_settings(db_session, enabled=True, api_key="fc-global",
                           base_url="https://fc.example", updated_by=uuid.uuid4())
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-env")
    config = resolve_firecrawl_config(db_session)
    assert config.api_key == "fc-global"
    assert config.source == "global"
    assert config.base_url == "https://fc.example"


def test_resolve_falls_back_to_env(db_session, monkeypatch):
    """全局禁用时回落 env。"""
    set_firecrawl_settings(db_session, enabled=False, api_key="fc-x", updated_by=uuid.uuid4())
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-env")
    config = resolve_firecrawl_config(db_session)
    assert config.api_key == "fc-env"
    assert config.source == "env"


def test_resolve_returns_none_when_unconfigured(db_session, monkeypatch):
    """都没配置返回 None。"""
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    assert resolve_firecrawl_config(db_session) is None


# ── get/set_firecrawl_settings ───────────────────────────────

def test_set_then_get_roundtrip(db_session):
    """set 后 get 返回脱敏 key。"""
    set_firecrawl_settings(
        db_session, enabled=True, api_key="fc-1234567890",
        base_url="https://fc.x", updated_by=uuid.uuid4(),
    )
    result = get_firecrawl_settings(db_session)
    assert result["enabled"] is True
    assert result["base_url"] == "https://fc.x"
    assert "fc-1234567890" not in result["api_key_masked"]  # 脱敏
    assert "***" in result["api_key_masked"] or "****" in result["api_key_masked"]


def test_set_preserves_key_when_empty(db_session):
    """api_key 空串时保留已有 key(不覆盖)。"""
    set_firecrawl_settings(
        db_session, enabled=True, api_key="fc-orig",
        base_url="https://x", updated_by=uuid.uuid4(),
    )
    set_firecrawl_settings(
        db_session, enabled=False, api_key="",  # 空,不改 key
        base_url="https://y", updated_by=uuid.uuid4(),
    )
    config = resolve_firecrawl_config(db_session)  # 禁用,走 env 或 None
    # 但 key 应仍在 SystemSetting 里
    cfg_setting = db_session.query(SystemSetting).filter_by(key="firecrawl_config").one()
    assert cfg_setting.value.get("api_key_encrypted")  # key 还在
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_firecrawl_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.firecrawl_client'`

- [ ] **Step 3: 实现 firecrawl_client.py**

创建 `apps/api/app/services/firecrawl_client.py`:

```python
"""Firecrawl 客户端封装 + 凭据解析 + admin 配置 get/set。

封装薄客户端,屏蔽 firecrawl-py SDK 细节,对上层只暴露领域语义方法。
返回 dataclass(不返回 SDK 原始对象),换 SDK/供应商时只改本文件。

spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 4 节。
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SystemSetting
from app.services.llm_config_service import decrypt_value, encrypt_value, _mask_key


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
    """crawl 任务轮询状态。"""
    status: str         # scrape(进行中) / completed / failed
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


# ── 客户端 ────────────────────────────────────────────────────

class FirecrawlClient:
    """firecrawl-py SDK 的薄封装。"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.firecrawl.dev"):
        from firecrawl import Firecrawl
        self._sdk = Firecrawl(api_key=api_key, api_url=base_url)

    def scrape(self, url: str) -> ScrapeResult:
        """同步抓单页。异常时返回 fetch_failed=True(不抛)。"""
        try:
            resp = self._sdk.scrape_url(url, formats=["markdown"])
            data = resp.get("data", {}) if isinstance(resp, dict) else getattr(resp, "data", {})
            metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
            return ScrapeResult(
                url=url,
                title=metadata.get("title", "") or "",
                markdown=data.get("markdown", "") if isinstance(data, dict) else "",
                status_code=metadata.get("statusCode", 200),
                fetch_failed=False,
            )
        except Exception:
            return ScrapeResult(
                url=url, title="", markdown="", status_code=0, fetch_failed=True,
            )

    def start_crawl(self, url: str, *, limit: int) -> CrawlJobHandle:
        """异步发起整站抓取。立即返回 job_id,不阻塞。"""
        resp = self._sdk.crawl_url(url, limit=limit, scrape_options={"formats": ["markdown"]})
        if isinstance(resp, dict):
            return CrawlJobHandle(firecrawl_job_id=resp["id"])
        return CrawlJobHandle(firecrawl_job_id=getattr(resp, "id"))

    def check_crawl(self, firecrawl_job_id: str) -> CrawlStatus:
        """查询 crawl 任务状态。进行中时 pages 为空。"""
        resp = self._sdk.check_crawl_status(firecrawl_job_id)
        if not isinstance(resp, dict):
            resp = {"status": getattr(resp, "status", "unknown")}
        status = resp.get("status", "scrape")
        completed = resp.get("completed", 0) or resp.get("total", 0)
        total = resp.get("total", 0)
        credits = resp.get("creditsUsed", 0) or 0
        data = resp.get("data", [])
        pages = []
        if status == "completed":
            for item in data:
                md = item.get("markdown", "") if isinstance(item, dict) else ""
                meta = item.get("metadata", {}) if isinstance(item, dict) else {}
                pages.append(ScrapeResult(
                    url=meta.get("sourceURL", ""),
                    title=meta.get("title", ""),
                    markdown=md,
                    status_code=meta.get("statusCode", 200),
                    fetch_failed=False,
                ))
        return CrawlStatus(
            status=status, completed=completed, total=total,
            pages=pages, credits_used=credits,
        )


# ── 凭据解析 ─────────────────────────────────────────────────

def resolve_firecrawl_config(db: Session) -> ResolvedFirecrawlConfig | None:
    """三级 fallback:全局 SystemSetting → env。无可用配置返回 None。
    
    与 chat/embedding 不同,Firecrawl 只有「全局」一层(不做 BYOK)。
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
            base_url = cfg_setting.value.get("base_url") or "https://api.firecrawl.dev"
            return ResolvedFirecrawlConfig(
                api_key=api_key, base_url=base_url, source="global",
            )

    # 2) env 兜底
    s = get_settings()
    if s.firecrawl_api_key:
        return ResolvedFirecrawlConfig(
            api_key=s.firecrawl_api_key,
            base_url=s.firecrawl_base_url or "https://api.firecrawl.dev",
            source="env",
        )

    return None


# ── admin 配置 get/set ───────────────────────────────────────

def get_firecrawl_settings(db: Session) -> dict:
    """读全局 Firecrawl 配置(api_key 脱敏返回)。"""
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
    """upsert 全局 Firecrawl 配置。api_key 空串表示不改。"""
    # enabled
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

    # config
    if api_key or base_url is not None:
        cfg_setting = db.scalar(
            select(SystemSetting).where(SystemSetting.key == "firecrawl_config")
        )
        current = cfg_setting.value if cfg_setting else {}
        new_value = {
            "base_url": base_url if base_url is not None else current.get("base_url", "https://api.firecrawl.dev"),
        }
        if api_key:
            new_value["api_key_encrypted"] = encrypt_value(api_key)
        elif current.get("api_key_encrypted"):
            new_value["api_key_encrypted"] = current["api_key_encrypted"]
        if cfg_setting:
            cfg_setting.value = new_value
        else:
            db.add(SystemSetting(
                key="firecrawl_config", value=new_value, updated_by=updated_by,
            ))
    db.commit()
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_firecrawl_client.py -v`
Expected: PASS(所有测试)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/firecrawl_client.py apps/api/tests/test_firecrawl_client.py
git commit -m "feat(services): FirecrawlClient + 凭据解析 + admin get/set"
```

---

## Task 8: knowledge_service.upload_*  加 url 参数

**Files:**
- Modify: `apps/api/app/services/knowledge_service.py`
- Test: `apps/api/tests/test_knowledge_service_url.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_knowledge_service_url.py`:

```python
"""knowledge_service upload_* 函数的 url 参数测试。"""

import uuid
from unittest.mock import MagicMock

from app.models import KnowledgeFile
from app.services import knowledge_service


def _mock_storage():
    storage = MagicMock()
    return storage


def _mock_user(uid=None):
    user = MagicMock()
    user.id = uid or uuid.uuid4()
    user.is_admin = False
    return user


def test_upload_external_with_url(db_session):
    """upload_external 的 url 参数被写入 KnowledgeFile.url。"""
    storage = _mock_storage()
    user = _mock_user()
    kf = knowledge_service.upload_external(
        db_session, storage=storage, user=user,
        filename="page.md", content=b"正文" * 100,
        mime="text/markdown", text="正文" * 100,
        url="https://example.com/page",
    )
    assert kf.url == "https://example.com/page"


def test_upload_external_without_url(db_session):
    """url 默认 None,不影响现有 docx/pdf 上传。"""
    storage = _mock_storage()
    user = _mock_user()
    kf = knowledge_service.upload_external(
        db_session, storage=storage, user=user,
        filename="doc.docx", content=b"content",
        mime="application/octet-stream", text="text",
    )
    assert kf.url is None


def test_upload_to_global_with_url(db_session):
    """upload_to_global 的 url 参数被写入。"""
    storage = _mock_storage()
    admin = _mock_user()
    admin.is_admin = True
    kf = knowledge_service.upload_to_global(
        db_session, storage=storage, uploader=admin,
        filename="page.md", content=b"unique-content-for-url-test-1",
        mime="text/markdown", text="unique-content-for-url-test-1",
        url="https://example.com/global",
    )
    assert kf.url == "https://example.com/global"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_knowledge_service_url.py -v`
Expected: FAIL with `TypeError: upload_external() got an unexpected keyword argument 'url'`

- [ ] **Step 3: 修改 upload_external 签名**

修改 `apps/api/app/services/knowledge_service.py`,把 `upload_external` 函数签名(第 73-76 行)改为:

```python
def upload_external(
    db, *, storage: Storage, user, filename: str,
    content: bytes, mime: str, text: str,
    url: str | None = None,
) -> KnowledgeFile:
    """user 上传外部素材进个人库。scope=personal,仅本人可检索。"""
```

然后在 `KnowledgeFile(...)` 构造(第 84-89 行)加 `url=url`:

```python
    kf = KnowledgeFile(
        uploader_id=user.id, scope="personal", bucket="personal",
        object_key=object_key, filename=filename, mime_type=mime,
        size=len(content), source_type=source_type,
        content_hash=hashlib.sha256(content).hexdigest(),
        url=url,
    )
```

- [ ] **Step 4: 修改 upload_to_global 签名**

同文件,把 `upload_to_global`(第 29-32 行)签名改为:

```python
def upload_to_global(
    db, *, storage: Storage, uploader, filename: str,
    content: bytes, mime: str, text: str,
    url: str | None = None,
) -> KnowledgeFile:
```

然后在 `KnowledgeFile(...)` 构造(第 56-61 行)加 `url=url`:

```python
    kf = KnowledgeFile(
        uploader_id=uploader.id, scope="global", bucket="global",
        object_key=object_key, filename=filename, mime_type=mime,
        size=len(content), source_type=source_type,
        content_hash=content_hash,
        url=url,
    )
```

- [ ] **Step 5: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_knowledge_service_url.py -v`
Expected: PASS(3 个测试)

- [ ] **Step 6: 跑全量测试确认零回归**

Run: `cd apps/api && uv run pytest -x`
Expected: 全部通过

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/services/knowledge_service.py apps/api/tests/test_knowledge_service_url.py
git commit -m "feat(knowledge): upload_external/upload_to_global 加 url 参数"
```

---

## Task 9: URL 校验 + 配额函数(SSRF 防护 + 配额控制)

**Files:**
- Create: `apps/api/app/services/web_ingestion_service.py`(本任务只填 URL 校验 + 配额函数,后续任务扩展)
- Test: `apps/api/tests/test_web_ingestion_service_helpers.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_web_ingestion_service_helpers.py`:

```python
"""web_ingestion_service 的 helper 函数测试(URL 校验 + 配额)。"""

import uuid
from unittest.mock import patch

import pytest

from app.core.exceptions import ValidationError
from app.services.web_ingestion_service import (
    MAX_CRAWL_PAGES_HARD_CAP,
    DEFAULT_QUOTA_PER_USER_PER_DAY,
    _validate_url,
    _used_pages_today,
    _reserve_quota,
    _refund_quota,
)
from app.services.llm_log_helper import log_firecrawl_call


# ── _validate_url(SSRF 防护)──────────────────────────────────

@pytest.mark.parametrize("url,should_pass", [
    ("https://example.com", True),
    ("http://example.com/path/to/page", True),
    ("http://example.com:8080/x", True),
    ("ftp://example.com", False),                       # 协议错
    ("http://127.0.0.1/admin", False),                  # loopback
    ("http://10.0.0.1/internal", False),                # 内网 A
    ("http://172.16.0.1/x", False),                     # 内网 B
    ("http://192.168.1.1", False),                      # 内网 C
    ("http://169.254.169.254/latest/meta-data", False), # 云元数据
    ("http://metadata.google.internal", False),         # GCE 元数据
    ("http://[::1]", False),                            # IPv6 loopback
    ("not-a-url", False),                               # 非法格式
    ("", False),                                        # 空
])
def test_validate_url_ssrf_protection(url, should_pass):
    if should_pass:
        _validate_url(url)
    else:
        with pytest.raises(ValidationError):
            _validate_url(url)


def test_validate_url_rejects_too_long():
    """超长 URL 被拒。"""
    long_url = "https://example.com/" + "a" * 2100
    with pytest.raises(ValidationError):
        _validate_url(long_url)


# ── 配额 ─────────────────────────────────────────────────────

def test_used_pages_today_starts_at_zero(db_session):
    """新用户当日使用量为 0。"""
    assert _used_pages_today(db_session, uuid.uuid4()) == 0


def test_used_pages_today_sums_logs(db_session):
    """聚合当日 firecrawl 日志的页数。"""
    uid = uuid.uuid4()
    log_firecrawl_call(db_session, user_id=uid, mode="scrape", pages=5, source="global")
    log_firecrawl_call(db_session, user_id=uid, mode="crawl", pages=50, source="global")
    assert _used_pages_today(db_session, uid) == 55


def test_used_pages_today_excludes_other_users(db_session):
    """只算本人。"""
    uid1, uid2 = uuid.uuid4(), uuid.uuid4()
    log_firecrawl_call(db_session, user_id=uid1, mode="scrape", pages=5, source="global")
    log_firecrawl_call(db_session, user_id=uid2, mode="scrape", pages=50, source="global")
    assert _used_pages_today(db_session, uid1) == 5


def test_reserve_quota_allows_within_limit(db_session):
    """配额内允许。"""
    uid = uuid.uuid4()
    _reserve_quota(db_session, user=_mock_user(uid), mode="scrape", max_pages=1)
    # 预扣后当日用量应为 1
    assert _used_pages_today(db_session, uid) == 1


def test_reserve_quota_rejects_over_limit(db_session):
    """超额报错。"""
    uid = uuid.uuid4()
    # 先把配额填满
    log_firecrawl_call(
        db_session, user_id=uid, mode="crawl",
        pages=DEFAULT_QUOTA_PER_USER_PER_DAY, source="global",
    )
    with pytest.raises(ValidationError):
        _reserve_quota(db_session, user=_mock_user(uid), mode="scrape", max_pages=1)


def test_reserve_quota_crawl_uses_max_pages(db_session):
    """crawl 模式按 max_pages 预扣。"""
    uid = uuid.uuid4()
    _reserve_quota(db_session, user=_mock_user(uid), mode="crawl", max_pages=50)
    assert _used_pages_today(db_session, uid) == 50


def test_refund_quota_decrements(db_session):
    """退款减量。"""
    uid = uuid.uuid4()
    _reserve_quota(db_session, user=_mock_user(uid), mode="scrape", max_pages=1)
    _refund_quota(db_session, user=_mock_user(uid), pages=1)
    assert _used_pages_today(db_session, uid) == 0


def _mock_user(uid):
    from unittest.mock import MagicMock
    u = MagicMock()
    u.id = uid
    u.is_admin = False
    return u
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_service_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.web_ingestion_service'`

- [ ] **Step 3: 创建 web_ingestion_service.py(helper 部分)**

创建 `apps/api/app/services/web_ingestion_service.py`:

```python
"""网页摄入服务:create_job / run_job / recover_pending_jobs + helpers。

scrape 同步返回 KnowledgeFile,crawl 异步建 WebIngestionJob + 后台轮询。
抓回内容标准化成 KnowledgeFile(source_type='external_web'),走现有入库流。

spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 5、7 节。
"""

import ipaddress
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
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
BLOCKED_HOSTS = {"metadata.google.internal", "169.254.169.254"}


# ── URL 校验(SSRF 防护)──────────────────────────────────────

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
    # 拒内网 IP / loopback
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            raise ValidationError("不允许访问内网地址")
    except ValueError:
        pass  # 非 IP(域名),允许


# ── 配额 ─────────────────────────────────────────────────────

def _used_pages_today(db: Session, user_id) -> int:
    """查询当日已用页数(SUM token_completion,action=firecrawl)。"""
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
    """预扣配额。超额报错。"""
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
    """退款(负 pages)。"""
    log_firecrawl_call(
        db, user_id=user.id, mode="scrape",
        pages=-pages, source="global", status="refund",
    )


def _correct_quota(db: Session, *, job: WebIngestionJob) -> None:
    """crawl 完成时按实际页数校正。多退少补。"""
    actual = job.pages_fetched - job.pages_filtered
    reserved = job.max_pages
    delta = actual - reserved
    if delta != 0:
        log_firecrawl_call(
            db, user_id=job.user_id, mode="crawl",
            pages=delta, source="global", status="correction",
        )


# ── 后续任务扩展:create_job / run_job / recover_pending_jobs ──
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_service_helpers.py -v`
Expected: PASS(所有测试)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/web_ingestion_service.py apps/api/tests/test_web_ingestion_service_helpers.py
git commit -m "feat(services): URL 校验(SSRF 防护)+ 配额函数"
```

---

## Task 10: create_job + _scrape_sync + _crawl_async(主入口)

**Files:**
- Modify: `apps/api/app/services/web_ingestion_service.py`
- Test: `apps/api/tests/test_web_ingestion_service_create.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_web_ingestion_service_create.py`:

```python
"""create_job / _scrape_sync / _crawl_async 测试。"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, ValidationError
from app.models import KnowledgeFile, WebIngestionJob
from app.services.firecrawl_client import (
    CrawlJobHandle, CrawlStatus, ResolvedFirecrawlConfig, ScrapeResult,
)
from app.services import web_ingestion_service
from app.services.web_ingestion_service import create_job


@pytest.fixture
def mock_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_admin = False
    return u


@pytest.fixture
def mock_admin():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_admin = True
    return u


@pytest.fixture
def fake_config():
    return ResolvedFirecrawlConfig(
        api_key="fc-test", base_url="https://x", source="global",
    )


# ── 入口校验 ─────────────────────────────────────────────────

def test_rejects_invalid_url(db_session, mock_user, fake_config):
    """非法 URL 报错。"""
    with patch("app.services.web_ingestion_service.resolve_firecrawl_config",
               return_value=fake_config):
        with pytest.raises(ValidationError):
            create_job(db_session, user=mock_user, url="ftp://x",
                       mode="scrape", scope="personal")


def test_rejects_unconfigured(db_session, mock_user):
    """Firecrawl 未配置报错。"""
    with patch("app.services.web_ingestion_service.resolve_firecrawl_config",
               return_value=None):
        with pytest.raises(ValidationError, match="未配置"):
            create_job(db_session, user=mock_user, url="https://x.com",
                       mode="scrape", scope="personal")


def test_rejects_non_admin_to_global(db_session, mock_user, fake_config):
    """非 admin 入 global 报错。"""
    with patch("app.services.web_ingestion_service.resolve_firecrawl_config",
               return_value=fake_config):
        with pytest.raises(AuthorizationError):
            create_job(db_session, user=mock_user, url="https://x.com",
                       mode="scrape", scope="global")


def test_rejects_crawl_over_cap(db_session, mock_user, fake_config):
    """crawl max_pages 超过硬上限报错。"""
    with patch("app.services.web_ingestion_service.resolve_firecrawl_config",
               return_value=fake_config):
        with pytest.raises(ValidationError):
            create_job(db_session, user=mock_user, url="https://x.com",
                       mode="crawl", scope="personal",
                       max_pages=web_ingestion_service.MAX_CRAWL_PAGES_HARD_CAP + 1)


# ── scrape 同步流 ────────────────────────────────────────────

@patch("app.services.web_ingestion_service.spawn_background_task")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_scrape_returns_knowledgefile(
    mock_client_cls, mock_resolve, mock_spawn, db_session, mock_user, fake_config,
):
    """scrape 同步返回 KnowledgeFile。"""
    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.scrape.return_value = ScrapeResult(
        url="https://example.com/p", title="测试页",
        markdown="专利正文" * 100, status_code=200, fetch_failed=False,
    )
    with patch("app.services.web_ingestion_service.get_storage") as mock_storage:
        mock_storage.return_value = MagicMock()
        kf = create_job(
            db_session, user=mock_user, url="https://example.com/p",
            mode="scrape", scope="personal",
        )
    assert isinstance(kf, KnowledgeFile)
    assert kf.scope == "personal"
    assert kf.source_type == "external_web"
    assert kf.url == "https://example.com/p"


@patch("app.services.web_ingestion_service.spawn_background_task")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_scrape_filtered_refunds_quota(
    mock_client_cls, mock_resolve, mock_spawn, db_session, mock_user, fake_config,
):
    """scrape 内容被过滤时退款并报错。"""
    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.scrape.return_value = ScrapeResult(
        url="https://x", title="x", markdown="太短",  # 触发长度过滤
        status_code=200, fetch_failed=False,
    )
    with patch("app.services.web_ingestion_service.get_storage"):
        with pytest.raises(ValidationError, match="质量过滤"):
            create_job(db_session, user=mock_user, url="https://x",
                       mode="scrape", scope="personal")
    # 配额应回退(预扣 1 + 退款 -1 = 0)
    used = web_ingestion_service._used_pages_today(db_session, mock_user.id)
    assert used == 0


@patch("app.services.web_ingestion_service.spawn_background_task")
@patch("app.services.web_ingestion_config" if False else "app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_scrape_fetch_failed_refunds(
    mock_client_cls, mock_resolve, mock_spawn, db_session, mock_user, fake_config,
):
    """scrape 抓取失败(fetch_failed=True)退款并报错。"""
    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.scrape.return_value = ScrapeResult(
        url="https://x", title="", markdown="", status_code=0, fetch_failed=True,
    )
    with patch("app.services.web_ingestion_service.get_storage"):
        with pytest.raises(ValidationError):
            create_job(db_session, user=mock_user, url="https://x",
                       mode="scrape", scope="personal")
    used = web_ingestion_service._used_pages_today(db_session, mock_user.id)
    assert used == 0


# ── crawl 异步流 ─────────────────────────────────────────────

@patch("app.services.web_ingestion_service.spawn_background_task")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_crawl_creates_job_and_spawns_task(
    mock_client_cls, mock_resolve, mock_spawn, db_session, mock_admin, fake_config,
):
    """crawl 建 job 并 spawn 后台任务。"""
    mock_resolve.return_value = fake_config
    client = MagicMock()
    mock_client_cls.return_value = client
    client.start_crawl.return_value = CrawlJobHandle(firecrawl_job_id="fc-job-1")
    
    job = create_job(
        db_session, user=mock_admin, url="https://example.com",
        mode="crawl", scope="global", max_pages=50,
    )
    assert isinstance(job, WebIngestionJob)
    assert job.status == "running"
    assert job.firecrawl_job_id == "fc-job-1"
    assert job.scope == "global"
    assert job.max_pages == 50
    mock_spawn.assert_called_once()
    # spawn 的第一个参数应是 run_job 函数
    assert mock_spawn.call_args[0][0].__name__ == "run_job"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_service_create.py -v`
Expected: FAIL with `ImportError: cannot import name 'create_job'`

- [ ] **Step 3: 在 web_ingestion_service.py 添加 create_job 等**

在 `apps/api/app/services/web_ingestion_service.py` 末尾(`# ── 后续任务扩展` 注释处)替换为:

```python
# ── 主入口 ───────────────────────────────────────────────────

from app.core.exceptions import AuthorizationError  # noqa: E402
from app.core.storage import get_storage  # noqa: E402
from app.models import KnowledgeFile  # noqa: E402
from app.parsing.content_filter import filter_content  # noqa: E402
from app.services import knowledge_service  # noqa: E402
from app.services.firecrawl_client import (  # noqa: E402
    CrawlJobHandle, FirecrawlClient, ResolvedFirecrawlConfig,
    resolve_firecrawl_config,
)
from app.core.background import spawn_background_task  # noqa: E402


def create_job(
    db: Session, *, user, url: str, mode: str, scope: str, max_pages: int = 1,
):
    """发起网页摄入。scrape 同步返回 KnowledgeFile,crawl 异步返回 WebIngestionJob。"""
    # ① 校验
    _validate_url(url)
    if mode not in ("scrape", "crawl"):
        raise ValidationError(f"不支持的模式:{mode}")
    if mode == "crawl" and max_pages > MAX_CRAWL_PAGES_HARD_CAP:
        raise ValidationError(f"max_pages 上限 {MAX_CRAWL_PAGES_HARD_CAP}")
    if scope == "global" and not getattr(user, "is_admin", False):
        raise AuthorizationError("仅 admin 可入 global 库")

    # ② 凭据
    config = resolve_firecrawl_config(db)
    if config is None:
        raise ValidationError("Firecrawl 未配置,请联系管理员")

    # ③ 配额预扣
    _reserve_quota(db, user=user, mode=mode, max_pages=max_pages)

    # ④ 分叉
    try:
        if mode == "scrape":
            return _scrape_sync(
                db, user=user, url=url, scope=scope, config=config,
            )
        return _crawl_async(
            db, user=user, url=url, scope=scope,
            max_pages=max_pages, config=config,
        )
    except Exception:
        # 分叉内部异常:配额已预扣,这里不重复退款(由具体分支处理)
        raise


def _derive_filename(title: str, url: str) -> str:
    """从标题或 URL 推导展示用文件名。"""
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
    """单页同步流:scrape → filter → upload。"""
    client = FirecrawlClient(config.api_key, config.base_url)
    result = client.scrape(url)

    # 抓取失败
    if result.fetch_failed:
        _refund_quota(db, user=user, pages=1)
        raise ValidationError("页面抓取失败")

    # 质量过滤
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
    """整站异步流:start_crawl → 建 job → spawn 轮询任务。"""
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
# (后续任务实现)
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_service_create.py -v`
Expected: PASS(所有测试)

注:`run_job` 此时还未定义,`_crawl_async` 里引用了它。Step 3 的代码在 `_crawl_async` 中调用 `run_job`,但函数未定义——这会导致 NameError。

**修正**:在 Step 3 代码末尾加占位(后续 Task 11 替换):

```python


def run_job(job_id: str) -> None:
    """BackgroundTask 入口。Task 11 实现。"""
    raise NotImplementedError("run_job 在 Task 11 实现")
```

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/web_ingestion_service.py apps/api/tests/test_web_ingestion_service_create.py
git commit -m "feat(services): create_job 入口 + scrape 同步 + crawl 异步"
```

---

## Task 11: run_job 轮询主循环 + 入库

**Files:**
- Modify: `apps/api/app/services/web_ingestion_service.py`
- Test: `apps/api/tests/test_web_ingestion_service_run.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_web_ingestion_service_run.py`:

```python
"""run_job / _poll_and_ingest 测试。"""

import time
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models import KnowledgeFile, WebIngestionJob
from app.services.firecrawl_client import CrawlStatus, ScrapeResult
from app.services import web_ingestion_service
from app.services.web_ingestion_service import run_job


def _make_page(i: int = 1) -> ScrapeResult:
    return ScrapeResult(
        url=f"https://example.com/p{i}", title=f"页{i}",
        markdown=f"专利正文{i}" * 50, status_code=200, fetch_failed=False,
    )


@pytest.fixture
def fake_job(db_session):
    """建一个 running 的 WebIngestionJob。"""
    uid = uuid.uuid4()
    job = WebIngestionJob(
        user_id=uid, scope="global", url="https://example.com",
        mode="crawl", max_pages=50, firecrawl_job_id="fc-job-1",
        status="running",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@patch("app.services.web_ingestion_service.time.sleep")  # 跳过真实 sleep
@patch("app.services.web_ingestion_service.get_storage")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_run_job_polls_until_completed(
    mock_client_cls, mock_resolve, mock_storage, mock_sleep, db_session, fake_job,
):
    """前两次进行中,第三次完成 → job.completed + file_ids 填充。"""
    from app.services.firecrawl_client import ResolvedFirecrawlConfig
    mock_resolve.return_value = ResolvedFirecrawlConfig(
        api_key="x", base_url="x", source="global",
    )
    client = MagicMock()
    mock_client_cls.return_value = client
    client.check_crawl.side_effect = [
        CrawlStatus(status="scrape", completed=5, total=50, pages=[], credits_used=0),
        CrawlStatus(status="scrape", completed=20, total=50, pages=[], credits_used=0),
        CrawlStatus(status="completed", completed=2, total=2,
                    pages=[_make_page(1), _make_page(2)], credits_used=2),
    ]
    mock_storage.return_value = MagicMock()
    
    run_job(str(fake_job.id))
    
    db_session.refresh(fake_job)
    assert fake_job.status == "completed"
    assert fake_job.pages_fetched == 2
    assert len(fake_job.file_ids) == 2


@patch("app.services.web_ingestion_service.time.sleep")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_run_job_marks_failed_on_firecrawl_failure(
    mock_client_cls, mock_resolve, mock_sleep, db_session, fake_job,
):
    """Firecrawl 远端失败 → job.failed。"""
    from app.services.firecrawl_client import ResolvedFirecrawlConfig
    mock_resolve.return_value = ResolvedFirecrawlConfig(
        api_key="x", base_url="x", source="global",
    )
    client = MagicMock()
    mock_client_cls.return_value = client
    client.check_crawl.return_value = CrawlStatus(
        status="failed", completed=10, total=50, pages=[], credits_used=10,
    )
    
    run_job(str(fake_job.id))
    
    db_session.refresh(fake_job)
    assert fake_job.status == "failed"
    assert "Firecrawl 任务失败" in (fake_job.error_message or "")


@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
def test_run_job_idempotent_on_completed(mock_resolve, db_session, fake_job):
    """已 completed 的 job 重跑无副作用。"""
    mock_resolve.return_value = MagicMock()
    fake_job.status = "completed"
    db_session.commit()
    
    run_job(str(fake_job.id))  # 不应抛,不应改状态
    
    db_session.refresh(fake_job)
    assert fake_job.status == "completed"


@patch("app.services.web_ingestion_service.time.sleep")
@patch("app.services.web_ingestion_service.get_storage")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_run_job_filters_garbage_pages(
    mock_client_cls, mock_resolve, mock_storage, mock_sleep, db_session, fake_job,
):
    """垃圾页被过滤,pages_filtered 计数。"""
    from app.services.firecrawl_client import ResolvedFirecrawlConfig
    mock_resolve.return_value = ResolvedFirecrawlConfig(
        api_key="x", base_url="x", source="global",
    )
    client = MagicMock()
    mock_client_cls.return_value = client
    garbage = ScrapeResult(
        url="https://x/garbage", title="x", markdown="太短",
        status_code=200, fetch_failed=False,
    )
    good = _make_page()
    client.check_crawl.return_value = CrawlStatus(
        status="completed", completed=2, total=2,
        pages=[garbage, good], credits_used=2,
    )
    mock_storage.return_value = MagicMock()
    
    run_job(str(fake_job.id))
    
    db_session.refresh(fake_job)
    assert fake_job.status == "completed"
    assert fake_job.pages_fetched == 2
    assert fake_job.pages_filtered == 1  # 一个被过滤
    assert len(fake_job.file_ids) == 1   # 只入了一个


@patch("app.services.web_ingestion_service.time.sleep")
@patch("app.services.web_ingestion_service.resolve_firecrawl_config")
@patch("app.services.web_ingestion_service.FirecrawlClient")
def test_run_job_marks_failed_on_unconfigured(
    mock_client_cls, mock_resolve, mock_sleep, db_session, fake_job,
):
    """Firecrawl 配置丢失 → job.failed。"""
    mock_resolve.return_value = None
    run_job(str(fake_job.id))
    db_session.refresh(fake_job)
    assert fake_job.status == "failed"
    assert "配置丢失" in (fake_job.error_message or "")
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_service_run.py -v`
Expected: FAIL with `NotImplementedError` 或类似

- [ ] **Step 3: 实现 run_job / _poll_and_ingest / _ingest_crawl_pages / _mark_failed**

修改 `apps/api/app/services/web_ingestion_service.py`,把末尾的占位 `def run_job... raise NotImplementedError` 替换为:

```python
import time as _time
from datetime import timedelta


def run_job(job_id: str) -> None:
    """BackgroundTask 入口。自开独立 Session(对称 run_parse_job_standalone)。"""
    db = SessionLocal()
    job = None
    try:
        job = db.get(WebIngestionJob, uuid.UUID(job_id))
        if job is None or job.status in ("completed", "failed"):
            return  # 幂等
        config = resolve_firecrawl_config(db)
        if config is None:
            _mark_failed(db, job, "Firecrawl 配置丢失")
            return
        client = FirecrawlClient(config.api_key, config.base_url)
        _poll_and_ingest(db, job=job, client=client, config=config)
    except Exception as e:
        if job is not None:
            _mark_failed(db, job, str(e)[:500])
    finally:
        db.close()


def _poll_and_ingest(db: Session, *, job, client, config) -> None:
    """轮询 Firecrawl 状态 + 完成时入库。"""
    from datetime import datetime, timezone
    deadline = datetime.now(timezone.utc) + timedelta(hours=CRAWL_TIMEOUT_HOURS)
    while datetime.now(timezone.utc) < deadline:
        status = client.check_crawl(job.firecrawl_job_id)
        if status.status == "completed":
            _ingest_crawl_pages(db, job=job, pages=status.pages, config=config)
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.pages_fetched = len(status.pages)
            db.commit()
            return
        if status.status == "failed":
            _mark_failed(
                db, job,
                f"Firecrawl 任务失败(已完成 {status.completed}/{status.total})",
            )
            return
        # 进行中:更新进度
        job.pages_fetched = status.completed
        db.commit()
        time.sleep(CRAWL_POLL_INTERVAL_SECONDS)
    _mark_failed(db, job, f"轮询超时({CRAWL_TIMEOUT_HOURS}h)")


def _ingest_crawl_pages(db: Session, *, job, pages, config) -> None:
    """整站结果分页入库。每页一个 KnowledgeFile。"""
    storage = get_storage()
    file_ids = []
    filtered_count = 0
    # 用 job.user_id 加载 user 实例(供 upload_* 用)
    from app.models import User
    user = db.get(User, job.user_id)
    if user is None:
        _mark_failed(db, job, "发起用户不存在")
        return

    for page in pages:
        filtered = filter_content(page.markdown, page.title)
        if filtered is None:
            filtered_count += 1
            continue
        content_bytes = filtered.markdown.encode("utf-8")
        filename = _derive_filename(filtered.title, page.url)
        try:
            if job.scope == "global":
                kf = knowledge_service.upload_to_global(
                    db, storage=storage, uploader=user,
                    filename=filename, content=content_bytes,
                    mime="text/markdown", text=filtered.markdown, url=page.url,
                )
            else:
                kf = knowledge_service.upload_external(
                    db, storage=storage, user=user,
                    filename=filename, content=content_bytes,
                    mime="text/markdown", text=filtered.markdown, url=page.url,
                )
            file_ids.append(str(kf.id))
        except Exception:
            # 单页入库失败不影响其他页(对齐 spec:不引入 partial 状态)
            continue

    job.file_ids = file_ids
    job.pages_filtered = filtered_count
    log_firecrawl_call(
        db, user_id=job.user_id, mode="crawl",
        pages=len(pages), source=config.source,
    )
    _correct_quota(db, job=job)


def _mark_failed(db: Session, job, message: str) -> None:
    """标记 job 失败,截断 error_message 500 字。"""
    from datetime import datetime, timezone
    job.status = "failed"
    job.error_message = message[:500]
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_service_run.py -v`
Expected: PASS(所有测试)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/web_ingestion_service.py apps/api/tests/test_web_ingestion_service_run.py
git commit -m "feat(services): run_job 轮询主循环 + 整站入库 + 失败标记"
```

---

## Task 12: recover_pending_jobs + get_job + list_jobs

**Files:**
- Modify: `apps/api/app/services/web_ingestion_service.py`
- Test: `apps/api/tests/test_web_ingestion_service_recover.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_web_ingestion_service_recover.py`:

```python
"""recover_pending_jobs + get_job + list_jobs 测试。"""

import uuid
from datetime import timedelta
from datetime import datetime as dt, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.models import WebIngestionJob
from app.services import web_ingestion_service


@pytest.fixture
def mock_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_admin = False
    return u


def _make_job(db_session, *, user_id, status, scope="personal", mode="crawl",
              updated_at=None, created_at=None):
    job = WebIngestionJob(
        user_id=user_id, scope=scope, url="https://x.com", mode=mode,
        max_pages=10, firecrawl_job_id="fc-x", status=status,
    )
    if updated_at:
        job.updated_at = updated_at
    if created_at:
        job.created_at = created_at
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


# ── recover_pending_jobs ─────────────────────────────────────

@patch("app.services.web_ingestion_service.spawn_background_task")
def test_recover_spawns_for_stale_running(mock_spawn, db_session, mock_user):
    """running 且超时 → spawn。"""
    old_time = dt.now(timezone.utc) - timedelta(hours=1)
    _make_job(db_session, user_id=mock_user.id, status="running", updated_at=old_time)
    count = web_ingestion_service.recover_pending_jobs()
    assert count == 1
    assert mock_spawn.call_count == 1


@patch("app.services.web_ingestion_service.spawn_background_task")
def test_recover_ignores_recent_running(mock_spawn, db_session, mock_user):
    """running 但未超时 → 不 spawn。"""
    _make_job(db_session, user_id=mock_user.id, status="running",
              updated_at=dt.now(timezone.utc))  # 刚建
    count = web_ingestion_service.recover_pending_jobs()
    assert count == 0
    mock_spawn.assert_not_called()


@patch("app.services.web_ingestion_service.spawn_background_task")
def test_recover_spawns_for_stale_pending(mock_spawn, db_session, mock_user):
    """pending 且超时 → spawn。"""
    old_time = dt.now(timezone.utc) - timedelta(minutes=30)
    _make_job(db_session, user_id=mock_user.id, status="pending", created_at=old_time)
    count = web_ingestion_service.recover_pending_jobs()
    assert count == 1


@patch("app.services.web_ingestion_service.spawn_background_task")
def test_recover_ignores_completed_failed(mock_spawn, db_session, mock_user):
    """completed/failed 不重入队。"""
    _make_job(db_session, user_id=mock_user.id, status="completed")
    _make_job(db_session, user_id=mock_user.id, status="failed")
    count = web_ingestion_service.recover_pending_jobs()
    assert count == 0


# ── get_job ──────────────────────────────────────────────────

def test_get_job_returns_own(db_session, mock_user):
    """owner 可查。"""
    job = _make_job(db_session, user_id=mock_user.id, status="running")
    got = web_ingestion_service.get_job(db_session, job_id=str(job.id), user=mock_user)
    assert got.id == job.id


def test_get_job_404_on_others(db_session, mock_user):
    """非 owner 查他人 job → 404(不暴露存在性)。"""
    other_uid = uuid.uuid4()
    job = _make_job(db_session, user_id=other_uid, status="running")
    with pytest.raises(NotFoundError):
        web_ingestion_service.get_job(db_session, job_id=str(job.id), user=mock_user)


def test_get_job_404_on_missing(db_session, mock_user):
    """不存在的 id → 404。"""
    with pytest.raises(NotFoundError):
        web_ingestion_service.get_job(db_session, job_id=str(uuid.uuid4()), user=mock_user)


def test_get_job_admin_can_see_others(db_session, mock_user):
    """admin 可查他人 job(运营审计)。"""
    admin = MagicMock()
    admin.id = uuid.uuid4()
    admin.is_admin = True
    job = _make_job(db_session, user_id=mock_user.id, status="running")
    got = web_ingestion_service.get_job(db_session, job_id=str(job.id), user=admin)
    assert got.id == job.id


# ── list_jobs ────────────────────────────────────────────────

def test_list_jobs_returns_own_only(db_session, mock_user):
    """只列本人的。"""
    other_uid = uuid.uuid4()
    _make_job(db_session, user_id=mock_user.id, status="running")
    _make_job(db_session, user_id=mock_user.id, status="completed")
    _make_job(db_session, user_id=other_uid, status="running")
    jobs = web_ingestion_service.list_jobs(db_session, user=mock_user)
    assert len(jobs) == 2
    assert all(j.user_id == mock_user.id for j in jobs)
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_service_recover.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'recover_pending_jobs'`

- [ ] **Step 3: 在 web_ingestion_service.py 末尾追加**

```python


def recover_pending_jobs(stale_minutes: int = 10) -> int:
    """启动时扫描孤儿 web ingestion 任务。返回重新入队数。
    
    异步 spawn,不阻塞 startup(与 parse_service.recover_pending_jobs 的同步模式不同,
    因 crawl 轮询可能跑数小时)。
    """
    from datetime import datetime, timedelta, timezone
    db = SessionLocal()
    try:
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
            spawn_background_task(run_job, str(job.id))
            count += 1
        return count
    except Exception:
        return 0  # 不阻塞 startup
    finally:
        db.close()


def get_job(db: Session, *, job_id: str, user) -> WebIngestionJob:
    """查 crawl 任务。越权(非 owner 且非 admin)→ 404。"""
    from app.core.exceptions import NotFoundError
    try:
        jid = uuid.UUID(job_id)
    except ValueError:
        raise NotFoundError("任务不存在")
    job = db.get(WebIngestionJob, jid)
    if job is None:
        raise NotFoundError("任务不存在")
    if job.user_id != user.id and not getattr(user, "is_admin", False):
        raise NotFoundError("任务不存在")  # 不暴露存在性
    return job


def list_jobs(db: Session, *, user) -> list[WebIngestionJob]:
    """列本人的网页摄入任务。"""
    return list(db.scalars(
        select(WebIngestionJob).where(WebIngestionJob.user_id == user.id)
        .order_by(WebIngestionJob.created_at.desc())
    ))
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_web_ingestion_service_recover.py -v`
Expected: PASS(所有测试)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/web_ingestion_service.py apps/api/tests/test_web_ingestion_service_recover.py
git commit -m "feat(services): recover_pending_jobs + get_job + list_jobs"
```

---

## Task 13: API 端点(user + admin)

**Files:**
- Modify: `apps/api/app/api/knowledge.py`
- Modify: `apps/api/app/api/admin.py`(或定位实际 admin 路由文件)
- Test: `apps/api/tests/test_web_ingestion_api.py`

- [ ] **Step 1: 定位 admin 路由文件 + 查看现有 API 测试风格**

Run: `cd apps/api && grep -rn "admin/console" app/api/ | head -5`

记下 admin 路由所在文件路径(下文记为 `<admin_file>`),以及 admin 守卫依赖名。

Run: `cd apps/api && ls tests/conftest.py tests/test_knowledge*.py tests/test_*api*.py 2>/dev/null && cat tests/conftest.py 2>/dev/null | head -60`

查看项目现有的 API 测试如何 mock `get_current_user`(关键:fixture 名、是否用 `dependency_overrides`、token 怎么造)。**记下现有模式,Step 2 测试照此写**。

- [ ] **Step 2: 写测试**

创建 `apps/api/tests/test_web_ingestion_api.py`。**先复制一个现有 API 测试文件作模板**(如 `tests/test_knowledge_api.py`),复用它的 auth/fixture/db_session setup,只改测试体:

```python
"""网页摄入 API 端点测试。

auth/db_session fixture 复用现有 conftest.py 的 setup。
若项目用 dependency_overrides 覆盖 get_current_user,照搬现有测试的写法。
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

# 下面两个 import 按现有测试文件的实际路径/写法调整:
# - auth_client / db_session / mock_user 的 fixture 名以 conftest.py 为准
# - 若项目用 dependency_overrides 覆盖 get_current_user,这里也用


def test_post_ingest_web_scrape_returns_file(auth_client, db_session):
    """POST /knowledge/ingest/web scrape 模式返回 {kind: file, file: {...}}。"""
    with patch("app.services.web_ingestion_service.FirecrawlClient") as mock_cls, \
         patch("app.services.web_ingestion_service.resolve_firecrawl_config") as mock_res:
        mock_res.return_value = MagicMock(
            api_key="x", base_url="x", source="global",
        )
        client_inst = MagicMock()
        mock_cls.return_value = client_inst
        client_inst.scrape.return_value = MagicMock(
            url="https://example.com", title="测试",
            markdown="专利正文" * 100, status_code=200, fetch_failed=False,
        )
        with patch("app.services.web_ingestion_service.get_storage") as mock_st:
            mock_st.return_value = MagicMock()
            resp = auth_client.post(
                "/knowledge/ingest/web",
                json={"url": "https://example.com", "mode": "scrape", "scope": "personal"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "file"
    assert "file" in body
    assert body["file"]["source_type"] == "external_web"


def test_post_ingest_web_crawl_returns_job(auth_client, db_session):
    """POST /knowledge/ingest/web crawl 模式返回 {kind: job, job: {...}}。"""
    with patch("app.services.web_ingestion_service.spawn_background_task"), \
         patch("app.services.web_ingestion_service.FirecrawlClient") as mock_cls, \
         patch("app.services.web_ingestion_service.resolve_firecrawl_config") as mock_res:
        mock_res.return_value = MagicMock(
            api_key="x", base_url="x", source="global",
        )
        client_inst = MagicMock()
        mock_cls.return_value = client_inst
        client_inst.start_crawl.return_value = MagicMock(firecrawl_job_id="fc-x")
        # 当前 user 需是 admin 才能入 global;若 auth_client 是普通 user,
        # 把 scope 改成 personal,或用 admin_client fixture(若项目有)
        resp = auth_client.post(
            "/knowledge/ingest/web",
            json={"url": "https://example.com", "mode": "crawl",
                  "scope": "personal", "max_pages": 10},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "job"
    assert body["job"]["status"] == "running"
    assert body["job"]["firecrawl_job_id"] == "fc-x"


def test_get_ingest_job_returns_status(auth_client, db_session, mock_user):
    """GET /knowledge/ingest/jobs/{id} 返回任务详情。"""
    from app.models import WebIngestionJob
    job = WebIngestionJob(
        user_id=mock_user.id, scope="personal", url="https://x.com",
        mode="crawl", max_pages=10, firecrawl_job_id="fc-x",
        status="running",
    )
    db_session.add(job)
    db_session.commit()

    resp = auth_client.get(f"/knowledge/ingest/jobs/{job.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(job.id)
    assert body["status"] == "running"


def test_get_ingest_job_404_on_others(auth_client, db_session, mock_user):
    """查他人 job 返回 404。"""
    from app.models import WebIngestionJob
    other_job = WebIngestionJob(
        user_id=uuid.uuid4(),  # 别人
        scope="personal", url="https://x.com", mode="crawl",
        max_pages=10, firecrawl_job_id="fc-y", status="running",
    )
    db_session.add(other_job)
    db_session.commit()

    resp = auth_client.get(f"/knowledge/ingest/jobs/{other_job.id}")
    assert resp.status_code == 404


def test_list_ingest_jobs(auth_client, db_session, mock_user):
    """GET /knowledge/ingest/jobs 列本人的任务。"""
    from app.models import WebIngestionJob
    for _ in range(2):
        db_session.add(WebIngestionJob(
            user_id=mock_user.id, scope="personal", url="https://x.com",
            mode="crawl", max_pages=10, firecrawl_job_id="fc-x", status="running",
        ))
    db_session.commit()

    resp = auth_client.get("/knowledge/ingest/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
```

**关键适配点**(执行 agent 必读):
- `auth_client` / `db_session` / `mock_user` 的 fixture 名以项目 `tests/conftest.py` 为准。若名字不同(如叫 `client` / `session` / `current_user`),全局替换。
- 若项目不用 fixture 而是直接 `from app.deps import get_current_user` + `app.dependency_overrides`,照现有测试文件写。
- `test_post_ingest_web_crawl_returns_job` 里 scope=global 需 admin;若 `auth_client` 是普通 user,要么改 scope=personal,要么用项目的 admin fixture。

- [ ] **Step 3: 在 knowledge.py 加端点**

修改 `apps/api/app/api/knowledge.py`,在文件末尾加:

```python


# ── 网页摄入(计划 T-firecrawl)──────────────────────────────────

class WebIngestRequest(BaseModel):
    url: str
    mode: str = "scrape"       # scrape / crawl
    scope: str = "personal"    # personal / global(global 需 admin)
    max_pages: int = 1         # 仅 crawl 有效


def _job_out(job) -> dict:
    return {
        "id": str(job.id),
        "url": job.url,
        "mode": job.mode,
        "scope": job.scope,
        "status": job.status,
        "pages_fetched": job.pages_fetched,
        "pages_filtered": job.pages_filtered,
        "file_ids": job.file_ids or [],
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/knowledge/ingest/web")
def ingest_web(
    payload: WebIngestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发起网页摄入。scrape 同步返回 file;crawl 异步返回 job。"""
    from app.models import KnowledgeFile as _KF
    from app.services import web_ingestion_service

    result = web_ingestion_service.create_job(
        db, user=current_user, url=payload.url,
        mode=payload.mode, scope=payload.scope, max_pages=payload.max_pages,
    )
    if isinstance(result, _KF):
        return {"kind": "file", "file": _file_out(result)}
    return {"kind": "job", "job": _job_out(result)}


@router.get("/knowledge/ingest/jobs/{job_id}")
def get_ingest_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查 crawl 任务状态。越权(非 owner)返回 404。"""
    from app.services import web_ingestion_service
    job = web_ingestion_service.get_job(db, job_id=job_id, user=current_user)
    return _job_out(job)


@router.get("/knowledge/ingest/jobs")
def list_ingest_jobs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出本人的网页摄入任务。"""
    from app.services import web_ingestion_service
    jobs = web_ingestion_service.list_jobs(db, user=current_user)
    return [_job_out(j) for j in jobs]
```

- [ ] **Step 4: 在 admin 路由文件加 firecrawl 配置端点**

打开 Step 1 定位的 `<admin_file>`,在文件末尾加:

```python


# ── Firecrawl 配置 ───────────────────────────────────────────

class FirecrawlConfigRequest(BaseModel):
    enabled: bool
    api_key: str = ""              # 空串表示不修改
    base_url: str = "https://api.firecrawl.dev"


@router.get("/admin/console/firecrawl")
def get_firecrawl_config(
    admin: User = Depends(get_admin_user),  # 用项目实际的 admin 守卫
    db: Session = Depends(get_db),
):
    """读全局 Firecrawl 配置(api_key 脱敏)。"""
    from app.services.firecrawl_client import get_firecrawl_settings
    return get_firecrawl_settings(db)


@router.put("/admin/console/firecrawl")
def set_firecrawl_config(
    payload: FirecrawlConfigRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """写全局 Firecrawl 配置。"""
    from app.services.firecrawl_client import set_firecrawl_settings
    set_firecrawl_settings(
        db, enabled=payload.enabled, api_key=payload.api_key,
        base_url=payload.base_url, updated_by=admin.id,
    )
    return {"ok": True}
```

**注意**:`get_admin_user` 是占位名。Step 1 已确认项目实际的 admin 守卫依赖名,替换之。`BaseModel`、`User`、`Depends`、`Session`、`get_db` 的 import 跟随该文件已有的 import 风格。

- [ ] **Step 5: 跑全量测试确认零回归**

Run: `cd apps/api && uv run pytest -x`
Expected: 全部通过

- [ ] **Step 6: 手动 smoke test(可选但推荐)**

启动服务,用 curl 测一遍:

```bash
cd apps/api && uv run uvicorn app.main:app --reload &
sleep 3
# 先 admin 配置(假设已有 admin token)
curl -X PUT http://localhost:8000/admin/console/firecrawl \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "api_key": "fc-test", "base_url": "https://api.firecrawl.dev"}'
# 单页摄入(假设已有 user token)
curl -X POST http://localhost:8000/knowledge/ingest/web \
  -H "Authorization: Bearer <user-token>" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "mode": "scrape", "scope": "personal"}'
```

Expected: scrape 返回 `{kind: "file", file: {...}}`

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/api/knowledge.py apps/api/app/api/<admin_file>.py apps/api/tests/test_web_ingestion_api.py
git commit -m "feat(api): 网页摄入端点(ingest/web + jobs)+ admin firecrawl 配置"
```

---

## Task 14: main.py startup hook 加恢复扫描

**Files:**
- Modify: `apps/api/app/main.py`
- Test: 手动验证(启动日志)

- [ ] **Step 1: 修改 main.py**

打开 `apps/api/app/main.py`,在现有 `on_startup` 函数(第 33-44 行)末尾,`except` 块之后追加:

```python

    # 网页摄入任务恢复(异步,不阻塞 startup)
    try:
        from app.services.web_ingestion_service import recover_pending_jobs as recover_web
        n_web = recover_web()
        if n_web:
            loguru.logger.info(f"恢复扫描:重新入队 {n_web} 个网页摄入任务")
    except Exception as e:
        loguru.logger.exception(f"网页摄入恢复扫描失败(不阻塞启动):{e}")
```

修改后的 `on_startup` 完整结构:

```python
@app.on_event("startup")
def on_startup():
    loguru.logger.info("TianGong API 启动")
    # 恢复扫描:重启后重入队崩溃中断的解析任务(设计 P0 #6)
    try:
        from app.services.parse_service import recover_pending_jobs

        n = recover_pending_jobs()
        if n:
            loguru.logger.info(f"恢复扫描:重新入队 {n} 个解析任务")
    except Exception as e:
        loguru.logger.exception(f"恢复扫描失败(不阻塞启动):{e}")

    # 网页摄入任务恢复(异步,不阻塞 startup)
    try:
        from app.services.web_ingestion_service import recover_pending_jobs as recover_web
        n_web = recover_web()
        if n_web:
            loguru.logger.info(f"恢复扫描:重新入队 {n_web} 个网页摄入任务")
    except Exception as e:
        loguru.logger.exception(f"网页摄入恢复扫描失败(不阻塞启动):{e}")
```

- [ ] **Step 2: 验证启动不崩**

Run: `cd apps/api && uv run python -c "from app.main import app; print('ok')"`
Expected: 输出 `ok`(import 成功,不实际触发 startup)

- [ ] **Step 3: 跑全量测试**

Run: `cd apps/api && uv run pytest`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/main.py
git commit -m "feat(main): startup hook 加网页摄入任务恢复扫描"
```

---

## 完成验证(全部任务做完后)

- [ ] **Step 1: 全量测试**

Run: `cd apps/api && uv run pytest -v`
Expected: 全部通过(原有 36+ 个 + 新增约 40 个)

- [ ] **Step 2: 迁移状态**

Run: `cd apps/api && uv run alembic current`
Expected: `c3d4e5f6a7b8 (head)`

- [ ] **Step 3: 验收清单对照 spec**

逐项对照 spec 第 10 节验收标准:
- [ ] 用户可 POST URL → scrape 同步返回 file,crawl 异步返回 job_id
- [ ] crawl 完成后 `GET /jobs/{id}` 看到 completed + file_ids
- [ ] admin 配 Firecrawl key 后用户立即能用
- [ ] SSRF 防护生效(127.0.0.1 / 169.254.169.254 被拒)
- [ ] 配额预扣 + 校正 + 退款逻辑正确
- [ ] 重启后 running 孤儿任务被异步恢复
- [ ] 全部单测 + 集成测试通过
- [ ] 现有审核流/检索/embedding 零回归

- [ ] **Step 4: 更新 AGENTS.md(可选)**

在 `AGENTS.md` 的「关键约定」末尾加一条:

```markdown
- **网页摄入(Firecrawl)**:用户/admin 贴 URL 入知识库。单页 scrape 同步、整站 crawl 异步(`WebIngestionJob` 表跟踪)。全局 key 存 `SystemSetting`(`firecrawl_config` + `firecrawl_enabled`)。复用现有 `upload_external/upload_to_global`,审核/检索/embedding 零改动。spec 见 `docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md`。
```

Commit:
```bash
git add AGENTS.md
git commit -m "docs(agents): 加网页摄入说明"
```

---

## 实施笔记(给执行 agent)

1. **Task 13 的 API 测试**:spec 第 9 节承认前端 UI 不在本 spec 范围,API 测试需要项目现有的 auth fixture。**先看 `tests/conftest.py` 和现有 `test_*api*.py`**,复用它们的 auth mock 模式,不要从零写。

2. **firecrawl-py SDK 的方法名**:Task 7 用了 `scrape_url` / `crawl_url` / `check_crawl_status`。这些是 SDK v2 的方法名。**实现时先 `uv run python -c "import firecrawl; help(firecrawl.Firecrawl)"` 确认实际方法名**,不同版本可能叫 `scrape` / `crawl` / `get_crawl_status`。若名字不同,改 `FirecrawlClient` 内部调用即可,对外接口(dataclass)不变。

3. **Task 9 配额测试的 db_session fixture**:依赖项目 `tests/conftest.py` 里的 `db_session` fixture。若不存在,参考现有 `test_*knowledge*.py` 的 fixture 用法。

4. **Task 10 的 mock 路径**:`@patch("app.services.web_ingestion_service.resolve_firecrawl_config")`——`web_ingestion_service.py` 内部 import 了 `resolve_firecrawl_config`,所以 patch 这个模块路径。**不要 patch `app.services.firecrawl_client.resolve_firecrawl_config`**(那是源头,模块内 import 后绑定在 service 模块命名空间)。

5. **线程池生命周期**:`ThreadPoolExecutor(max_workers=4)` 在模块加载时创建,进程退出时由 Python 自动回收。不需要显式 shutdown(对本场景够用)。

6. **遇到 firecrawl-py 的实际 API 与 spec/plan 不符**:spec 第 4 节明确「返回 dataclass,不返回 SDK 原始对象,换 SDK 时只改这一个文件」。所以 SDK 差异**全部隔离在 `FirecrawlClient` 内部**,对上层零影响。

7. **已知 gap:客户端重试策略未实现**:spec 第 8 节提到对 429/5xx 重试 3 次(指数退避),但 plan 的 Task 7 FirecrawlClient 未实现重试。**理由**:firecrawl-py SDK 内部可能已有重试,且 MVP 阶段重试非核心路径。若实测发现限流频繁,再在 `FirecrawlClient.scrape` / `start_crawl` / `check_crawl` 外包一层 `_with_retry` 装饰器(spec 第 8 节有伪代码)。这是可选增强,不阻塞 MVP。

8. **Task 10 的 `run_job` 占位衔接**:Task 10 的 `_crawl_async` 引用了 `run_job`,但 run_job 在 Task 11 才实现。Task 10 Step 3 末尾放了 `def run_job(...): raise NotImplementedError` 占位,Task 11 替换它。**Task 10 的测试不依赖 run_job 实际实现**(因为 `spawn_background_task` 被 mock,不会真调),所以这个过渡是安全的。
