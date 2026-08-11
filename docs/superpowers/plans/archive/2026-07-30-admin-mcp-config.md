# Admin MCP 配置页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 admin 控制台新增「MCP 配置页」，支持 stdio/http/sse 三种传输的全局 server CRUD + 测试连接，并在 agent 生成时把这些 server 暴露的工具加载进 agent 工具列表。

**Architecture:** 新建独立 `mcp_servers` 表（逐值加密 headers/env）+ `SystemSetting` 全局开关；后端仿 `skills.py`(CRUD) + `console.py`(测试连接) 模式；AI 接入在 `tools.py` 新增 `load_mcp_tools`，并把 `create_agent_tools`/`build_agent` 异步化（调用方 `astream_*` 已是 async）；前端仿 MinerU 配置页 + skills 列表 CRUD。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic；`langchain-mcp-adapters`（`MultiServerMCPClient`）；Next.js + React Query + shadcn/ui 3.x（手写新组件，CLI 坏）。

**Spec:** `docs/superpowers/specs/2026-07-30-admin-mcp-config-design.md`

---

## File Structure

**后端新建：**
- `apps/api/app/models/mcp_server.py` — `McpServer` ORM 模型
- `apps/api/app/schemas/mcp.py` — `McpServerBase/Create/Update/Out` + `McpGlobalEnabled` + `McpTestResult`
- `apps/api/app/services/mcp_config_service.py` — CRUD + 全局开关 + `resolve_mcp_servers`(解密) + `test_mcp_server`
- `apps/api/app/api/admin/mcp.py` — 8 个 admin 路由
- `apps/api/alembic/versions/<hash>_create_mcp_servers.py` — 迁移（autogenerate）
- `apps/api/tests/test_admin_mcp_api.py` — 后端测试

**后端修改：**
- `apps/api/app/models/__init__.py` — 注册 `McpServer`
- `apps/api/app/api/admin/__init__.py` — include `mcp.router`
- `apps/api/app/ai/tools.py` — `create_agent_tools` 改 async + 新增 `load_mcp_tools`
- `apps/api/app/ai/agent.py` — `build_agent` 改 async + `await create_agent_tools(...)`
- `apps/api/app/ai/orchestrator.py` — 两处 `build_agent(...)` 加 `await`
- `apps/api/pyproject.toml` — 加 `langchain-mcp-adapters`

**前端新建：**
- `apps/web/src/app/(app)/admin/console/mcp/page.tsx` — 配置页（全局开关 + server 表格 + 表单 Dialog）

**前端修改：**
- `apps/web/src/lib/api.ts` — 加 `mcp` 方法组
- `apps/web/src/lib/queries.ts` — 加 `queryKeys.admin.mcpConfig` + 7 个 hooks
- `apps/web/src/types/api.ts` — 加 `McpServer` / `McpTestResult` 等类型
- `apps/web/src/app/(app)/admin/console/page.tsx` — `CONSOLE_SECTIONS` 加一张 MCP 卡片

---

## Task 1: 添加依赖 + 数据模型

**Files:**
- Modify: `apps/api/pyproject.toml`
- Create: `apps/api/app/models/mcp_server.py`
- Modify: `apps/api/app/models/__init__.py`

- [ ] **Step 1: 添加 `langchain-mcp-adapters` 依赖**

编辑 `apps/api/pyproject.toml`，在 `[project] dependencies` 数组里（与其它 langchain 包同组）加一行：

```toml
    "langchain-mcp-adapters>=0.1.0",
```

- [ ] **Step 2: 装依赖**

Run: `cd apps/api && uv sync`
Expected: 成功装上 `langchain-mcp-adapters`（及其依赖 `mcp`）。无报错。

- [ ] **Step 3: 创建 `McpServer` 模型**

Create `apps/api/app/models/mcp_server.py`：

```python
# apps/api/app/models/mcp_server.py
"""MCP (Model Context Protocol) server 配置模型（全局作用域）。

admin 配置一组 MCP server（stdio/http/sse），agent 生成时把已启用 server 暴露的
工具加载进 agent 工具列表。凭据（headers/env）逐值加密存储。
详见 spec docs/superpowers/specs/2026-07-30-admin-mcp-config-design.md §2。
"""
import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin

TRANSPORT_STDIO = "stdio"
TRANSPORT_HTTP = "http"
TRANSPORT_SSE = "sse"


class McpServer(Base, IdMixin, TimestampMixin):
    """一条 MCP server 配置。

    - transport 决定使用哪组字段：stdio 用 command+args+env；http/sse 用 url+headers。
    - headers_encrypted / env_encrypted：dict，每个 value 已 encrypt_value。
      API 响应只回 {key: {has_value: true}}，绝不回明文（masking）。
    - enabled=false 的 server 不会被 agent 加载，也不进 resolve_mcp_servers。
    """
    __tablename__ = "mcp_servers"
    __table_args__ = (
        Index("ix_mcp_servers_name", "name", unique=True),
    )

    name: Mapped[str] = mapped_column(String(100))
    transport: Mapped[str] = mapped_column(String(20))  # stdio / http / sse
    command: Mapped[str | None] = mapped_column(String(255), nullable=True)
    args: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    headers_encrypted: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    env_encrypted: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
```

- [ ] **Step 4: 注册模型到 `__init__.py`**

在 `apps/api/app/models/__init__.py`：
- 在 import 区（`from app.models.llm_call_log import LLMCallLog` 之后，按字母序）加：
  ```python
  from app.models.mcp_server import McpServer
  ```
- 在 `__all__` 列表里加 `"McpServer",`（加在 `"LLMCallLog",` 之后）。

- [ ] **Step 5: 提交**

```bash
git add apps/api/pyproject.toml apps/api/uv.lock apps/api/app/models/mcp_server.py apps/api/app/models/__init__.py
git commit -m "feat(mcp): McpServer 模型 + langchain-mcp-adapters 依赖"
```

---

## Task 2: Alembic 迁移（创建 mcp_servers 表）

**Files:**
- Create: `apps/api/alembic/versions/<hash>_create_mcp_servers.py`

- [ ] **Step 1: 生成迁移**

Run: `cd apps/api && uv run alembic revision --autogenerate -m "create mcp_servers"`
Expected: 在 `apps/api/alembic/versions/` 生成新迁移文件。

- [ ] **Step 2: 校验迁移内容**

打开生成的迁移文件，确认 `down_revision = '9a3f7c2e1b4d'`（当前 head —— 分支已合并 main，含 is_builtin 迁移），且 `upgrade()` 包含创建 `mcp_servers` 表（含所有字段 + `ix_mcp_servers_name` unique index）。JSON 列应为 `sa.JSON()` 或 `postgresql.JSONB()`。

若 autogenerate 把 `args`/`headers_encrypted`/`env_encrypted` 列生成成了普通 `sa.JSON()`，需手动改成双库兼容形式：

```python
import sqlalchemy as sa
# JSON 列：PG 用 JSONB，sqlite 用 JSON（GOTCHAS G2）
json_col = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")
```

把这三列的 `sa.Column(...)` 替换为用 `json_col`。`enabled` 列确保 `server_default=sa.text("1")`（避免 NOT NULL 无默认）。

