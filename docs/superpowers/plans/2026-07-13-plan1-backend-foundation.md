# 计划 1：后端地基 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建天工后端地基——FastAPI 工程、Postgres+pgvector、User/Project/SystemSetting 数据模型、JWT 认证、项目 CRUD、资源级权限、首个管理员脚本，产出可通过 API 测试的后端骨架。

**Architecture:** FastAPI 单体（同步 + 请求级 DB Session）。SQLAlchemy 2.0 ORM + Alembic 迁移。PostgreSQL + pgvector（本计划只建扩展，向量字段在后续计划用）。JWT(access+refresh) 存 httpOnly Cookie。bcrypt 密码哈希。分层：api（路由）→ services（业务）→ models（ORM）→ schemas（Pydantic）。pytest 测试。

**Tech Stack:** Python 3.11+ · uv · FastAPI · SQLAlchemy 2.0 · Alembic · PostgreSQL 16 + pgvector · Pydantic v2 · pyjwt · passlib[bcrypt] · pytest · Docker Compose

**Spec reference:** `docs/superpowers/specs/2026-07-13-tiangong-mvp-design.md` v1.5
- 覆盖：路线图阶段 0（脚手架）+ 阶段 1（用户与项目基础）
- 数据模型：3.2 User / Project / SystemSetting
- 权限：8.1 角色（user/admin）+ 8.5 权限实现（require_admin / 资源级隔离）+ 13.1 资源级授权
- 认证：4.2 JWT（access+refresh）+ bcrypt

---

## 文件结构

本计划创建的后端目录（`apps/api/`）。每个文件单一职责：

```
apps/api/
├── pyproject.toml              # uv 依赖与项目元数据
├── alembic.ini                 # Alembic 配置
├── Dockerfile                  # 后端镜像
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 应用装配（路由注册、中间件、异常处理）
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py           # Settings（pydantic-settings，读 .env）
│   │   ├── security.py         # 密码哈希 + JWT 签发/校验 + AES 加密工具
│   │   ├── database.py         # engine + sessionmaker + get_db 依赖
│   │   └── exceptions.py       # 自定义异常 + 全局异常处理器
│   ├── deps.py                 # 公共依赖：get_current_user / require_user / require_admin
│   ├── models/
│   │   ├── __init__.py         # 导出所有模型（供 Alembic autogenerate 发现）
│   │   ├── base.py             # DeclarativeBase + 公共 mixin（TimestampMixin）
│   │   ├── user.py             # User 模型
│   │   ├── project.py          # Project 模型
│   │   └── system_setting.py   # SystemSetting 模型
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── auth.py             # 注册/登录请求与响应、Token
│   │   ├── user.py             # User 读/更新
│   │   └── project.py          # Project CRUD
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py     # 注册、登录、刷新、登出
│   │   └── project_service.py  # 项目 CRUD 业务逻辑
│   └── api/
│       ├── __init__.py
│       ├── router.py           # 聚合所有子路由
│       ├── auth.py             # /auth/* 认证路由
│       ├── projects.py         # /projects/* 项目路由
│       ├── health.py           # /health 健康检查
│       └── admin.py            # /admin/* 管理员占位路由（计划7实现细节）
├── scripts/
│   └── create_admin.py         # 命令行创建首个管理员
├── alembic/
│   ├── env.py                  # Alembic 环境（含 pgvector 扩展）
│   ├── script.py.mako
│   └── versions/               # 迁移脚本
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # pytest fixtures：测试 DB（sqlite/pg）、client、认证辅助
│   ├── test_health.py
│   ├── test_auth.py
│   ├── test_projects.py
│   └── test_admin_script.py
└── .env.example                # 环境变量样板
```

**关键设计决策（贯穿全计划）**：
1. **同步 + 请求级 Session**：`get_db` 依赖每请求 yield 一个 session，结束自动关闭。简单可靠、测试友好。
2. **httpOnly Cookie**：access/refresh token 放 cookie，防 XSS。CSRF 防护靠 `SameSite=Lax`（MVP 单体后端足够）。
3. **资源级权限**：所有资源 API 先 `get_current_user`（解码 JWT），再校验 `resource.user_id == user.id`，不符返回 **404**（非 403，防探测）。
4. **首个管理员**：`scripts/create_admin.py` 命令行创建，不开放注册管理员。
5. **数据库**：开发用 Postgres（docker-compose），测试用 **Postgres 测试库**（非 sqlite——因 pgvector 扩展与 JSONB 行为差异，测试库要贴近生产）。

---

## 任务 0：工程脚手架与 Docker Compose

**Files:**
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/.env.example`
- Create: `apps/api/Dockerfile`
- Create: `apps/api/app/__init__.py`（空文件）
- Create: `docker-compose.yml`（仓库根）
- Create: `.gitignore`（仓库根，若不存在）

- [ ] **Step 1: 创建仓库根 `.gitignore`**

Create `G:/03-Personal-Projects/TianGong/.gitignore`:

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.pytest_cache/
.ruff_cache/

# Env
.env
.env.local

# Node
node_modules/
.next/
dist/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# 项目数据（本地存储，勿提交）
uploads/
storage/
```

- [ ] **Step 2: 创建 `apps/api/pyproject.toml`**

Create `apps/api/pyproject.toml`:

```toml
[project]
name = "tiangong-api"
version = "0.1.0"
description = "TianGong patent disclosure AI agent - backend"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.36",
    "alembic>=1.14.0",
    "psycopg[binary]>=3.2.3",
    "pgvector>=0.3.6",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "passlib[bcrypt]>=1.7.4",
    "pyjwt>=2.10.0",
    "cryptography>=43.0.0",
    "python-multipart>=0.0.12",
    "loguru>=0.7.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 3: 创建 `.env.example`**

Create `apps/api/.env.example`:

```bash
# 数据库
DATABASE_URL=postgresql+psycopg://tiangong:tiangong@localhost:5432/tiangong
TEST_DATABASE_URL=postgresql+psycopg://tiangong:tiangong@localhost:5432/tiangong_test

# JWT
JWT_SECRET=change-me-to-a-random-64-char-string
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Cookie
COOKIE_DOMAIN=localhost
COOKIE_SECURE=false

# 加密（用于 LLM key 等敏感字段）
ENCRYPTION_KEY=change-me-base64-32-byte-key

# CORS
CORS_ORIGINS=http://localhost:3000
```

- [ ] **Step 4: 创建 `apps/api/Dockerfile`**

Create `apps/api/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 安装依赖（利用缓存层）
COPY pyproject.toml ./
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# 复制源码
COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

- [ ] **Step 5: 创建仓库根 `docker-compose.yml`**

Create `G:/03-Personal-Projects/TianGong/docker-compose.yml`:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: tiangong-postgres
    environment:
      POSTGRES_USER: tiangong
      POSTGRES_PASSWORD: tiangong
      POSTGRES_DB: tiangong
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tiangong"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

- [ ] **Step 6: 创建空 `__init__.py`**

Create `apps/api/app/__init__.py`（内容为空）。

- [ ] **Step 7: 验证依赖可安装**

Run（在 `apps/api/` 目录）:
```bash
cd apps/api && uv sync
```
Expected: 创建 `.venv/`，安装所有依赖无报错。

- [ ] **Step 8: 启动 Postgres 验证 pgvector 镜像可用**

Run（仓库根）:
```bash
docker compose up -d postgres
docker compose exec postgres psql -U tiangong -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extversion FROM pg_extension WHERE extname='vector';"
```
Expected: 输出 pgvector 版本号（如 `0.3.0` 或更高）。

- [ ] **Step 9: Commit**

```bash
git add apps/api/pyproject.toml apps/api/.env.example apps/api/Dockerfile apps/api/app/__init__.py docker-compose.yml .gitignore
git commit -m "chore: 初始化后端脚手架与 Docker Compose（pgvector）"
```

---

## 任务 1：配置层（Settings + 加密工具）

**Files:**
- Create: `apps/api/app/core/__init__.py`（空）
- Create: `apps/api/app/core/config.py`
- Create: `apps/api/app/core/security.py`
- Test: `apps/api/tests/__init__.py`（空）
- Test: `apps/api/tests/test_security.py`

- [ ] **Step 1: 创建空 `__init__.py`**

Create `apps/api/app/core/__init__.py` 和 `apps/api/tests/__init__.py`（均空）。

- [ ] **Step 2: 写 `config.py` 的失败测试**

Create `apps/api/tests/test_config.py`:

```python
import os
from app.core.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://t:t@localhost/t")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("ENCRYPTION_KEY", "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=")
    s = Settings()
    assert s.database_url.startswith("postgresql://")
    assert len(s.jwt_secret) >= 32
    assert s.access_token_expire_minutes == 30


def test_cors_origins_parses_csv(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://t:t@localhost/t")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("ENCRYPTION_KEY", "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com,http://b.com")
    s = Settings()
    assert s.cors_origins == ["http://a.com", "http://b.com"]
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: app.core.config`）。

- [ ] **Step 4: 实现 `config.py`**

Create `apps/api/app/core/config.py`:

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 数据库
    database_url: str
    test_database_url: str = ""

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Cookie
    cookie_domain: str = "localhost"
    cookie_secure: bool = False

    # 加密
    encryption_key: str

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    @classmethod
    def from_env(cls) -> "Settings":
        # pydantic-settings 自动从 .env 与环境变量读取
        return cls()  # type: ignore[call-arg]


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
```

> 注：`cors_origins` 用 `list[str]`，pydantic-settings 会自动按逗号分割字符串。但默认值需是 list 形式。

- [ ] **Step 5: 创建 `.env`（本地，不提交）**

Run: `cd apps/api && cp .env.example .env`

> `.env` 已在 `.gitignore` 中，不会被提交。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_config.py -v`
Expected: 2 passed。

- [ ] **Step 7: 写 `security.py` 的失败测试**

Create `apps/api/tests/test_security.py`:

```python
import jwt
import pytest
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    encrypt_value, decrypt_value,
)


def test_password_hash_and_verify():
    raw = "MyPass123!"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_access_token_roundtrip():
    token = create_access_token({"sub": "user-abc", "role": "user"})
    payload = decode_token(token)
    assert payload["sub"] == "user-abc"
    assert payload["role"] == "user"
    assert payload["type"] == "access"


def test_refresh_token_has_correct_type():
    token = create_refresh_token({"sub": "user-abc"})
    payload = decode_token(token)
    assert payload["type"] == "refresh"


def test_decode_invalid_token_raises():
    with pytest.raises(jwt.InvalidTokenError):
        decode_token("not.a.valid.token")


def test_encrypt_decrypt_roundtrip():
    secret = "sk-abcdefghij123456"
    enc = encrypt_value(secret)
    assert enc != secret
    assert decrypt_value(enc) == secret
```

- [ ] **Step 8: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_security.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 9: 实现 `security.py`**

Create `apps/api/app/core/security.py`:

```python
import base64
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from cryptography.fernet import Fernet
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── 密码 ──
def hash_password(raw: str) -> str:
    return _pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd_context.verify(raw, hashed)


# ── JWT ──
def _create_token(data: dict[str, Any], expires_delta: timedelta, token_type: str) -> str:
    settings = get_settings()
    payload = {**data, "type": token_type}
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(data: dict[str, Any]) -> str:
    settings = get_settings()
    return _create_token(data, timedelta(minutes=settings.access_token_expire_minutes), "access")


def create_refresh_token(data: dict[str, Any]) -> str:
    settings = get_settings()
    return _create_token(data, timedelta(days=settings.refresh_token_expire_days), "refresh")


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# ── 对称加密（用于 LLM key 等敏感字段，计划1预埋） ──
def _get_fernet() -> Fernet:
    settings = get_settings()
    # encryption_key 期望是 base64 编码的 32 字节
    key = base64.urlsafe_b64decode(settings.encryption_key)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
```

- [ ] **Step 10: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_security.py -v`
Expected: 5 passed。

- [ ] **Step 11: Commit**

```bash
git add apps/api/app/core/ apps/api/tests/test_config.py apps/api/tests/test_security.py apps/api/tests/__init__.py
git commit -m "feat: 配置层与安全工具（bcrypt密码、JWT签发校验、AES加密）"
```

---

## 任务 2：数据库与模型

**Files:**
- Create: `apps/api/app/core/database.py`
- Create: `apps/api/app/models/__init__.py`
- Create: `apps/api/app/models/base.py`
- Create: `apps/api/app/models/user.py`
- Create: `apps/api/app/models/project.py`
- Create: `apps/api/app/models/system_setting.py`
- Test: `apps/api/tests/test_models.py`

- [ ] **Step 1: 写模型行为的失败测试**

Create `apps/api/tests/test_models.py`:

```python
from datetime import datetime

from app.models import User, Project, SystemSetting


def test_user_defaults():
    u = User(email="a@b.com", password_hash="x", name="A")
    assert u.role == "user"
    assert u.status == "active"
    assert u.org_id is None
    assert u.is_superuser is False


def test_project_stage_defaults_to_disclosure():
    u = User(email="a@b.com", password_hash="x", name="A")
    p = Project(user_id=u.id, title="我的发明", template_id=None)
    assert p.stage == "disclosure"
    assert p.status == "draft"
    assert p.progress_pct == 0


def test_system_setting_key_value():
    s = SystemSetting(key="llm_global_enabled", value={"enabled": True})
    assert s.key == "llm_global_enabled"
    assert s.value == {"enabled": True}
```

> 注：这些测试只验证模型字段默认值，不涉及 DB（用 SQLAlchemy 的对象构造即可）。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_models.py -v`
Expected: FAIL（`ModuleNotFoundError: app.models`）。

- [ ] **Step 3: 实现 `database.py`**

Create `apps/api/app/core/database.py`:

```python
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每请求 yield 一个 session，结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: 实现 `base.py`（DeclarativeBase + Mixin）**

Create `apps/api/app/models/base.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 5: 实现 `user.py`**

Create `apps/api/app/models/user.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))

    # 角色：user / admin（MVP）；预留 org_admin（P2+）
    role: Mapped[str] = mapped_column(String(20), default="user")
    # 状态：active / disabled
    status: Mapped[str] = mapped_column(String(20), default="active")
    # 所属组织（预留，MVP 为 NULL）
    org_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # 首个超管标记（命令行创建）
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 6: 实现 `project.py`**

Create `apps/api/app/models/project.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Project(Base, IdMixin, TimestampMixin):
    __tablename__ = "projects"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    # 生命周期阶段：disclosure(MVP) / application / examination / archive
    stage: Mapped[str] = mapped_column(String(20), default="disclosure")
    # 状态：draft / in_progress / completed / archived
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_section_order: Mapped[int] = mapped_column(Integer, default=1)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    prior_art_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

> 注：`metadata` 是 SQLAlchemy 保留字，用 `mapped_column("metadata", ...)` 映射列名，Python 属性用 `metadata_`。

- [ ] **Step 7: 实现 `system_setting.py`**

Create `apps/api/app/models/system_setting.py`:

```python
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class SystemSetting(Base, IdMixin, TimestampMixin):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
```

- [ ] **Step 8: 实现 `models/__init__.py`（聚合导出）**

Create `apps/api/app/models/__init__.py`:

```python
from app.models.base import Base
from app.models.project import Project
from app.models.system_setting import SystemSetting
from app.models.user import User

__all__ = ["Base", "User", "Project", "SystemSetting"]
```