- [ ] **Step 3: 跑迁移**

Run: `cd apps/api && uv run alembic upgrade head`
Expected: 输出 `Running upgrade 9a3f7c2e1b4d -> <hash>, create mcp_servers`，无报错。

- [ ] **Step 4: 提交**

```bash
git add apps/api/alembic/versions/
git commit -m "feat(mcp): 迁移 create mcp_servers 表"
```

---

## Task 3: Schemas

**Files:**
- Create: `apps/api/app/schemas/mcp.py`
- Test: `apps/api/tests/test_mcp_schemas.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_mcp_schemas.py`：

```python
# apps/api/tests/test_mcp_schemas.py
"""McpServer schemas 单元测试（masking + transport 校验 + partial update）。"""
import pytest

from app.schemas.mcp import (
    McpGlobalEnabled, McpServerCreate, McpServerOut, McpServerUpdate, McpTestResult,
)


def test_create_stdio_ok():
    s = McpServerCreate(name="fs", transport="stdio", command="npx", args=["-y", "x"])
    assert s.transport == "stdio"
    assert s.enabled is True  # 默认


def test_create_rejects_bad_transport():
    with pytest.raises(Exception):
        McpServerCreate(name="x", transport="websocket")  # type: ignore[arg-type]


def test_update_all_optional():
    u = McpServerUpdate()
    assert u.name is None
    assert u.enabled is None


def test_test_result_shape():
    r = McpTestResult(ok=True, tool_count=2, tool_names=["a", "b"], error=None)
    assert r.ok is True and r.tool_count == 2


def test_global_enabled():
    assert McpGlobalEnabled(enabled=True).enabled is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_mcp_schemas.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.schemas.mcp'`）。

- [ ] **Step 3: 实现 schemas**

Create `apps/api/app/schemas/mcp.py`：

```python
# apps/api/app/schemas/mcp.py
"""MCP server schemas（CRUD + 全局开关 + 测试结果）。

凭据 masking：API 响应中 headers/env 形如 {key: {has_value: bool}}，绝不回明文。
"""
from pydantic import BaseModel, Field


class McpServerBase(BaseModel):
    name: str = Field(..., max_length=100, description="唯一标识")
    transport: str = Field(..., pattern="^(stdio|http|sse)$")
    command: str | None = Field(None, max_length=255, description="stdio 专用")
    args: list[str] | None = Field(None, description="stdio 专用，参数数组")
    url: str | None = Field(None, max_length=500, description="http/sse 专用")
    headers: dict[str, str] | None = Field(None, description="http/sse 凭据（明文，仅写）")
    env: dict[str, str] | None = Field(None, description="stdio 环境变量（明文，仅写）")
    enabled: bool = True


class McpServerCreate(McpServerBase):
    """创建 server。"""


class McpServerUpdate(BaseModel):
    """更新 server（全 Optional，partial）。空字段=不改。"""
    name: str | None = Field(None, max_length=100)
    transport: str | None = Field(None, pattern="^(stdio|http|sse)$")
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    env: dict[str, str] | None = None
    enabled: bool | None = None


class McpServerOut(BaseModel):
    """server 输出（列表 + 详情共用）。

    headers/env 返回 {key: {has_value: bool}} 形态（masking）。
    """
    model_config = {"from_attributes": True}

    id: str
    name: str
    transport: str
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, dict] | None = None
    env: dict[str, dict] | None = None
    enabled: bool
    created_at: str
    updated_at: str


class McpGlobalEnabled(BaseModel):
    enabled: bool


class McpTestResult(BaseModel):
    ok: bool
    tool_count: int
    tool_names: list[str]
    error: str | None = None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_mcp_schemas.py -v`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/schemas/mcp.py apps/api/tests/test_mcp_schemas.py
git commit -m "feat(mcp): schemas (CRUD + masking + test result)"
```

---

## Task 4: mcp_config_service（CRUD + 加密 + 全局开关）

**Files:**
- Create: `apps/api/app/services/mcp_config_service.py`
- Test: `apps/api/tests/test_mcp_config_service.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_mcp_config_service.py`：

```python
# apps/api/tests/test_mcp_config_service.py
"""mcp_config_service 测试：CRUD + 凭据加密 masking + 全局开关。"""


def test_create_then_read_masks_secrets(db_session):
    from app.services import mcp_config_service as svc

    s = svc.create_mcp_server(
        db_session, name="weather", transport="http", url="https://x/sse",
        headers={"Authorization": "Bearer secret123"},
    )
    # 落库：headers_encrypted 是加密后的 dict，不是明文
    assert s.headers_encrypted["Authorization"] != "Bearer secret123"

    out = svc.to_out(s)
    # 输出：只有 has_value，无明文
    assert out["headers"]["Authorization"] == {"has_value": True}


def test_update_blank_keeps_old_secret(db_session):
    from app.services import mcp_config_service as svc

    svc.create_mcp_server(
        db_session, name="fs", transport="stdio", command="npx",
        env={"API_KEY": "oldval"},
    )
    server_id = svc.list_mcp_servers(db_session)[0].id
    # 更新时所有可选字段传 None → env 保留旧值
    s = svc.update_mcp_server(db_session, server_id=server_id,
                              name="fs", transport="stdio", command="npx", args=None,
                              url=None, headers=None, env=None, enabled=True)
    # 旧 env 仍在
    assert s.env_encrypted is not None


def test_global_enabled_default_true(db_session):
    from app.services import mcp_config_service as svc

    assert svc.get_mcp_enabled(db_session) is True  # 未设置时默认开
    svc.set_mcp_enabled(db_session, enabled=False)
    assert svc.get_mcp_enabled(db_session) is False


def test_resolve_returns_plaintext(db_session):
    from app.services import mcp_config_service as svc

    svc.create_mcp_server(
        db_session, name="weather", transport="http", url="https://x/sse",
        headers={"Authorization": "Bearer secret123"}, enabled=True,
    )
    resolved = svc.resolve_mcp_servers(db_session)
    assert len(resolved) == 1
    assert resolved[0]["headers"]["Authorization"] == "Bearer secret123"  # 解密成明文
    assert resolved[0]["name"] == "weather"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_mcp_config_service.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.mcp_config_service'`）。

- [ ] **Step 3: 实现 service**

Create `apps/api/app/services/mcp_config_service.py`：