- [ ] **Step 9: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_models.py -v`
Expected: 3 passed。

- [ ] **Step 10: Commit**

```bash
git add apps/api/app/core/database.py apps/api/app/models/ apps/api/tests/test_models.py
git commit -m "feat: 数据库连接与核心模型（User/Project/SystemSetting）"
```

---

## 任务 3：Alembic 迁移

**Files:**
- Create: `apps/api/alembic.ini`
- Create: `apps/api/alembic/env.py`
- Create: `apps/api/alembic/script.py.mako`
- Create: `apps/api/alembic/versions/`（目录）

- [ ] **Step 1: 初始化 Alembic**

Run:
```bash
cd apps/api && uv run alembic init alembic
```
Expected: 生成 `alembic.ini`、`alembic/env.py`、`alembic/script.py.mako`、`alembic/versions/`。

- [ ] **Step 2: 替换 `alembic.ini` 的 sqlalchemy.url**

Edit `apps/api/alembic.ini`，找到 `[alembic]` 段下的 `sqlalchemy.url` 行，改为（让 env.py 动态注入）:

```ini
sqlalchemy.url =
```

- [ ] **Step 3: 替换 `alembic/env.py`**

覆盖 `apps/api/alembic/env.py` 全部内容为:

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.models import Base  # 导入所有模型供 autogenerate 发现

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 动态注入数据库 URL
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: 生成首个迁移**

Run:
```bash
cd apps/api && uv run alembic revision --autogenerate -m "init schema: users projects system_settings"
```
Expected: 在 `alembic/versions/` 生成迁移文件，含 `create_table` for users/projects/system_settings。

- [ ] **Step 5: 检查生成的迁移，确认无遗漏**

打开生成的迁移文件，确认包含：
- `op.create_table('users', ...)` 含 email/password_hash/name/role/status/org_id/is_superuser/last_login_at/created_at/updated_at/id
- `op.create_table('projects', ...)` 含 user_id(外键)/template_id/title/stage/status/current_section_order/progress_pct/metadata/prior_art_refs/archived_at/...
- `op.create_table('system_settings', ...)` 含 key/value/updated_by/...
- 各表的 unique index（email、key）

如果发现遗漏，手动补全。

- [ ] **Step 6: 应用迁移到开发库**

确保 Postgres 已启动（`docker compose up -d postgres`），然后：
```bash
cd apps/api && uv run alembic upgrade head
```
Expected: 输出 `Running upgrade -> <revision>, init schema ...`，无报错。

- [ ] **Step 7: 验证表已创建**

Run:
```bash
docker compose exec postgres psql -U tiangong -c "\dt"
```
Expected: 看到 `alembic_version`、`users`、`projects`、`system_settings` 四张表。

- [ ] **Step 8: Commit**

```bash
git add apps/api/alembic.ini apps/api/alembic/
git commit -m "feat: Alembic 迁移配置与初始 schema（users/projects/system_settings）"
```

---

## 任务 4：认证（密码校验 + JWT 依赖）

**Files:**
- Create: `apps/api/app/schemas/__init__.py`（空）
- Create: `apps/api/app/schemas/auth.py`
- Create: `apps/api/app/schemas/user.py`
- Test: `apps/api/tests/conftest.py`
- Test: `apps/api/tests/test_auth.py`

- [ ] **Step 1: 实现 `schemas/auth.py` 和 `schemas/user.py`**

Create `apps/api/app/schemas/auth.py`:

```python
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str
```

Create `apps/api/app/schemas/user.py`:

```python
from pydantic import BaseModel, EmailStr


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str
    status: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: 写 conftest.py（测试 fixtures）**

Create `apps/api/tests/conftest.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Base, User


@pytest.fixture(scope="session")
def db_url() -> str:
    settings = get_settings()
    # 优先用 TEST_DATABASE_URL；回退到内存 sqlite（仅当无测试库时）
    return settings.test_database_url or "sqlite+pysqlite:///:memory:"


@pytest.fixture(scope="function")
def engine(db_url):
    """每测试用独立 engine。Postgres 测试库需用事务回滚隔离。"""
    if db_url.startswith("postgresql"):
        eng = create_engine(db_url, pool_pre_ping=True)
        # 确保表存在（测试库）
        Base.metadata.create_all(eng)
        yield eng
        Base.metadata.drop_all(eng)
    else:
        # sqlite 内存回退（不依赖 pgvector 时不影响）
        eng = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(eng)
        yield eng
        eng.dispose()


@pytest.fixture
def db(engine):
    """每测试一个 session，Postgres 下用 SAVEPOINT 隔离。"""
    connection = engine.connect()
    trans = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture
def app_obj(db, monkeypatch):
    """构造 app 时用测试 DB。"""
    from app.core import database as db_module
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=db.bind))
    from app.main import app
    yield app


@pytest.fixture
def client(app_obj):
    with TestClient(app_obj) as c:
        yield c


@pytest.fixture
def registered_user(db) -> dict:
    """注册一个普通用户，返回 {id, email, password}。"""
    from app.models import User
    u = User(
        email="test@example.com",
        password_hash=hash_password("Pass1234!"),
        name="测试用户",
    )
    db.add(u)
    db.commit()
    return {"id": str(u.id), "email": u.email, "password": "Pass1234!"}
```

- [ ] **Step 3: 写认证失败的测试**

Create `apps/api/tests/test_auth.py`:

```python
from app.core.security import hash_password, verify_password
from app.models import User
from app.services.auth_service import authenticate_user, register_user


def test_authenticate_user_success(db):
    register_user(db, email="a@b.com", password="Pass1234!", name="A")
    user = authenticate_user(db, email="a@b.com", password="Pass1234!")
    assert user is not None
    assert user.email == "a@b.com"


def test_authenticate_user_wrong_password(db):
    register_user(db, email="a@b.com", password="Pass1234!", name="A")
    assert authenticate_user(db, email="a@b.com", password="wrong") is None


def test_authenticate_user_not_found(db):
    assert authenticate_user(db, email="none@b.com", password="x") is None


def test_register_duplicate_email_raises(db):
    register_user(db, email="a@b.com", password="Pass1234!", name="A")
    import pytest
    from app.core.exceptions import ConflictError
    with pytest.raises(ConflictError):
        register_user(db, email="a@b.com", password="Pass1234!", name="B")
```

- [ ] **Step 4: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_auth.py -v`
Expected: FAIL（`app.services.auth_service` 与 `app.core.exceptions` 不存在）。

- [ ] **Step 5: 实现 `core/exceptions.py`**

Create `apps/api/app/core/exceptions.py`:

```python
class AppError(Exception):
    """所有自定义异常基类。status_code 决定 HTTP 响应。"""
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
```

- [ ] **Step 6: 实现 `services/auth_service.py`**

Create `apps/api/app/services/__init__.py`（空）。

Create `apps/api/app/services/auth_service.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.core.security import hash_password, verify_password
from app.models import User