```python
# apps/api/app/services/mcp_config_service.py
"""MCP server 配置服务：CRUD + 凭据逐值加密 + 全局开关 + resolve(解密)。

仿 firecrawl_client / mineru_client 模式。service 拥有事务，失败 rollback。
凭据 masking：to_out 只回 {key: {has_value: bool}}；resolve 返回明文（仅内部用）。
"""
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import decrypt_value, encrypt_value
from app.models import SystemSetting
from app.models.mcp_server import McpServer

GLOBAL_ENABLED_KEY = "mcp_global_enabled"


# ── 凭据加密/解密工具 ──

def _encrypt_dict(d: dict[str, str] | None) -> dict[str, str] | None:
    """逐值加密。None/空 dict 返回 None。"""
    if not d:
        return None
    return {k: encrypt_value(v) for k, v in d.items()}


def _decrypt_dict(d: dict[str, str] | None) -> dict[str, str]:
    """逐值解密成明文。None → {}。"""
    if not d:
        return {}
    return {k: decrypt_value(v) for k, v in d.items()}


def _mask_dict(d: dict[str, str] | None) -> dict[str, dict] | None:
    """转 masking 形态：{key: {has_value: True}}。None → None。"""
    if not d:
        return None
    return {k: {"has_value": bool(v)} for k, v in d.items()}


def to_out(s: McpServer) -> dict[str, Any]:
    """ORM → 输出 dict（凭据 masking）。显式 str 转换，不依赖 from_attributes。"""
    return {
        "id": str(s.id),
        "name": s.name,
        "transport": s.transport,
        "command": s.command,
        "args": s.args,
        "url": s.url,
        "headers": _mask_dict(s.headers_encrypted),
        "env": _mask_dict(s.env_encrypted),
        "enabled": s.enabled,
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    }


# ── CRUD ──

def create_mcp_server(
    db: Session, *, name: str, transport: str,
    command: str | None = None, args: list[str] | None = None,
    url: str | None = None,
    headers: dict[str, str] | None = None, env: dict[str, str] | None = None,
    enabled: bool = True, actor=None,
) -> McpServer:
    """新建 server。name 唯一性校验。凭据逐值加密。"""
    existing = db.scalar(select(McpServer).where(McpServer.name == name))
    if existing:
        raise ConflictError(f"MCP server 名「{name}」已存在")

    server = McpServer(
        name=name, transport=transport, command=command, args=args, url=url,
        headers_encrypted=_encrypt_dict(headers), env_encrypted=_encrypt_dict(env),
        enabled=enabled, updated_by=actor.id if actor else None,
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    return server


def get_mcp_server(db: Session, *, server_id) -> McpServer:
    sid = uuid.UUID(str(server_id)) if isinstance(server_id, str) else server_id
    server = db.get(McpServer, sid)
    if server is None:
        raise NotFoundError("MCP server 不存在")
    return server


def update_mcp_server(
    db: Session, *, server_id, name: str | None = None,
    transport: str | None = None, command: str | None = None,
    args: list[str] | None = None, url: str | None = None,
    headers: dict[str, str] | None = None, env: dict[str, str] | None = None,
    enabled: bool | None = None, actor=None,
) -> McpServer:
    """更新 server。name 改了做唯一性校验。空字段=保留原值（凭据）。

    transport 变化时清空旧 transport 专属字段，避免脏数据残留（spec §3.2 note）。
    """
    server = get_mcp_server(db, server_id=server_id)

    if name is not None and name != server.name:
        existing = db.scalar(select(McpServer).where(McpServer.name == name))
        if existing:
            raise ConflictError(f"MCP server 名「{name}」已存在")
        server.name = name

    old_transport = server.transport
    new_transport = transport if transport is not None else old_transport
    transport_changed = new_transport != old_transport

    if transport is not None:
        server.transport = transport
    if command is not None:
        server.command = command
    if args is not None:
        server.args = args
    if url is not None:
        server.url = url
    if enabled is not None:
        server.enabled = enabled
    if actor is not None:
        server.updated_by = actor.id

    # 凭据：传了新值才覆盖，空/None 保留旧值
    if headers is not None:
        server.headers_encrypted = _encrypt_dict(headers)
    if env is not None:
        server.env_encrypted = _encrypt_dict(env)

    # transport 切换：清空旧专属字段（避免脏数据残留）
    if transport_changed:
        if new_transport == "stdio":
            server.url = None
            server.headers_encrypted = None
        else:  # http / sse
            server.command = None
            server.args = None
            server.env_encrypted = None

    db.commit()
    db.refresh(server)
    return server


def delete_mcp_server(db: Session, *, server_id) -> None:
    server = get_mcp_server(db, server_id=server_id)
    db.delete(server)
    db.commit()


def list_mcp_servers(db: Session) -> list[McpServer]:
    return list(db.scalars(select(McpServer).order_by(McpServer.created_at.desc())))


# ── 全局开关 ──

def get_mcp_enabled(db: Session) -> bool:
    """读全局开关。未设置时默认 True（与 llm_global_enabled 语义一致）。"""
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == GLOBAL_ENABLED_KEY))
    if row is None:
        return True
    return bool(row.value.get("enabled", True))


def set_mcp_enabled(db: Session, *, enabled: bool, actor=None) -> None:
    """写全局开关（upsert）。"""
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == GLOBAL_ENABLED_KEY))
    if row is None:
        row = SystemSetting(key=GLOBAL_ENABLED_KEY, value={"enabled": enabled},
                            updated_by=actor.id if actor else None)
        db.add(row)
    else:
        row.value = {"enabled": enabled}
        if actor is not None:
            row.updated_by = actor.id
    db.commit()


# ── resolve（解密，供 agent 加载与测试连接，绝不进 API 响应）──

def resolve_mcp_servers(db: Session) -> list[dict[str, Any]]:
    """返回已启用 server 的明文配置列表（headers/env 已解密）。

    全局开关关闭时返回空。仅内部使用，绝不进 API 响应。
    """
    if not get_mcp_enabled(db):
        return []
    rows = list(db.scalars(
        select(McpServer).where(McpServer.enabled.is_(True)).order_by(McpServer.created_at.desc())
    ))
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "transport": s.transport,
            "command": s.command,
            "args": s.args or [],
            "url": s.url,
            "headers": _decrypt_dict(s.headers_encrypted),
            "env": _decrypt_dict(s.env_encrypted),
        }
        for s in rows
    ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_mcp_config_service.py -v`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/services/mcp_config_service.py apps/api/tests/test_mcp_config_service.py
git commit -m "feat(mcp): mcp_config_service (CRUD + 凭据加密 + 全局开关 + resolve)"
```

---

## Task 5: test_mcp_server（测试连接）

**Files:**
- Modify: `apps/api/app/services/mcp_config_service.py`
- Test: `apps/api/tests/test_mcp_config_service.py`

- [ ] **Step 1: 写失败测试**

追加到 `apps/api/tests/test_mcp_config_service.py`：

```python
def test_test_mcp_server_success(db_session, monkeypatch):
    """测试连接成功：monkeypatch MultiServerMCPClient 返回假工具。"""
    from app.services import mcp_config_service as svc

    svc.create_mcp_server(
        db_session, name="weather", transport="http", url="https://x/sse",
        headers={"Authorization": "Bearer t"}, enabled=True,
    )
    server = svc.list_mcp_servers(db_session)[0]

    class _FakeTool:
        def __init__(self, n): self.name = n

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def get_tools(self): return [_FakeTool("search"), _FakeTool("fetch")]

    # 懒 import，patch 模块属性
    import app.services.mcp_config_service as mod
    monkeypatch.setattr(mod, "MultiServerMCPClient", _FakeClient)

    result = svc.test_mcp_server(db_session, server_id=server.id)
    assert result.ok is True
    assert result.tool_count == 2
    assert result.tool_names == ["search", "fetch"]
    assert result.error is None


def test_test_mcp_server_failure(db_session, monkeypatch):
    """测试连接失败：返回 ok=False + error，不抛异常。"""
    from app.services import mcp_config_service as svc

    svc.create_mcp_server(
        db_session, name="dead", transport="http", url="https://dead/sse", enabled=True,
    )
    server = svc.list_mcp_servers(db_session)[0]

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def get_tools(self): raise ConnectionError("refused")

    import app.services.mcp_config_service as mod
    monkeypatch.setattr(mod, "MultiServerMCPClient", _FakeClient)

    result = svc.test_mcp_server(db_session, server_id=server.id)
    assert result.ok is False
    assert result.error is not None
    assert "refused" in result.error
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_mcp_config_service.py -v`
Expected: 两个新 test FAIL（`test_mcp_server` 不存在）。

- [ ] **Step 3: 实现 `test_mcp_server` + 顶层 import**

在 `apps/api/app/services/mcp_config_service.py` 顶部 import 区加（在其它 import 之后）：

```python
import asyncio
import logging

from langchain_mcp_adapters.client import MultiServerMCPClient

from app.schemas.mcp import McpTestResult

logger = logging.getLogger(__name__)
```

在文件末尾追加：

```python
def _to_connection(server_cfg: dict[str, Any]) -> dict[str, Any]:
    """resolve 出的 server 配置 → MultiServerMCPClient 的 connection dict。"""
    transport = server_cfg["transport"]
    if transport == "stdio":
        conn: dict[str, Any] = {
            "transport": "stdio",
            "command": server_cfg["command"],
            "args": server_cfg["args"] or [],
        }
        if server_cfg["env"]:
            conn["env"] = server_cfg["env"]
        return conn
    # http / sse
    conn = {"transport": transport, "url": server_cfg["url"]}
    if server_cfg["headers"]:
        conn["headers"] = server_cfg["headers"]
    return conn


async def _get_server_tools(server_cfg: dict[str, Any]) -> list:
    """对单个 server 起临时 client，拉取工具列表。失败抛异常。"""
    conn = _to_connection(server_cfg)
    client = MultiServerMCPClient({server_cfg["name"]: conn}, tool_name_prefix=True)
    return await client.get_tools()


def test_mcp_server(db: Session, *, server_id, timeout: float = 10.0) -> McpTestResult:
    """测试单个 server 连通性：起临时 client 调 get_tools，返回工具列表。

    临时连接、不持久化、带超时。失败返回 ok=False + error，不抛异常。
    用 asyncio.run 同步化（本函数在同步 admin 路由里调用，无已存在事件循环）。
    """
    server = get_mcp_server(db, server_id=server_id)
    # 构造一个 resolve 形态的 dict（含明文凭据）
    cfg = {
        "id": str(server.id),
        "name": server.name,
        "transport": server.transport,
        "command": server.command,
        "args": server.args or [],
        "url": server.url,
        "headers": _decrypt_dict(server.headers_encrypted),
        "env": _decrypt_dict(server.env_encrypted),
    }
    try:
        tools = asyncio.run(asyncio.wait_for(_get_server_tools(cfg), timeout=timeout))
        names = [getattr(t, "name", str(t)) for t in tools]
        return McpTestResult(ok=True, tool_count=len(names), tool_names=names, error=None)
    except Exception as e:
        logger.warning("MCP server %s 测试连接失败: %s", server.name, e)
        return McpTestResult(ok=False, tool_count=0, tool_names=[], error=str(e)[:300])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_mcp_config_service.py -v`
Expected: 6 passed（含 2 个新 test）。

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/services/mcp_config_service.py apps/api/tests/test_mcp_config_service.py
git commit -m "feat(mcp): test_mcp_server 测试连接（临时 client + 超时 + 失败不抛）"
```

---

## Task 6: admin API 路由

**Files:**
- Create: `apps/api/app/api/admin/mcp.py`
- Modify: `apps/api/app/api/admin/__init__.py`
- Test: `apps/api/tests/test_admin_mcp_api.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_admin_mcp_api.py`：

```python
# apps/api/tests/test_admin_mcp_api.py
"""admin MCP API 测试：CRUD + 全局开关 + 测试连接 + 权限。"""


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })


def _make_admin(client, registered_user, db_session):
    from uuid import UUID
    from app.models import User
    user = db_session.query(User).filter_by(id=UUID(registered_user["id"])).first()
    user.role = "admin"
    db_session.commit()


def test_create_list_get_update_delete(client, registered_user, db_session):
    """admin 全流程 CRUD。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    # create
    resp = client.post("/api/v1/admin/mcp/servers", json={
        "name": "weather", "transport": "http", "url": "https://x/sse",
        "headers": {"Authorization": "Bearer secret"},
    })
    assert resp.status_code == 200, resp.text
    sid = resp.json()["id"]
    # 凭据 masking：不回明文
    assert resp.json()["headers"]["Authorization"] == {"has_value": True}

    # list
    resp = client.get("/api/v1/admin/mcp/servers")
    assert resp.status_code == 200
    assert any(s["id"] == sid for s in resp.json())

    # get
    resp = client.get(f"/api/v1/admin/mcp/servers/{sid}")
    assert resp.json()["name"] == "weather"

    # update（不传 headers → 保留旧值，仍 has_value）
    resp = client.put(f"/api/v1/admin/mcp/servers/{sid}", json={
        "name": "weather", "transport": "http", "url": "https://y/sse", "enabled": False,
    })
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    assert resp.json()["headers"]["Authorization"] == {"has_value": True}

    # delete
    resp = client.delete(f"/api/v1/admin/mcp/servers/{sid}")
    assert resp.json() == {"ok": True}


def test_global_enabled_roundtrip(client, registered_user, db_session):
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    resp = client.get("/api/v1/admin/mcp/enabled")
    assert resp.json()["enabled"] is True  # 默认

    resp = client.put("/api/v1/admin/mcp/enabled", json={"enabled": False})
    assert resp.status_code == 200

    resp = client.get("/api/v1/admin/mcp/enabled")
    assert resp.json()["enabled"] is False


def test_non_admin_forbidden(client, registered_user):
    """普通用户 → 403。"""
    _login(client, registered_user)
    resp = client.get("/api/v1/admin/mcp/servers")
    assert resp.status_code == 403


def test_test_endpoint(client, registered_user, db_session, monkeypatch):
    """/test 端点：monkeypatch service.test_mcp_server。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    # 先建一个 server
    r = client.post("/api/v1/admin/mcp/servers", json={
        "name": "fs", "transport": "http", "url": "https://x/sse",
    })
    sid = r.json()["id"]

    from app.services import mcp_config_service as svc
    from app.schemas.mcp import McpTestResult
    monkeypatch.setattr(
        svc, "test_mcp_server",
        lambda db, *, server_id: McpTestResult(ok=True, tool_count=1, tool_names=["search"], error=None),
    )

    resp = client.post(f"/api/v1/admin/mcp/servers/{sid}/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["tool_names"] == ["search"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_admin_mcp_api.py -v`
Expected: FAIL（404 或路由不存在）。

- [ ] **Step 3: 实现 admin 路由**

Create `apps/api/app/api/admin/mcp.py`：