def register_user(db: Session, *, email: str, password: str, name: str) -> User:
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise ConflictError(f"邮箱 {email} 已注册")
    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        return None
    if user.status != "active":
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def update_last_login(db: Session, user: User) -> None:
    from datetime import datetime, timezone
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_auth.py -v`
Expected: 4 passed。

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/schemas/ apps/api/app/services/ apps/api/app/core/exceptions.py apps/api/tests/conftest.py apps/api/tests/test_auth.py
git commit -m "feat: 认证服务（注册/登录校验）与异常体系"
```

---

## 任务 5：认证 API 路由（注册/登录/刷新/登出）

**Files:**
- Create: `apps/api/app/deps.py`
- Create: `apps/api/app/api/__init__.py`（空）
- Create: `apps/api/app/api/auth.py`
- Create: `apps/api/app/api/health.py`
- Create: `apps/api/app/api/router.py`
- Test: `apps/api/tests/test_auth_api.py`

- [ ] **Step 1: 实现 `deps.py`（get_current_user 依赖）**

Create `apps/api/app/deps.py`:

```python
import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token
from app.models import User


def _extract_token(request: Request) -> str | None:
    """从 access_token cookie 取 token。"""
    return request.cookies.get("access_token")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise UnauthorizedError("未登录")
    try:
        payload = decode_token(token)
    except jwt.InvalidTokenError:
        raise UnauthorizedError("无效的登录凭证")
    if payload.get("type") != "access":
        raise UnauthorizedError("token 类型错误")
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("token 缺少用户标识")
    from sqlalchemy import select
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or user.status != "active":
        raise UnauthorizedError("用户不存在或已禁用")
    return user
```

- [ ] **Step 2: 写认证 API 失败测试**

Create `apps/api/tests/test_auth_api.py`:

```python
def test_register_success(client):
    res = client.post("/api/v1/auth/register", json={
        "email": "new@example.com",
        "password": "Pass1234!",
        "name": "新用户",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "new@example.com"
    assert data["role"] == "user"
    assert "id" in data


def test_register_duplicate(client, registered_user):
    res = client.post("/api/v1/auth/register", json={
        "email": registered_user["email"],
        "password": "Pass1234!",
        "name": "重复",
    })
    assert res.status_code == 409


def test_login_success_sets_cookie(client, registered_user):
    res = client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    assert res.status_code == 200
    assert "access_token" in res.cookies
    assert "refresh_token" in res.cookies


def test_login_wrong_password(client, registered_user):
    res = client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": "wrongpass",
    })
    assert res.status_code == 401


def test_me_requires_auth(client):
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_me_returns_user(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200
    assert res.json()["email"] == registered_user["email"]


def test_logout_clears_cookies(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 200
    # cookie 被清除（值为空或过期）
    assert res.cookies.get("access_token") in (None, "")
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_auth_api.py -v`
Expected: FAIL（路由不存在）。

- [ ] **Step 4: 实现 `api/auth.py`**

Create `apps/api/app/api/auth.py`:

```python
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token
from app.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.services.auth_service import authenticate_user, register_user, update_last_login

router = APIRouter(prefix="/auth", tags=["auth"])
_settings = get_settings()


def _set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie(
        "access_token", access,
        httponly=True, secure=_settings.cookie_secure,
        samesite="lax", max_age=_settings.access_token_expire_minutes * 60,
        domain=_settings.cookie_domain,
    )
    response.set_cookie(
        "refresh_token", refresh,
        httponly=True, secure=_settings.cookie_secure,
        samesite="lax", max_age=_settings.refresh_token_expire_days * 86400,
        domain=_settings.cookie_domain,
    )


@router.post("/register", response_model=UserRead)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = register_user(db, email=payload.email, password=payload.password, name=payload.name)
    return UserRead(id=str(user.id), email=user.email, name=user.name, role=user.role)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_user(db, email=payload.email, password=payload.password)
    if user is None:
        raise UnauthorizedError("邮箱或密码错误")
    update_last_login(db, user)
    access = create_access_token({"sub": str(user.id), "role": user.role})
    refresh = create_refresh_token({"sub": str(user.id)})
    _set_auth_cookies(response, access, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token", domain=_settings.cookie_domain)
    response.delete_cookie("refresh_token", domain=_settings.cookie_domain)
    return {"message": "已登出"}


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)):
    return UserRead(
        id=str(current_user.id), email=current_user.email,
        name=current_user.name, role=current_user.role,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(request):  # 简化：MVP 不实现 refresh 逻辑，预留
    # 计划 1 暂不实现 refresh 端点（access 30 分钟足够测试）
    raise UnauthorizedError("未实现")
```

> 注：`/refresh` 端点 MVP 预留不实现（access token 30 分钟，测试期足够）；后续计划补全。

- [ ] **Step 5: 实现 `api/health.py`**

Create `apps/api/app/api/health.py`:

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 6: 实现 `api/router.py`**

Create `apps/api/app/api/router.py`:

```python
from fastapi import APIRouter

from app.api import auth, health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(health.router)
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_auth_api.py -v`
Expected: 7 passed。

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/deps.py apps/api/app/api/ apps/api/tests/test_auth_api.py
git commit -m "feat: 认证 API（注册/登录/登出/me）+ httpOnly cookie"
```

---

## 任务 6：权限依赖（require_admin）

**Files:**
- Modify: `apps/api/app/deps.py`（追加 require_admin）
- Test: `apps/api/tests/test_permissions.py`

- [ ] **Step 1: 写权限测试**

Create `apps/api/tests/test_permissions.py`:

```python
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.deps import get_current_user, require_admin
from app.models import User