```python
# apps/api/app/api/admin/mcp.py
"""admin MCP server 管理路由（/admin/mcp/*）。

仿 admin/skills.py（CRUD）+ admin/console.py（测试连接 + 全局开关）。
每个 handler 挂 require_admin。写操作记审计（detail 不含凭据明文）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import User
from app.schemas.mcp import (
    McpGlobalEnabled, McpServerCreate, McpServerOut, McpServerUpdate, McpTestResult,
)
from app.services import admin_service, mcp_config_service as svc

router = APIRouter(tags=["admin"])


# ── CRUD ──

@router.get("/admin/mcp/servers", response_model=list[McpServerOut])
def list_servers(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [McpServerOut(**svc.to_out(s)) for s in svc.list_mcp_servers(db)]


@router.post("/admin/mcp/servers", response_model=McpServerOut)
def create_server(
    payload: McpServerCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    server = svc.create_mcp_server(
        db, name=payload.name, transport=payload.transport,
        command=payload.command, args=payload.args, url=payload.url,
        headers=payload.headers, env=payload.env, enabled=payload.enabled, actor=admin,
    )
    admin_service._audit(
        db, actor=admin, action="create_mcp_server", target_type="mcp_server",
        target_id=str(server.id),
        detail={"name": server.name, "transport": server.transport, "enabled": server.enabled},
    )
    return McpServerOut(**svc.to_out(server))


@router.get("/admin/mcp/servers/{server_id}", response_model=McpServerOut)
def get_server(
    server_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return McpServerOut(**svc.to_out(svc.get_mcp_server(db, server_id=server_id)))


@router.put("/admin/mcp/servers/{server_id}", response_model=McpServerOut)
def update_server(
    server_id: str,
    payload: McpServerUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    fields = payload.model_dump(exclude_unset=True)
    server = svc.update_mcp_server(
        db, server_id=server_id, actor=admin,
        name=fields.get("name"), transport=fields.get("transport"),
        command=fields.get("command"), args=fields.get("args"), url=fields.get("url"),
        headers=fields.get("headers"), env=fields.get("env"),
        enabled=fields.get("enabled"),
    )
    admin_service._audit(
        db, actor=admin, action="update_mcp_server", target_type="mcp_server",
        target_id=str(server.id),
        detail={"name": server.name, "transport": server.transport, "enabled": server.enabled},
    )
    return McpServerOut(**svc.to_out(server))


@router.delete("/admin/mcp/servers/{server_id}")
def delete_server(
    server_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    svc.delete_mcp_server(db, server_id=server_id)
    admin_service._audit(
        db, actor=admin, action="delete_mcp_server", target_type="mcp_server",
        target_id=server_id, detail={},
    )
    return {"ok": True}


# ── 全局开关 ──

@router.get("/admin/mcp/enabled", response_model=McpGlobalEnabled)
def get_enabled(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return McpGlobalEnabled(enabled=svc.get_mcp_enabled(db))


@router.put("/admin/mcp/enabled", response_model=McpGlobalEnabled)
def set_enabled(
    payload: McpGlobalEnabled,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    svc.set_mcp_enabled(db, enabled=payload.enabled, actor=admin)
    admin_service._audit(
        db, actor=admin, action="set_mcp_global_enabled",
        target_type="system_setting", target_id="mcp_global_enabled",
        detail={"enabled": payload.enabled},
    )
    return McpGlobalEnabled(enabled=payload.enabled)


# ── 测试连接 ──

@router.post("/admin/mcp/servers/{server_id}/test", response_model=McpTestResult)
def test_server(
    server_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """测试单个 server 连通性（拉工具列表）。失败返回 ok=False + error，不抛 500。"""
    return svc.test_mcp_server(db, server_id=server_id)
```

- [ ] **Step 4: 注册路由**

修改 `apps/api/app/api/admin/__init__.py`：
- import 行改为：
  ```python
  from . import chunks, console, content, invites, mcp, retrieval, review, skills, users
  ```
- 在 `router.include_router(chunks.router)` 之前加：
  ```python
  router.include_router(mcp.router)
  ```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_admin_mcp_api.py -v`
Expected: 4 passed。

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/api/admin/mcp.py apps/api/app/api/admin/__init__.py apps/api/tests/test_admin_mcp_api.py
git commit -m "feat(mcp): admin API 路由 (CRUD + 全局开关 + 测试连接 + 审计)"
```

---

## Task 7: AI 接入 — 异步化 tools.py + load_mcp_tools

**Files:**
- Modify: `apps/api/app/ai/tools.py`
- Test: `apps/api/tests/test_ai_tools_mcp.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_ai_tools_mcp.py`：

```python
# apps/api/tests/test_ai_tools_mcp.py
"""load_mcp_tools 测试：全局开关关闭→空；无 server→空；server 加载成功→append；失败→跳过。"""


def test_load_mcp_tools_disabled_returns_empty(db_session):
    from app.services import mcp_config_service as svc
    svc.set_mcp_enabled(db_session, enabled=False)

    import asyncio
    from app.ai.tools import load_mcp_tools
    tools = asyncio.run(load_mcp_tools(db_session))
    assert tools == []


def test_load_mcp_tools_no_servers_returns_empty(db_session):
    from app.services import mcp_config_service as svc
    svc.set_mcp_enabled(db_session, enabled=True)
    # 无 server
    import asyncio
    from app.ai.tools import load_mcp_tools
    assert asyncio.run(load_mcp_tools(db_session)) == []


def test_load_mcp_tools_appends_and_skips_failures(db_session, monkeypatch):
    """两个 server：一个成功一个失败，只返回成功的工具，整体不抛。"""
    from app.services import mcp_config_service as svc
    svc.set_mcp_enabled(db_session, enabled=True)
    svc.create_mcp_server(db_session, name="ok", transport="http", url="https://a/sse", enabled=True)
    svc.create_mcp_server(db_session, name="bad", transport="http", url="https://b/sse", enabled=True)

    class _FakeTool:
        def __init__(self, n): self.name = n

    class _OkClient:
        def __init__(self, *a, **kw): pass
        async def get_tools(self): return [_FakeTool("search")]

    class _BadClient:
        def __init__(self, *a, **kw): pass
        async def get_tools(self): raise ConnectionError("down")

    # 按 server.name 路由不同 client
    import app.ai.tools as tools_mod

    def _fake_factory(connections, **kw):
        # connections 是 {name: cfg}，只有一个
        name = next(iter(connections))
        return _OkClient() if name == "ok" else _BadClient()

    monkeypatch.setattr(tools_mod, "MultiServerMCPClient", _fake_factory)

    import asyncio
    tools = asyncio.run(tools_mod.load_mcp_tools(db_session))
    assert len(tools) == 1  # 只成功 server 的 1 个工具，失败的被跳过
    assert tools[0].name == "search"


def test_create_agent_tools_is_async():
    """create_agent_tools 改成 async def（可被 await）。"""
    import inspect
    from app.ai.tools import create_agent_tools
    assert inspect.iscoroutinefunction(create_agent_tools)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_ai_tools_mcp.py -v`
Expected: FAIL（`load_mcp_tools` 不存在 / `create_agent_tools` 不是 async）。

- [ ] **Step 3: 改造 `tools.py`**

把 `apps/api/app/ai/tools.py` 的 `create_agent_tools` 改为 `async def`，并在末尾 append MCP 工具。完整改造：

在顶部 import 区加：
```python
import logging

from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)
```

把 `def create_agent_tools(db: Any, user_id):` 改为 `async def create_agent_tools(db: Any, user_id):`（函数体不变，仅加 `async`）。

把 `return [rag_search, save_memory]` 改为：
```python
    tools = [rag_search, save_memory]
    # 加载已启用的 MCP server 工具（逐 server try/except，失败跳过不阻塞 agent 构建）
    try:
        tools.extend(await load_mcp_tools(db))
    except Exception as e:
        logger.warning("MCP 工具整体加载失败，跳过: %s", e)
    return tools
```

在文件末尾追加 `load_mcp_tools`：
```python
async def load_mcp_tools(db: Any) -> list:
    """加载已启用的 MCP server 工具列表。

    - 全局开关关闭 / 无 server → 返回空列表。
    - 逐 server try/except：单个 server 连不上记日志、跳过，不阻塞其余 server。
    - tool_name_prefix=True：避免多 server 工具重名冲突。
    """
    from app.services.mcp_config_service import resolve_mcp_servers, _to_connection

    servers = resolve_mcp_servers(db)
    if not servers:
        return []
    tools: list = []
    for s in servers:
        try:
            conn = _to_connection(s)
            client = MultiServerMCPClient({s["name"]: conn}, tool_name_prefix=True)
            tools.extend(await client.get_tools())
        except Exception as e:
            logger.warning("MCP server %s 加载失败，跳过: %s", s["name"], e)
            continue
    return tools
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_ai_tools_mcp.py -v`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/tools.py apps/api/tests/test_ai_tools_mcp.py
git commit -m "feat(mcp): load_mcp_tools + create_agent_tools 异步化（逐 server 跳过失败）"
```

---

## Task 8: 异步化 build_agent + orchestrator 调用点

**Files:**
- Modify: `apps/api/app/ai/agent.py`
- Modify: `apps/api/app/ai/orchestrator.py`
- Test: 现有 agent 相关测试

- [ ] **Step 1: `build_agent` 改 async**

修改 `apps/api/app/ai/agent.py`：
- `def build_agent(` → `async def build_agent(`
- 第 117 行 `tools=create_agent_tools(db, user_id),` → `tools=await create_agent_tools(db, user_id),`

- [ ] **Step 2: orchestrator 两处调用加 `await`**

修改 `apps/api/app/ai/orchestrator.py`：
- 第 138 行：`agent = build_agent(db, ...)` → `agent = await build_agent(db, ...)`
- 第 199 行：`agent = build_agent(db, ...)` → `agent = await build_agent(db, ...)`

（两处都在已存在的 `async def astream_*` 函数内，加 `await` 即可。）

- [ ] **Step 3: 跑全部 AI 相关测试**

Run: `cd apps/api && uv run pytest tests/ -k "agent or orchestrator or ai or stream or chat or generate" -v`
Expected: 全部 PASS。

> ⚠️ 若有测试直接调用同步 `build_agent(...)`（未 await），会拿到 coroutine 而非 agent。检查报错并把这些测试调用改成 `await build_agent(...)`（测试函数本身需为 `async def` + pytest-asyncio，或用 `asyncio.run`）。

- [ ] **Step 4: 跑全量后端测试回归**

Run: `cd apps/api && uv run pytest`
Expected: 全部 PASS（含原有 36+ 测试）。若有因异步化导致的失败，逐一修复调用点。

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/agent.py apps/api/app/ai/orchestrator.py
git commit -m "refactor(ai): build_agent 异步化以支持 MCP 工具加载"
```

---

## Task 9: 前端类型 + API 方法

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: 加类型定义**

在 `apps/web/src/types/api.ts` 的 MinerU 类型块（约第 639 行 `MineruConfigPayload` 之后）追加：

```typescript
// ── MCP server 配置（admin 全局）──
export interface McpServer {
  id: string
  name: string
  transport: 'stdio' | 'http' | 'sse'
  command: string | null
  args: string[] | null
  url: string | null
  headers: Record<string, { has_value: boolean }> | null
  env: Record<string, { has_value: boolean }> | null
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface McpServerPayload {
  name: string
  transport: 'stdio' | 'http' | 'sse'
  command?: string | null
  args?: string[] | null
  url?: string | null
  headers?: Record<string, string> | null
  env?: Record<string, string> | null
  enabled?: boolean
}

export interface McpTestResult {
  ok: boolean
  tool_count: number
  tool_names: string[]
  error: string | null
}

export interface McpGlobalEnabled {
  enabled: boolean
}
```

- [ ] **Step 2: 加 API 方法**

在 `apps/web/src/lib/api.ts` 的 MinerU 方法块（约第 384 行 `testMineruConfig` 之后）追加：

```typescript
  // ── MCP server 全局配置（admin）── stdio/http/sse 三种传输
  listMcpServers: () =>
    request<import('@/types/api').McpServer[]>('/admin/mcp/servers'),

  createMcpServer: (payload: import('@/types/api').McpServerPayload) =>
    request<import('@/types/api').McpServer>('/admin/mcp/servers', {
      method: 'POST', body: JSON.stringify(payload),
    }),

  getMcpServer: (id: string) =>
    request<import('@/types/api').McpServer>(`/admin/mcp/servers/${id}`),

  updateMcpServer: (id: string, payload: Partial<import('@/types/api').McpServerPayload>) =>
    request<import('@/types/api').McpServer>(`/admin/mcp/servers/${id}`, {
      method: 'PUT', body: JSON.stringify(payload),
    }),

  deleteMcpServer: (id: string) =>
    request<{ ok: boolean }>(`/admin/mcp/servers/${id}`, { method: 'DELETE' }),

  getMcpEnabled: () =>
    request<import('@/types/api').McpGlobalEnabled>('/admin/mcp/enabled'),

  setMcpEnabled: (payload: import('@/types/api').McpGlobalEnabled) =>
    request<import('@/types/api').McpGlobalEnabled>('/admin/mcp/enabled', {
      method: 'PUT', body: JSON.stringify(payload),
    }),

  testMcpServer: (id: string) =>
    request<import('@/types/api').McpTestResult>(`/admin/mcp/servers/${id}/test`, {
      method: 'POST',
    }),
```

- [ ] **Step 3: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无新增类型错误（MCP 相关类型与方法自洽）。

- [ ] **Step 4: 提交**

```bash
git add apps/web/src/types/api.ts apps/web/src/lib/api.ts
git commit -m "feat(mcp/web): 类型定义 + API 方法（CRUD + 全局开关 + 测试）"
```

---

## Task 10: 前端 hooks（React Query）

**Files:**
- Modify: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: 加 queryKey**

在 `apps/web/src/lib/queries.ts` 的 `admin` 块内（`mineruConfig` 之后）加：

```typescript
    // MCP server 配置（stdio/http/sse）
    mcpServers: ['admin', 'mcp-servers'] as const,
    mcpEnabled: ['admin', 'mcp-enabled'] as const,
```

- [ ] **Step 2: 加 hooks**

在 MinerU hooks 块（`useTestMineruConfig` 之后，约第 697 行）追加：

```typescript
// ── MCP server 配置（admin 全局，stdio/http/sse）──
export function useMcpServers() {
  return useQuery({
    queryKey: queryKeys.admin.mcpServers,
    queryFn: () => api.listMcpServers(),
  })
}

export function useMcpEnabled() {
  return useQuery({
    queryKey: queryKeys.admin.mcpEnabled,
    queryFn: () => api.getMcpEnabled(),
  })
}

export function useSaveMcpServer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').McpServerPayload) =>
      api.createMcpServer(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpServers })
    },
  })
}

export function useUpdateMcpServer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<import('@/types/api').McpServerPayload> }) =>
      api.updateMcpServer(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpServers })
    },
  })
}

export function useDeleteMcpServer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteMcpServer(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpServers })
    },
  })
}

export function useToggleMcpGlobal() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').McpGlobalEnabled) =>
      api.setMcpEnabled(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpEnabled })
    },
  })
}

export function useTestMcpServer() {
  return useMutation({
    mutationFn: (id: string) => api.testMcpServer(id),
  })
}
```

- [ ] **Step 3: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无新增类型错误。

- [ ] **Step 4: 提交**

```bash
git add apps/web/src/lib/queries.ts
git commit -m "feat(mcp/web): React Query hooks（list/CRUD/toggle/test）"
```

---

## Task 11: 前端配置页

**Files:**
- Create: `apps/web/src/app/(app)/admin/console/mcp/page.tsx`

> 说明：本页有较多交互（表格 + 动态表单 + Dialog），无单测（项目前端无测试框架）。验证靠手动 + tsc。

- [ ] **Step 1: 创建配置页**

Create `apps/web/src/app/(app)/admin/console/mcp/page.tsx`：

```tsx
'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Plus, Trash2, Pencil, FlaskConical } from 'lucide-react'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { useMcpServers, useMcpEnabled, useToggleMcpGlobal,
  useSaveMcpServer, useUpdateMcpServer, useDeleteMcpServer, useTestMcpServer } from '@/lib/queries'
import type { McpServer } from '@/types/api'

type Transport = 'stdio' | 'http' | 'sse'

interface FormState {
  name: string
  transport: Transport
  command: string
  argsText: string  // 每行一个参数
  url: string
  headers: Record<string, string>
  env: Record<string, string>
  enabled: boolean
}

const EMPTY_FORM: FormState = {
  name: '', transport: 'stdio', command: '', argsText: '', url: '',
  headers: {}, env: {}, enabled: true,
}

export default function McpConfigPage() {
  const { data: servers, isLoading } = useMcpServers()
  const { data: enabledData } = useMcpEnabled()
  const toggleGlobal = useToggleMcpGlobal()
  const save = useSaveMcpServer()
  const update = useUpdateMcpServer()
  const remove = useDeleteMcpServer()
  const test = useTestMcpServer()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)

  function openCreate() {
    setForm(EMPTY_FORM)
    setEditingId(null)
    setDialogOpen(true)
  }

  function openEdit(s: McpServer) {
    setForm({
      name: s.name,
      transport: s.transport,
      command: s.command ?? '',
      argsText: (s.args ?? []).join('\n'),
      url: s.url ?? '',
      headers: {},
      env: {},
      enabled: s.enabled,
    })
    setEditingId(s.id)
    setDialogOpen(true)
  }

  function handleSubmit() {
    const args = form.argsText.split('\n').map((x) => x.trim()).filter(Boolean)
    const payload = {
      name: form.name,
      transport: form.transport,
      command: form.transport === 'stdio' ? form.command || null : null,
      args: form.transport === 'stdio' ? args : null,
      url: form.transport !== 'stdio' ? form.url || null : null,
      headers: form.transport !== 'stdio' && Object.keys(form.headers).length ? form.headers : null,
      env: form.transport === 'stdio' && Object.keys(form.env).length ? form.env : null,
      enabled: form.enabled,
    }
    const onSuccess = () => {
      toast.success(editingId ? '已更新' : '已创建')
      setDialogOpen(false)
    }
    const onError = (err: { message?: string }) => toast.error(err?.message ?? '操作失败')
    if (editingId) {
      update.mutate({ id: editingId, payload }, { onSuccess, onError })
    } else {
      save.mutate(payload, { onSuccess, onError })
    }
  }

  function handleToggleGlobal(next: boolean) {
    toggleGlobal.mutate({ enabled: next }, {
      onSuccess: () => toast.success(next ? '已开启 MCP 工具加载' : '已关闭 MCP 工具加载'),
      onError: () => toast.error('切换失败'),
    })
  }

  function handleToggleRow(s: McpServer, next: boolean) {
    update.mutate({ id: s.id, payload: { enabled: next } }, {
      onSuccess: () => toast.success(next ? '已启用' : '已禁用'),
      onError: () => toast.error('切换失败'),
    })
  }

  function handleDelete(s: McpServer) {
    if (!confirm(`确认删除 MCP server「${s.name}」？`)) return
    remove.mutate(s.id, {
      onSuccess: () => toast.success('已删除'),
      onError: () => toast.error('删除失败'),
    })
  }

  function handleTest(s: McpServer) {
    test.mutate(s.id, {
      onSuccess: (res) => {
        if (res.ok) toast.success(`连接成功，共 ${res.tool_count} 个工具：${res.tool_names.join(', ')}`)
        else toast.error(`测试失败：${res.error}`)
      },
      onError: () => toast.error('测试请求失败'),
    })
  }

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="MCP 配置" description="MCP server 全局管理" />
        <Skeleton className="h-64" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader title="MCP 配置" description="配置 MCP server，agent 生成时自动加载其工具">
        <Button onClick={openCreate}>
          <Plus className="mr-1 h-4 w-4" /> 添加 Server
        </Button>
      </PageHeader>

      <div className="space-y-4 py-6">
        {/* 全局开关 */}
        <div
          className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div>
            <div className="text-sm font-medium">启用 MCP 工具加载</div>
            <div className="text-xs text-muted-foreground">
              {enabledData?.enabled
                ? '已启用 server 的工具将被 agent 加载'
                : '关闭后，所有 MCP server 的工具都不会被 agent 加载'}
            </div>
          </div>
          <Switch
            checked={enabledData?.enabled ?? false}
            onCheckedChange={handleToggleGlobal}
            disabled={toggleGlobal.isPending}
          />
        </div>

        {/* server 列表 */}
        <div className="rounded-2xl border border-black/[0.07] bg-card dark:border-white/10" style={{ boxShadow: 'var(--shadow-card)' }}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>传输</TableHead>
                <TableHead>目标</TableHead>
                <TableHead>启用</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(servers ?? []).map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell>{s.transport}</TableCell>
                  <TableCell className="max-w-[280px] truncate text-xs text-muted-foreground">
                    {s.transport === 'stdio' ? `${s.command} ${(s.args ?? []).join(' ')}` : s.url}
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={s.enabled}
                      onCheckedChange={(v) => handleToggleRow(s, v)}
                      disabled={update.isPending}
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => handleTest(s)} disabled={test.isPending}>
                        <FlaskConical className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => openEdit(s)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(s)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {(servers ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                    暂无 MCP server，点击右上角添加
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* 添加/编辑 Dialog */}
      {dialogOpen && (
        <McpServerDialog
          form={form}
          setForm={setForm}
          editing={!!editingId}
          onClose={() => setDialogOpen(false)}
          onSubmit={handleSubmit}
          submitting={save.isPending || update.isPending}
        />
      )}
    </PageShell>
  )
}

// ── 表单 Dialog（手写，shadcn Dialog CLI 不可用）──
function McpServerDialog(props: {
  form: FormState
  setForm: (f: FormState) => void
  editing: boolean
  onClose: () => void
  onSubmit: () => void
  submitting: boolean
}) {
  const { form, setForm, editing, onClose, onSubmit, submitting } = props
  const isStdio = form.transport === 'stdio'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl border border-black/[0.07] bg-card p-6 dark:border-white/10"
        style={{ boxShadow: 'var(--shadow-card)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-lg font-semibold">{editing ? '编辑 Server' : '添加 Server'}</h2>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="mcp-name">名称</Label>
            <Input id="mcp-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="web-search" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="mcp-transport">传输方式</Label>
            <select
              id="mcp-transport"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
              value={form.transport}
              onChange={(e) => setForm({ ...form, transport: e.target.value as Transport })}
            >
              <option value="stdio">stdio（本地命令）</option>
              <option value="http">http（远程）</option>
              <option value="sse">sse（远程流式）</option>
            </select>
          </div>

          {isStdio ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-command">命令</Label>
                <Input id="mcp-command" value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} placeholder="npx" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-args">参数（每行一个）</Label>
                <textarea
                  id="mcp-args"
                  className="flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
                  value={form.argsText}
                  onChange={(e) => setForm({ ...form, argsText: e.target.value })}
                  placeholder={'-y\n@modelcontextprotocol/server-filesystem\n.'}
                />
              </div>
              <KVEditor label="环境变量 (env)" kv={form.env} onChange={(env) => setForm({ ...form, env })} />
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-url">URL</Label>
                <Input id="mcp-url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://example.com/sse" />
              </div>
              <KVEditor label="请求头 (headers)" kv={form.headers} onChange={(headers) => setForm({ ...form, headers })} />
            </>
          )}

          <div className="flex items-center gap-2">
            <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} />
            <Label>启用</Label>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={onSubmit} disabled={submitting || !form.name}>
            {submitting ? '保存中...' : '保存'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ── 键值对动态编辑器（headers / env 通用）──
function KVEditor(props: { label: string; kv: Record<string, string>; onChange: (kv: Record<string, string>) => void }) {
  const { label, kv, onChange } = props
  const keys = Object.keys(kv)
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {keys.map((k) => (
        <div key={k} className="flex gap-2">
          <Input
            className="flex-1"
            value={k}
            onChange={(e) => {
              const newKv = { ...kv }
              const val = newKv[k]; delete newKv[k]; newKv[e.target.value] = val
              onChange(newKv)
            }}
            placeholder="key"
          />
          <Input
            className="flex-1"
            type="password"
            value={kv[k]}
            onChange={(e) => onChange({ ...kv, [k]: e.target.value })}
            placeholder={editingHint()}
          />
          <Button variant="ghost" size="sm" onClick={() => { const n = { ...kv }; delete n[k]; onChange(n) }}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button variant="outline" size="sm" onClick={() => onChange({ ...kv, '': '' })}>
        <Plus className="mr-1 h-4 w-4" /> 添加
      </Button>
    </div>
  )

  function editingHint() {
    return 'value（留空则不变）'
  }
}
```

- [ ] **Step 2: 确认 Table 组件存在**

Run: `ls apps/web/src/components/ui/table.tsx`
Expected: 文件存在（探索阶段已确认 table 组件在用）。若不存在，需手写（见 GOTCHAS F8），但探索已确认存在。

- [ ] **Step 3: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无新增类型错误。

- [ ] **Step 4: 提交**

```bash
git add "apps/web/src/app/(app)/admin/console/mcp/page.tsx"
git commit -m "feat(mcp/web): MCP 配置页（全局开关 + server 表格 + 表单 Dialog）"
```

---

## Task 12: 控制台入口卡片

**Files:**
- Modify: `apps/web/src/app/(app)/admin/console/page.tsx`

- [ ] **Step 1: 加 MCP 卡片到 `CONSOLE_SECTIONS`**

修改 `apps/web/src/app/(app)/admin/console/page.tsx`：

import 行（第 3 行）加 `Plug`：
```tsx
import { BarChart3, FileText, Globe, Plug, ScanText, Search, Settings, SlidersHorizontal } from 'lucide-react'
```

在 `CONSOLE_SECTIONS` 数组里（`rerank` 之后、`audit` 之前）加：
```tsx
  {
    href: '/admin/console/mcp',
    icon: Plug,
    title: 'MCP 配置',
    description: 'MCP server 工具加载（stdio/http/sse）',
  },
```

- [ ] **Step 2: 类型检查 + 构建**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm build`
Expected: 构建成功，无错误。

- [ ] **Step 3: 提交**

```bash
git add "apps/web/src/app/(app)/admin/console/page.tsx"
git commit -m "feat(mcp/web): 控制台入口卡片"
```

---

## Task 13: 全量回归 + 手动验证

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest`
Expected: 全部 PASS（含新增 MCP 测试 + 原有测试）。

- [ ] **Step 2: 前端构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功。

- [ ] **Step 3: 手动验证（启动后端 + 前端）**

```bash
# 终端 1
cd apps/api && uv run uvicorn app.main:app --reload
# 终端 2
cd apps/web && pnpm dev
```

浏览器访问 `http://localhost:3000/admin/console`，确认：
1. 控制台出现「MCP 配置」卡片
2. 进入后能看到全局开关 + server 表格（空）
3. 添加一个 http server（如填测试 URL），保存成功，列表出现，凭据列显示已设置
4. 点「测试」按钮，toast 显示结果（外部 URL 失败属正常）
5. 编辑、启停、删除均正常
6. 全局开关切换正常

- [ ] **Step 4: 最终提交（如有手动验证发现的修复）**

若手动验证发现需修复，修复后单独提交。否则无需额外提交。

---

## Self-Review（plan 作者自检，执行者可忽略）

**Spec 覆盖：**
- §2 数据模型（mcp_servers 表 + 全局开关 + 加密）→ Task 1, 2, 4 ✓
- §3 后端 API（8 端点 + masking + 审计）→ Task 4, 5, 6 ✓
- §4 AI 接入（load_mcp_tools + 异步化 + 跳过失败）→ Task 7, 8 ✓
- §5 前端（页面 + 表单 + wiring + 卡片）→ Task 9, 10, 11, 12 ✓
- §6 测试/审计/安全 → Task 3-8 测试 + Task 6 审计 + masking 全程 ✓

**类型一致性：**
- `to_out` 在 service（返回 dict）和 route（`McpServerOut(**svc.to_out(s))`）用法一致 ✓
- `resolve_mcp_servers` 返回的 dict 形态与 `_to_connection` 读取的字段名（name/transport/command/args/url/headers/env）一致 ✓
- 前端 `McpServer` 类型与后端 `McpServerOut` 字段一一对应（headers/env 都是 `Record<string,{has_value}>`）✓
- `_to_connection` 在 service（Task 5 定义）和 tools.py（Task 7 `from ... import _to_connection`）共享同一实现，不重复 ✓