def _make_app_with_admin_route():
    """临时 app，含一个仅 admin 可访问的路由。"""
    app = FastAPI()

    @app.get("/admin-only")
    def admin_only_route(admin: User = Depends(require_admin)):
        return {"id": str(admin.id)}

    return app


def test_admin_can_access(client, db, monkeypatch):
    # 创建一个 admin 用户
    admin = User(
        email="admin@example.com",
        password_hash=hash_password("Pass1234!"),
        name="管理员",
        role="admin",
    )
    db.add(admin)
    db.commit()

    # 登录
    client.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "Pass1234!",
    })

    # 用同 db 的 app 测试 require_admin
    app = _make_app_with_admin_route()
    # 复用 client 的 cookie 需要绑定到新 app——这里直接验证依赖逻辑
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr("app.deps.get_db", lambda: (yield db))

    with TestClient(app) as c:
        # 手动设 cookie
        from app.core.security import create_access_token
        token = create_access_token({"sub": str(admin.id), "role": "admin"})
        c.cookies.set("access_token", token)
        res = c.get("/admin-only")
        assert res.status_code == 200


def test_normal_user_forbidden(client, db, registered_user, monkeypatch):
    app = _make_app_with_admin_route()
    monkeypatch.setattr("app.deps.get_db", lambda: (yield db))
    with TestClient(app) as c:
        from app.core.security import create_access_token
        token = create_access_token({"sub": registered_user["id"], "role": "user"})
        c.cookies.set("access_token", token)
        res = c.get("/admin-only")
        assert res.status_code == 403
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_permissions.py -v`
Expected: FAIL（`require_admin` 不存在）。

- [ ] **Step 3: 在 `deps.py` 追加 `require_admin`**

在 `apps/api/app/deps.py` 末尾追加:

```python
from app.core.exceptions import ForbiddenError


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """校验当前用户是 admin，否则 403。"""
    if current_user.role != "admin":
        raise ForbiddenError("需要管理员权限")
    return current_user
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_permissions.py -v`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/deps.py apps/api/tests/test_permissions.py
git commit -m "feat: require_admin 权限依赖（管理员校验 403）"
```

---

## 任务 7：项目 CRUD API + 资源级权限

**Files:**
- Create: `apps/api/app/schemas/project.py`
- Create: `apps/api/app/services/project_service.py`
- Create: `apps/api/app/api/projects.py`
- Modify: `apps/api/app/api/router.py`（注册 projects 路由）
- Test: `apps/api/tests/test_projects.py`

- [ ] **Step 1: 实现 `schemas/project.py`**

Create `apps/api/app/schemas/project.py`:

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    template_id: str | None = None
    metadata: dict[str, Any] | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict[str, Any] | None = None


class ProjectOut(BaseModel):
    id: str
    title: str
    stage: str
    status: str
    progress_pct: int
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: 写项目服务的失败测试**

Create `apps/api/tests/test_projects.py`:

```python
import pytest
from app.core.exceptions import NotFoundError
from app.models import Project, User
from app.services.project_service import (
    create_project, get_project, list_projects,
    update_project, delete_project,
)


def test_create_project(db, registered_user):
    user = db.get(User, registered_user["id"])
    p = create_project(db, user=user, title="我的发明")
    assert p.id is not None
    assert p.title == "我的发明"
    assert p.stage == "disclosure"
    assert p.status == "draft"
    assert p.user_id == user.id


def test_list_projects_only_own(db, registered_user):
    user = db.get(User, registered_user["id"])
    # 另一个用户的项目
    other = User(email="o@b.com", password_hash="x", name="O")
    db.add(other)
    db.commit()
    create_project(db, user=other, title="别人的")
    # 自己的项目
    create_project(db, user=user, title="我的")
    projects = list_projects(db, user=user)
    assert len(projects) == 1
    assert projects[0].title == "我的"


def test_get_project_not_found_raises(db, registered_user):
    user = db.get(User, registered_user["id"])
    with pytest.raises(NotFoundError):
        get_project(db, user=user, project_id="00000000-0000-0000-0000-000000000000")


def test_get_project_other_users_returns_404(db):
    """资源级权限：访问他人项目返回 NotFound（防探测）。"""
    owner = User(email="o@b.com", password_hash="x", name="O")
    intruder = User(email="i@b.com", password_hash="x", name="I")
    db.add_all([owner, intruder])
    db.commit()
    p = create_project(db, user=owner, title="所有者的")
    with pytest.raises(NotFoundError):
        get_project(db, user=intruder, project_id=str(p.id))


def test_delete_project(db, registered_user):
    user = db.get(User, registered_user["id"])
    p = create_project(db, user=user, title="待删")
    delete_project(db, user=user, project_id=str(p.id))
    with pytest.raises(NotFoundError):
        get_project(db, user=user, project_id=str(p.id))
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_projects.py -v`
Expected: FAIL（`app.services.project_service` 不存在）。

- [ ] **Step 4: 实现 `services/project_service.py`**

Create `apps/api/app/services/project_service.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Project, User


def create_project(
    db: Session, *, user: User, title: str,
    template_id: str | None = None,
    metadata: dict | None = None,
) -> Project:
    project = Project(
        user_id=user.id,
        title=title,
        template_id=uuid.UUID(template_id) if template_id else None,
        metadata_=metadata,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, *, user: User, project_id: str) -> Project:
    """获取项目。资源级权限：非本人项目返回 NotFound（防探测）。"""
    project = db.scalar(
        select(Project).where(Project.id == project_id)
    )
    if project is None or project.user_id != user.id:
        raise NotFoundError("项目不存在")
    return project


def list_projects(db: Session, *, user: User) -> list[Project]:
    return list(db.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.updated_at.desc())
    ))


def update_project(
    db: Session, *, user: User, project_id: str,
    title: str | None = None, metadata: dict | None = None,
) -> Project:
    project = get_project(db, user=user, project_id=project_id)
    if title is not None:
        project.title = title
    if metadata is not None:
        project.metadata_ = metadata
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, *, user: User, project_id: str) -> None:
    project = get_project(db, user=user, project_id=project_id)
    db.delete(project)
    db.commit()
```

- [ ] **Step 5: 运行服务层测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_projects.py -v`
Expected: 5 passed。

- [ ] **Step 6: 实现 `api/projects.py`**

Create `apps/api/app/api/projects.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
def create(payload: ProjectCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.create_project(
        db, user=current_user, title=payload.title,
        template_id=payload.template_id, metadata=payload.metadata,
    )
    return _to_out(p)


@router.get("", response_model=list[ProjectOut])
def list_all(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = project_service.list_projects(db, user=current_user)
    return [_to_out(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_one(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.get_project(db, user=current_user, project_id=project_id)
    return _to_out(p)


@router.patch("/{project_id}", response_model=ProjectOut)
def update(project_id: str, payload: ProjectUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.update_project(
        db, user=current_user, project_id=project_id,
        title=payload.title, metadata=payload.metadata,
    )
    return _to_out(p)


@router.delete("/{project_id}", status_code=204)
def delete(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project_service.delete_project(db, user=current_user, project_id=project_id)
    return None


def _to_out(p) -> ProjectOut:
    return ProjectOut(
        id=str(p.id), title=p.title, stage=p.stage, status=p.status,
        progress_pct=p.progress_pct, metadata=p.metadata_,
        created_at=p.created_at, updated_at=p.updated_at,
    )
```

- [ ] **Step 7: 注册路由到 `router.py`**

Edit `apps/api/app/api/router.py`:

```python
from fastapi import APIRouter

from app.api import auth, health, projects

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(health.router)
```

- [ ] **Step 8: 写项目 API 集成测试（追加到 test_projects.py）**

在 `apps/api/tests/test_projects.py` 末尾追加:

```python
def test_api_create_and_list(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    res = client.post("/api/v1/projects", json={"title": "API发明"})
    assert res.status_code == 201
    assert res.json()["title"] == "API发明"

    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_api_access_other_users_project_returns_404(client, registered_user, db):
    # 创建另一个用户及其项目
    from app.core.security import hash_password
    from app.services.project_service import create_project
    other = User(email="o@b.com", password_hash=hash_password("Pass1234!"), name="O")
    db.add(other)
    db.commit()
    other_project = create_project(db, user=other, title="别人的")

    # registered_user 登录后尝试访问 other 的项目
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    res = client.get(f"/api/v1/projects/{other_project.id}")
    assert res.status_code == 404


def test_api_unauthenticated_returns_401(client):
    res = client.get("/api/v1/projects")
    assert res.status_code == 401
```

- [ ] **Step 9: 运行全部项目测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_projects.py -v`
Expected: 8 passed。

- [ ] **Step 10: Commit**

```bash
git add apps/api/app/schemas/project.py apps/api/app/services/project_service.py apps/api/app/api/projects.py apps/api/app/api/router.py apps/api/tests/test_projects.py
git commit -m "feat: 项目 CRUD API + 资源级权限（他人项目返回 404）"
```

---

## 任务 8：首个管理员命令行脚本

**Files:**
- Create: `apps/api/scripts/__init__.py`（空）
- Create: `apps/api/scripts/create_admin.py`
- Test: `apps/api/tests/test_admin_script.py`

- [ ] **Step 1: 写脚本的失败测试**

Create `apps/api/tests/test_admin_script.py`:

```python
from sqlalchemy import select

from app.models import User
from scripts.create_admin import create_admin


def test_create_admin_creates_admin_user(db):
    create_admin(db, email="admin@test.com", password="AdminPass1!")
    user = db.scalar(select(User).where(User.email == "admin@test.com"))
    assert user is not None
    assert user.role == "admin"
    assert user.is_superuser is True
    assert user.status == "active"


def test_create_admin_idempotent(db):
    create_admin(db, email="admin@test.com", password="AdminPass1!")
    # 第二次创建同邮箱应跳过（幂等），不报错
    create_admin(db, email="admin@test.com", password="Different2!")
    from sqlalchemy import select
    user = db.scalar(select(User).where(User.email == "admin@test.com"))
    # 密码不被覆盖
    from app.core.security import verify_password
    assert verify_password("AdminPass1!", user.password_hash)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_admin_script.py -v`
Expected: FAIL（`scripts.create_admin` 不存在）。

- [ ] **Step 3: 实现 `scripts/create_admin.py`**

Create `apps/api/scripts/__init__.py`（空）。

Create `apps/api/scripts/create_admin.py`:

```python
"""命令行创建首个管理员。

用法：
    cd apps/api
    uv run python -m scripts.create_admin --email admin@tiangong.com --password YourPass
"""

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User


def create_admin(db: Session, *, email: str, password: str) -> User:
    """创建管理员。幂等：若邮箱已存在则跳过。"""
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        print(f"管理员 {email} 已存在，跳过。")
        return existing
    admin = User(
        email=email,
        password_hash=hash_password(password),
        name="管理员",
        role="admin",
        is_superuser=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    print(f"管理员创建成功：{email} (id={admin.id})")
    return admin


def main():
    parser = argparse.ArgumentParser(description="创建首个管理员")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        create_admin(db, email=args.email, password=args.password)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_admin_script.py -v`
Expected: 2 passed。

- [ ] **Step 5: 验证命令行可用**

Run:
```bash
cd apps/api && uv run python -m scripts.create_admin --email admin@tiangong.local --password Admin123!
```
Expected: 输出"管理员创建成功"。

验证:
```bash
docker compose exec postgres psql -U tiangong -c "SELECT email, role, is_superuser FROM users;"
```
Expected: 看到 `admin@tiangong.local | admin | t`。

- [ ] **Step 6: Commit**

```bash
git add apps/api/scripts/ apps/api/tests/test_admin_script.py
git commit -m "feat: 命令行脚本创建首个管理员（幂等）"
```

---

## 任务 9：全局异常处理

**Files:**
- Modify: `apps/api/app/core/exceptions.py`（追加处理器注册函数）

- [ ] **Step 1: 写异常处理测试**

Create `apps/api/tests/test_error_handling.py`:

```python
def test_not_found_returns_404(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    res = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404
    data = res.json()
    assert data["code"] == "not_found"


def test_unauthorized_returns_401_without_detail(client):
    res = client.get("/api/v1/projects")
    assert res.status_code == 401
    assert res.json()["code"] == "unauthorized"


def test_validation_error_returns_422(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    # 空标题违反 min_length
    res = client.post("/api/v1/projects", json={"title": ""})
    assert res.status_code == 422
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_error_handling.py -v`
Expected: FAIL（`code` 字段缺失——尚未注册异常处理器）。

- [ ] **Step 3: 在 `exceptions.py` 追加注册函数**

在 `apps/api/app/core/exceptions.py` 末尾追加:

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，统一错误响应格式 {code, message}。"""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc):
        return JSONResponse(
            status_code=401,
            content={"code": "unauthorized", "message": "未登录或凭证失效"},
        )
```

- [ ] **Step 4: Commit（异常处理器在任务 10 main.py 装配后才生效，测试将随之通过）**

```bash
git add apps/api/app/core/exceptions.py apps/api/tests/test_error_handling.py
git commit -m "feat: 全局异常处理器（统一 {code, message} 响应格式）"
```

---

## 任务 10：main.py 装配 + 集成验证

**Files:**
- Create: `apps/api/app/main.py`
- Modify: 测试 fixtures 已包含

- [ ] **Step 1: 实现 `main.py`**

Create `apps/api/app/main.py`:

```python
import loguru
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers

settings = get_settings()

app = FastAPI(
    title="TianGong API",
    description="AI 驱动的专利交底书撰写智能体",
    version="0.1.0",
)

# CORS（前端跨域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # cookie 跨域必需
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理
register_exception_handlers(app)

# 路由
app.include_router(api_router)


@app.on_event("startup")
def on_startup():
    loguru.logger.info("TianGong API 启动")
```

- [ ] **Step 2: 运行全部测试**

Run: `cd apps/api && uv run pytest -v`
Expected: 全部 passed（含 test_error_handling 现在通过）。

- [ ] **Step 3: 手动启动验证**

Run:
```bash
cd apps/api && uv run uvicorn app.main:app --reload
```

打开浏览器访问 `http://localhost:8000/docs`，确认：
- 看到 Swagger UI
- `/api/v1/health` 返回 `{"status":"ok"}`
- `/api/v1/auth/register` 可用

- [ ] **Step 4: 验证端到端流程**

在 Swagger UI 或用 curl:
```bash
# 注册
curl -c cookies.txt -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"e2e@test.com","password":"Pass1234!","name":"E2E"}'

# 登录
curl -c cookies.txt -b cookies.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"e2e@test.com","password":"Pass1234!"}'

# 创建项目
curl -b cookies.txt -X POST http://localhost:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"title":"端到端测试发明"}'

# 列项目
curl -b cookies.txt http://localhost:8000/api/v1/projects
```
Expected: 注册→登录→创建项目→列表返回刚创建的项目，全程无报错。

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/main.py
git commit -m "feat: FastAPI 应用装配（CORS + 异常处理 + 路由）+ 端到端验证通过"
```

- [ ] **Step 6: 最终全量测试 + 覆盖率检查**

Run:
```bash
cd apps/api && uv run pytest -v --tb=short
```
Expected: 所有测试通过。

确认无遗漏：
- `test_config.py` ✓
- `test_security.py` ✓
- `test_models.py` ✓
- `test_auth.py`（service 层）✓
- `test_auth_api.py`（API 层）✓
- `test_permissions.py` ✓
- `test_projects.py`（service + API）✓
- `test_admin_script.py` ✓
- `test_error_handling.py` ✓

---

## 完成标准

计划 1 完成后，应满足：

- [ ] `apps/api/` 目录结构完整，所有文件就位
- [ ] `docker compose up -d postgres` 可启动带 pgvector 的数据库
- [ ] `uv run alembic upgrade head` 可建表
- [ ] `uv run uvicorn app.main:app` 可启动，Swagger UI 可用
- [ ] 认证完整：注册/登录/登出/me，httpOnly cookie
- [ ] 项目 CRUD 完整：创建/列表/详情/更新/删除
- [ ] 资源级权限：他人项目返回 404
- [ ] 管理员校验：require_admin 返回 403
- [ ] 首个管理员可命令行创建
- [ ] 全部 pytest 测试通过

## 后续计划衔接

| 后续计划 | 本计划已预埋的接口 |
|---|---|
| 计划 3 模板 | Project.template_id 字段、SystemSetting 表 |
| 计划 4 AI 引擎 | User/Project 模型、认证、资源权限 |
| 计划 6 知识库 | pgvector 扩展已建、KnowledgeChunk 表待加 |
| 计划 7 管理/自定义配置 | User.role、SystemSetting、encrypt_value、require_admin |
