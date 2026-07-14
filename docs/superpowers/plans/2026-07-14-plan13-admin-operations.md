# 计划 13：管理后台运营闭环 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现管理员用户运营（封禁/解禁/重置密码 + 自我保护三条约束）、LLM 调用监控统计、管理员审计日志（含 api_key 脱敏），完成 P0 #29 + #30。

**Architecture:** 两个新日志表（`LLMCallLog` 仅元数据、`AuditLog` 含脱敏 detail）通过 Alembic 迁移落地。新增 `admin_service`（封禁/重置密码 + 审计 helper，自我保护约束在 service 层强制）+ `stats_service`（SQL 聚合，绝不返回 LLM 内容）。`api/admin.py` 增 4 个写/读端点；`api/ai.py` 三个 SSE 端点（plan 9 已改 async）在 `generate()` 完成或异常时写 `LLMCallLog`。前端 `admin/page.tsx` 增封禁/重置按钮 + 统计面板 + 审计表。

**Tech Stack:** FastAPI · SQLAlchemy 2.0（Mapped/mapped_column）· Alembic · Pydantic v2 · bcrypt · Next.js 16 · React 19 · @tanstack/react-query

**Spec reference:** `docs/superpowers/specs/2026-07-14-p0-completion-iteration.md` §8（计划 13）
- 8.1 用户运营（#29，设计 8.2③）：PATCH status + POST reset-password + 自我保护三条
- 8.2 监控运维（#30，设计 8.2④）：LLMCallLog + `GET /admin/stats/llm`，设计 8.3 红线「只看元数据不看内容」
- 8.3 审计日志（#30，设计 8.2⑤）：AuditLog + `GET /admin/audit-logs`，detail 脱敏不存 api_key 明文

---

## 关键约束（贯穿全计划）

1. **设计 8.3 红线**：管理员看到的 LLM 调用数据只含 `duration_ms / token / status / model / user(email)`，绝不返回 prompt/completion 内容。`LLMCallLog` 模型本身就不存内容字段。
2. **自我保护三条**（service 层强制，全部要测）：
   - 不能封禁/重置自己（`target_id == actor.id` → 403/ForbiddenError）
   - 不能封禁 `is_superuser=True`（命令行超管）→ 403
   - 不能封禁其他 `role=="admin"` → 403
3. **审计脱敏**：`AuditLog.detail` 绝不存 `api_key` 明文；全局 LLM 变更只记 `{model, base_url, enabled}`。必须测。
4. **日志表不随用户删除**：`LLMCallLog.user_id` 无 FK（或 FK SET NULL），`AuditLog.actor_id` FK SET NULL + `actor_email` 冗余（用户删除后审计仍可查）。
5. **plan 9 已把 `api/ai.py` 三个端点改 async**（`astream_chat/generate/rewrite` + `_yield_with_heartbeat`）。本计划 Task 6 在 async `generate()` 中插日志。
6. **GOTCHAS G2**：JSONB 字段必须用 `JSONType = JSONB().with_variant(JSON, "sqlite")`（已在 `app.models.base` 定义）。
7. **bcrypt G1**：`hash_password` 在 `app.core.security`，已在 auth_service 使用，直接 import。
8. **测试命令**：`cd apps/api && uv run pytest <path> -v`。alembic 用 `uv run alembic`。

---

## 文件结构

| 层 | 文件 | 责任 | 改动 |
|---|---|---|---|
| 模型 | `apps/api/app/models/llm_call_log.py` | LLM 调用元数据记录 | 新建 |
| 模型 | `apps/api/app/models/audit_log.py` | 管理员操作审计（脱敏 detail） | 新建 |
| 模型 | `apps/api/app/models/__init__.py` | 注册新模型到 `__all__` | 修改 |
| 迁移 | `apps/api/alembic/versions/<id>_add_llm_call_logs.py` | 建表 `llm_call_logs` | 新建（autogenerate） |
| 迁移 | `apps/api/alembic/versions/<id>_add_audit_logs.py` | 建表 `audit_logs` | 新建（autogenerate） |
| 服务 | `apps/api/app/services/admin_service.py` | 封禁/重置密码 + 自我保护 + 审计 helper | 新建 |
| 服务 | `apps/api/app/services/stats_service.py` | LLM 调用 SQL 聚合 | 新建 |
| API | `apps/api/app/api/admin.py` | PATCH status / POST reset-password / GET stats / GET audit-logs + set_global_llm 审计 | 修改 |
| API | `apps/api/app/api/ai.py` | 三个 SSE 端点 generate() 写 LLMCallLog | 修改 |
| 前端 | `apps/web/src/types/api.ts` | 新增 LLMStats / AuditLog 类型 | 修改 |
| 前端 | `apps/web/src/lib/api.ts` | 新增 listLLMStats / listAuditLogs / banUser / resetUserPassword | 修改 |
| 前端 | `apps/web/src/app/(app)/admin/page.tsx` | 封禁/重置按钮 + 统计面板 + 审计表 | 修改 |
| 测试 | `apps/api/tests/test_admin.py` | 封禁/重置/自我保护/统计/审计/脱敏 | 新建 |

---

## Task 1：LLMCallLog 模型 + 迁移

**Files:**
- Create: `apps/api/app/models/llm_call_log.py`
- Modify: `apps/api/app/models/__init__.py`
- Create: `apps/api/alembic/versions/<id>_add_llm_call_logs.py`（autogenerate）

- [ ] **Step 1: 写失败测试 — 模型可在 sqlite 建表并插入**

Create `apps/api/tests/test_llm_call_log_model.py`:

```python
"""LLMCallLog 模型测试。"""

from datetime import datetime, timezone

from app.models import Base, LLMCallLog


def test_llm_call_log_model_importable():
    """模型可从 app.models 导入。"""
    assert LLMCallLog is not None
    assert LLMCallLog.__tablename__ == "llm_call_logs"


def test_llm_call_log_create_row(db_session):
    """可插入一条记录，字段持久化（user_id/project_id 可空，无 FK 级联）。"""
    log = LLMCallLog(
        user_id=None,
        project_id=None,
        action="chat",
        model="glm-4-flash",
        provider="global",
        token_prompt=None,
        token_completion=None,
        duration_ms=123,
        status="success",
        error=None,
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)

    assert log.id is not None
    assert log.action == "chat"
    assert log.duration_ms == 123
    assert log.status == "success"
    assert log.created_at is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_llm_call_log_model.py -v`
Expected: FAIL（`ImportError: cannot import name 'LLMCallLog' from 'app.models'`）

- [ ] **Step 3: 创建模型文件**

Create `apps/api/app/models/llm_call_log.py`:

```python
"""LLM 调用日志（仅元数据，设计 8.3 红线：绝不存 prompt/completion 内容）。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


class LLMCallLog(Base, IdMixin):
    __tablename__ = "llm_call_logs"

    # 无 FK 级联：日志需独立留存；user_id 可空（全局配置时无归属用户概念）
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(50))  # chat/generate/rewrite/review/embed
    model: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(20))  # user/global
    token_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # success/failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 不含内容
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
```

- [ ] **Step 4: 注册到 models/__init__.py**

Modify `apps/api/app/models/__init__.py` — 在 import 区加一行，`__all__` 加一项：

```python
from app.models.base import Base, JSONType
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.llm_call_log import LLMCallLog
from app.models.message import Message
from app.models.parse_job import ParseJob
from app.models.project import Project
from app.models.review_record import ReviewRecord
from app.models.review_rubric import ReviewRubric
from app.models.section import Section
from app.models.section_version import SectionVersion
from app.models.system_setting import SystemSetting
from app.models.template import Template
from app.models.user import User
from app.models.user_llm_config import UserLLMConfig

__all__ = [
    "Base", "JSONType",
    "User", "Project", "SystemSetting",
    "Template", "ParseJob", "Section", "SectionVersion", "Message",
    "KnowledgeChunk", "ReviewRubric", "ReviewRecord", "UserLLMConfig",
    "LLMCallLog",
]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_llm_call_log_model.py -v`
Expected: 2 passed

- [ ] **Step 6: 生成迁移**

Run:
```bash
cd apps/api && uv run alembic revision --autogenerate -m "add llm_call_logs"
```
Expected: 生成 `alembic/versions/<new_id>_add_llm_call_logs.py`，含 `op.create_table('llm_call_logs', ...)`。**打开生成的文件确认**：`down_revision` 指向当前 head（plan 13 开始时为 `a20f16f0da4e`，若更早计划已推进 head 则指向当时 head）；表结构含 `user_id`/`project_id`(FK SET NULL)/各字段 + `ix_llm_call_logs_user_id`/`ix_llm_call_logs_project_id`/`ix_llm_call_logs_created_at` 索引。**确认无内容字段（prompt/completion）残留**。

- [ ] **Step 7: 应用迁移验证**

Run:
```bash
cd apps/api && uv run alembic upgrade head
```
Expected: `Running upgrade a20f16f0da4e -> <new_id>, add llm_call_logs`（down_revision 按实际显示）。无报错。

- [ ] **Step 8: 回滚 + 重应用验证可逆**

Run:
```bash
cd apps/api && uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: 先 downgrade 删表，再 upgrade 建表，均无报错。

- [ ] **Step 9: 提交**

```bash
cd apps/api && git add app/models/llm_call_log.py app/models/__init__.py alembic/versions/*_add_llm_call_logs.py tests/test_llm_call_log_model.py
git commit -m "feat(plan13): LLMCallLog 模型 + 迁移"
```

---

## Task 2：AuditLog 模型 + 迁移

**Files:**
- Create: `apps/api/app/models/audit_log.py`
- Modify: `apps/api/app/models/__init__.py`
- Create: `apps/api/alembic/versions/<id>_add_audit_logs.py`（autogenerate）

- [ ] **Step 1: 写失败测试 — 模型可导入并插入，detail 为 JSON**

Create `apps/api/tests/test_audit_log_model.py`:

```python
"""AuditLog 模型测试。"""

from app.models import AuditLog, Base


def test_audit_log_model_importable():
    assert AuditLog is not None
    assert AuditLog.__tablename__ == "audit_logs"


def test_audit_log_create_row(db_session):
    """可插入审计记录，detail 为 JSON dict。"""
    log = AuditLog(
        actor_id=None,  # 测试中先不绑用户，验证字段可空写入
        actor_email="admin@example.com",
        action="set_global_llm",
        target_type="system_setting",
        target_id="llm_global_config",
        detail={"model": "glm-4-flash", "base_url": "https://x", "enabled": True},
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)

    assert log.id is not None
    assert log.action == "set_global_llm"
    assert log.detail["model"] == "glm-4-flash"
    # 关键：detail 中绝无 api_key
    assert "api_key" not in log.detail
    assert log.created_at is not None
```

注意：`actor_id` 此处先测可空（FK SET NULL），Task 3 会用真实用户。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_audit_log_model.py -v`
Expected: FAIL（`ImportError: cannot import name 'AuditLog'`）

- [ ] **Step 3: 创建模型文件**

Create `apps/api/app/models/audit_log.py`:

```python
"""审计日志：管理员操作记录（设计 8.2⑤）。

detail 绝不存 api_key 等敏感明文（脱敏在 service 层强制）。
actor_email 冗余存储：用户删除后审计仍可查。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType


class AuditLog(Base, IdMixin):
    __tablename__ = "audit_logs"

    # FK SET NULL：用户删除后审计保留，actor_email 冗余兜底
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_email: Mapped[str] = mapped_column(String(255))  # 冗余，防用户删除后查不到
    action: Mapped[str] = mapped_column(String(100))  # ban_user/reset_password/set_global_llm/...
    target_type: Mapped[str] = mapped_column(String(50))  # user/system_setting
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # 变更摘要，脱敏后
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
```

- [ ] **Step 4: 注册到 models/__init__.py**

Modify `apps/api/app/models/__init__.py` — import 区加（在 `llm_call_log` import 之后）：

```python
from app.models.audit_log import AuditLog
```

`__all__` 末尾加：

```python
    "LLMCallLog",
    "AuditLog",
]
```

完整 `__all__` 应为：

```python
__all__ = [
    "Base", "JSONType",
    "User", "Project", "SystemSetting",
    "Template", "ParseJob", "Section", "SectionVersion", "Message",
    "KnowledgeChunk", "ReviewRubric", "ReviewRecord", "UserLLMConfig",
    "LLMCallLog",
    "AuditLog",
]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_audit_log_model.py -v`
Expected: 2 passed

- [ ] **Step 6: 生成迁移**

Run:
```bash
cd apps/api && uv run alembic revision --autogenerate -m "add audit_logs"
```
Expected: 生成 `alembic/versions/<new_id>_add_audit_logs.py`。**打开确认**：`down_revision` 指向 Task 1 的新 head；表含 `actor_id`(FK SET NULL)/`actor_email`/`action`/`target_type`/`target_id`/`detail`(JSONB with sqlite variant)/`created_at` + `ix_audit_logs_actor_id`/`ix_audit_logs_created_at` 索引。

- [ ] **Step 7: 应用 + 回滚验证**

Run:
```bash
cd apps/api && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: 三步均无报错，最终 head 为 audit_logs 迁移。

- [ ] **Step 8: 提交**

```bash
cd apps/api && git add app/models/audit_log.py app/models/__init__.py alembic/versions/*_add_audit_logs.py tests/test_audit_log_model.py
git commit -m "feat(plan13): AuditLog 模型 + 迁移"
```

---

## Task 3：admin_service（封禁/重置 + 自我保护 + 审计 helper）

**Files:**
- Create: `apps/api/app/services/admin_service.py`
- Create: `apps/api/tests/test_admin_service.py`

自我保护三条约束在 service 层强制（抛 `ForbiddenError`），不依赖 API 层。

- [ ] **Step 1: 写失败测试 — 封禁/重置正常路径 + 自我保护三条**

Create `apps/api/tests/test_admin_service.py`:

```python
"""admin_service 测试：封禁/重置密码 + 自我保护 + 审计。"""

import uuid

import pytest

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import verify_password
from app.models import AuditLog, User
from app.services import admin_service


@pytest.fixture
def admin_user(db_session):
    """普通管理员（role=admin, is_superuser=False）。"""
    u = User(
        email="admin@example.com",
        password_hash="x",
        name="管理员",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def normal_user(db_session):
    u = User(
        email="user@example.com",
        password_hash="oldhash",
        name="普通用户",
        role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def superadmin(db_session):
    """命令行创建的超管（is_superuser=True）。"""
    u = User(
        email="root@example.com",
        password_hash="x",
        name="超管",
        role="admin",
        status="active",
        is_superuser=True,
    )
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def another_admin(db_session):
    u = User(
        email="admin2@example.com",
        password_hash="x",
        name="管理员2",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(u)
    db_session.commit()
    return u


# ── 封禁/解禁正常路径 ──

def test_ban_user_sets_status_disabled(db_session, admin_user, normal_user):
    admin_service.set_user_status(db_session, actor=admin_user, user_id=normal_user.id, status="disabled")
    db_session.refresh(normal_user)
    assert normal_user.status == "disabled"


def test_unban_user_sets_status_active(db_session, admin_user, normal_user):
    normal_user.status = "disabled"
    db_session.commit()
    admin_service.set_user_status(db_session, actor=admin_user, user_id=normal_user.id, status="active")
    db_session.refresh(normal_user)
    assert normal_user.status == "active"


def test_set_user_status_writes_audit_log(db_session, admin_user, normal_user):
    admin_service.set_user_status(db_session, actor=admin_user, user_id=normal_user.id, status="disabled")
    logs = list(db_session.scalars(__import__("sqlalchemy").select(AuditLog)))
    assert len(logs) == 1
    log = logs[0]
    assert log.action == "ban_user"
    assert log.target_type == "user"
    assert log.target_id == str(normal_user.id)
    assert log.actor_id == admin_user.id
    assert log.detail["status"] == "disabled"


# ── 自我保护 1：不能封禁/重置自己（ban + reset 都禁）──

def test_cannot_ban_self(db_session, admin_user):
    with pytest.raises(ForbiddenError):
        admin_service.set_user_status(
            db_session, actor=admin_user, user_id=admin_user.id, status="disabled"
        )


def test_cannot_reset_self(db_session, admin_user):
    with pytest.raises(ForbiddenError):
        admin_service.reset_user_password(
            db_session, actor=admin_user, user_id=admin_user.id, new_password="NewPass1!"
        )


# ── 自我保护 2：不能封禁超管（仅 ban；reset 放行——设计 8.1 仅禁封禁语义）──

def test_cannot_ban_superuser(db_session, admin_user, superadmin):
    with pytest.raises(ForbiddenError):
        admin_service.set_user_status(
            db_session, actor=admin_user, user_id=superadmin.id, status="disabled"
        )


def test_can_reset_superuser_password(db_session, admin_user, superadmin):
    """重置超管密码：设计 8.1 自我保护仅禁'封禁'语义，reset 放行。"""
    admin_service.reset_user_password(
        db_session, actor=admin_user, user_id=superadmin.id, new_password="NewPass1!"
    )
    db_session.refresh(superadmin)
    assert verify_password("NewPass1!", superadmin.password_hash)


# ── 自我保护 3：不能封禁其他管理员（仅 ban）──

def test_cannot_ban_other_admin(db_session, admin_user, another_admin):
    with pytest.raises(ForbiddenError):
        admin_service.set_user_status(
            db_session, actor=admin_user, user_id=another_admin.id, status="disabled"
        )


def test_can_reset_other_admin_password(db_session, admin_user, another_admin):
    """重置其他管理员密码：设计 8.1 仅禁封禁，reset 放行（不改账号可用性）。"""
    admin_service.reset_user_password(
        db_session, actor=admin_user, user_id=another_admin.id, new_password="NewPass1!"
    )
    db_session.refresh(another_admin)
    assert verify_password("NewPass1!", another_admin.password_hash)


# ── 重置密码正常路径 ──

def test_reset_password_updates_hash(db_session, admin_user, normal_user):
    admin_service.reset_user_password(
        db_session, actor=admin_user, user_id=normal_user.id, new_password="FreshPass9!"
    )
    db_session.refresh(normal_user)
    assert verify_password("FreshPass9!", normal_user.password_hash)
    assert normal_user.password_hash != "oldhash"


def test_reset_password_writes_audit_log(db_session, admin_user, normal_user):
    admin_service.reset_user_password(
        db_session, actor=admin_user, user_id=normal_user.id, new_password="FreshPass9!"
    )
    logs = list(db_session.scalars(__import__("sqlalchemy").select(AuditLog)))
    assert len(logs) == 1
    log = logs[0]
    assert log.action == "reset_password"
    assert log.target_type == "user"
    # 关键：detail 不含新密码明文
    assert "new_password" not in (log.detail or {})
    assert log.detail.get("reset") is True


# ── 404：用户不存在 ──

def test_set_status_user_not_found(db_session, admin_user):
    with pytest.raises(NotFoundError):
        admin_service.set_user_status(
            db_session, actor=admin_user, user_id=uuid.uuid4(), status="disabled"
        )


def test_reset_password_user_not_found(db_session, admin_user):
    with pytest.raises(NotFoundError):
        admin_service.reset_user_password(
            db_session, actor=admin_user, user_id=uuid.uuid4(), new_password="X"
        )


# ── 审计 helper ──

def test_audit_log_redacts_api_key(db_session, admin_user):
    """审计 helper 直接调用：detail 不含 api_key 明文。"""
    admin_service._audit(
        db_session,
        actor=admin_user,
        action="set_global_llm",
        target_type="system_setting",
        target_id="llm_global_config",
        detail={"model": "glm-4-flash", "base_url": "https://x", "enabled": True},
    )
    log = db_session.scalar(__import__("sqlalchemy").select(AuditLog))
    assert log is not None
    assert "api_key" not in (log.detail or {})
    assert log.detail["model"] == "glm-4-flash"
    assert log.actor_email == admin_user.email
```

注意：设计 8.1 自我保护三条针对「封禁」语义。`reset_user_password` 的约束比 ban 更宽——只禁「重置自己」（防误操作锁死自己），对超管和其他管理员放行（重置密码不改账号可用性，属正常运维）。`_get_and_guard` 通过 `action` 参数区分：`action=="ban"` 时三条全检查，`action=="reset"` 时只检查自身。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_admin_service.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.admin_service'`）

- [ ] **Step 3: 实现 admin_service.py**

Create `apps/api/app/services/admin_service.py`:

```python
"""管理员运营服务：封禁/解禁/重置密码 + 自我保护 + 审计 helper（设计 8.1/8.3）。

自我保护（设计 8.1，针对「封禁」语义）：
1. 不能封禁自己（ban: target.id == actor.id → 403）
2. 不能封禁超管（ban: target.is_superuser → 403）
3. 不能封禁其他管理员（ban: target.role == "admin" → 403）
重置密码约束更宽：仅禁「重置自己」（防误锁死自己），对超管/其他管理员放行。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models import AuditLog, User


def set_user_status(
    db: Session, *, actor: User, user_id: uuid.UUID, status: str
) -> User:
    """封禁/解禁用户。status ∈ {active, disabled}。"""
    if status not in ("active", "disabled"):
        raise ForbiddenError(f"非法状态值: {status}")
    target = _get_and_guard(db, actor=actor, user_id=user_id, action="ban")
    target.status = status
    db.commit()
    db.refresh(target)

    _audit(
        db,
        actor=actor,
        action="ban_user" if status == "disabled" else "unban_user",
        target_type="user",
        target_id=str(target.id),
        detail={"status": status, "target_email": target.email},
    )
    return target


def reset_user_password(
    db: Session, *, actor: User, user_id: uuid.UUID, new_password: str
) -> None:
    """重置用户密码。不返回响应（管理员线下告知）。"""
    if not new_password or len(new_password) < 1:
        raise ForbiddenError("新密码不能为空")
    # reset 仅禁自身（设计 8.1 自我保护只针对封禁语义；reset 不改账号可用性，对超管/其他管理员放行）
    target = _get_and_guard(db, actor=actor, user_id=user_id, action="reset")

    target.password_hash = hash_password(new_password)
    db.commit()

    _audit(
        db,
        actor=actor,
        action="reset_password",
        target_type="user",
        target_id=str(target.id),
        detail={"reset": True, "target_email": target.email},  # 不含新密码明文
    )


def _get_and_guard(db: Session, *, actor: User, user_id: uuid.UUID, action: str) -> User:
    """取目标用户 + 自我保护校验。action ∈ {ban, reset}。

    共同约束：不能操作自己（ban/reset 都禁自身）。
    ban 额外约束：不能封禁超管、不能封禁其他管理员。
    reset 对超管/其他管理员放行（重置密码不改账号可用性）。
    """
    target = db.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise NotFoundError("用户不存在")

    # 约束 1（ban + reset 共有）：不能操作自己
    if target.id == actor.id:
        raise ForbiddenError("不能对自己执行此操作")

    if action == "ban":
        # 约束 2：不能封禁超管
        if target.is_superuser:
            raise ForbiddenError("不能封禁超级管理员")
        # 约束 3：不能封禁其他管理员
        if target.role == "admin":
            raise ForbiddenError("不能封禁其他管理员")

    return target


def _audit(
    db: Session,
    *,
    actor: User,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict | None = None,
) -> AuditLog:
    """写审计日志。detail 必须已脱敏（调用方负责，绝不传 api_key 明文）。"""
    log = AuditLog(
        actor_id=actor.id,
        actor_email=actor.email,  # 冗余，防用户删除后查不到
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.add(log)
    db.commit()
    return log
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_admin_service.py -v`
Expected: 全部 PASS（共约 14 个测试）。若 `test_cannot_reset_other_admin_password` 相关失败，检查 `_get_and_guard` 的 `action=="ban"` 分支是否只对 ban 生效。

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/services/admin_service.py tests/test_admin_service.py
git commit -m "feat(plan13): admin_service 封禁/重置密码 + 自我保护 + 审计 helper"
```

---

## Task 4：admin API 端点（status PATCH + reset-password POST）

**Files:**
- Modify: `apps/api/app/api/admin.py`
- Create: `apps/api/tests/test_admin_api.py`

端点走 `require_admin`（已有）。请求体用 Pydantic 校验。

- [ ] **Step 1: 写失败测试 — 封禁/重置端点 + 自我保护 HTTP 表现**

Create `apps/api/tests/test_admin_api.py`:

```python
"""admin 用户运营 API 测试。"""

import uuid

import pytest

from app.core.security import hash_password, verify_password
from app.models import User


@pytest.fixture
def admin_and_login(client, db_session):
    """创建管理员并登录，返回 admin user。"""
    admin = User(
        email="admin@example.com",
        password_hash=hash_password("Admin1234!"),
        name="管理员",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(admin)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "Admin1234!",
    })
    return admin


@pytest.fixture
def target_user(db_session):
    u = User(
        email="target@example.com",
        password_hash=hash_password("OldPass1!"),
        name="目标用户",
        role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _patch_status(client, user_id, status):
    return client.patch(f"/api/v1/admin/users/{user_id}/status", json={"status": status})


def _reset_password(client, user_id, new_password):
    return client.post(f"/api/v1/admin/users/{user_id}/reset-password", json={"new_password": new_password})


def test_patch_status_ban_user(client, db_session, admin_and_login, target_user):
    res = _patch_status(client, target_user.id, "disabled")
    assert res.status_code == 200
    assert res.json()["status"] == "disabled"
    db_session.expire_all()
    u = db_session.get(User, target_user.id)
    assert u.status == "disabled"


def test_patch_status_unban_user(client, db_session, admin_and_login, target_user):
    target_user.status = "disabled"
    db_session.commit()
    res = _patch_status(client, target_user.id, "active")
    assert res.status_code == 200
    assert res.json()["status"] == "active"


def test_reset_password_endpoint(client, db_session, admin_and_login, target_user):
    res = _reset_password(client, target_user.id, "BrandNew9!")
    assert res.status_code == 200
    db_session.expire_all()
    u = db_session.get(User, target_user.id)
    assert verify_password("BrandNew9!", u.password_hash)


def test_cannot_ban_self_returns_403(client, admin_and_login):
    res = _patch_status(client, admin_and_login.id, "disabled")
    assert res.status_code == 403
    assert res.json()["code"] == "forbidden"


def test_cannot_reset_self_returns_403(client, admin_and_login):
    res = _reset_password(client, admin_and_login.id, "AnyPass1!")
    assert res.status_code == 403


def test_cannot_ban_superuser_returns_403(client, admin_and_login, db_session):
    superadmin = User(
        email="root@example.com",
        password_hash="x",
        name="超管",
        role="admin",
        status="active",
        is_superuser=True,
    )
    db_session.add(superadmin)
    db_session.commit()
    res = _patch_status(client, superadmin.id, "disabled")
    assert res.status_code == 403


def test_cannot_ban_other_admin_returns_403(client, admin_and_login, db_session):
    other_admin = User(
        email="admin2@example.com",
        password_hash="x",
        name="管理员2",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(other_admin)
    db_session.commit()
    res = _patch_status(client, other_admin.id, "disabled")
    assert res.status_code == 403


def test_patch_status_user_not_found_404(client, admin_and_login):
    res = _patch_status(client, uuid.uuid4(), "disabled")
    assert res.status_code == 404


def test_normal_user_cannot_access_ban(client, registered_user, target_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = _patch_status(client, target_user.id, "disabled")
    assert res.status_code == 403
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_admin_api.py -v`
Expected: FAIL（`404` 或路由不存在 / `AttributeError`，因 admin.py 还没 PATCH/POST 端点）

- [ ] **Step 3: 在 admin.py 加两个端点**

Modify `apps/api/app/api/admin.py` — 在 `list_users` 函数之后、`GlobalLLMSettings` 类之前插入。先加 import：在文件顶部 import 区改：

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user, require_admin
from app.models import Project, User, UserLLMConfig
from app.services import admin_service, llm_config_service
```

然后在 `list_users` return 之后插入两个端点：

```python
# ── 管理员：用户运营（封禁/解禁/重置密码，设计 8.1）──

class UserStatusUpdate(BaseModel):
    status: str  # active / disabled


class PasswordReset(BaseModel):
    new_password: str


@router.patch("/admin/users/{user_id}/status")
def update_user_status(
    user_id: str,
    payload: UserStatusUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """封禁/解禁用户。自我保护在 service 层强制。"""
    import uuid as _uuid
    target = admin_service.set_user_status(
        db, actor=admin, user_id=_uuid.UUID(user_id), status=payload.status,
    )
    return {"id": str(target.id), "status": target.status}


@router.post("/admin/users/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    payload: PasswordReset,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """重置用户密码（管理员线下告知，不返回敏感信息）。"""
    import uuid as _uuid
    admin_service.reset_user_password(
        db, actor=admin, user_id=_uuid.UUID(user_id), new_password=payload.new_password,
    )
    return {"ok": True}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_admin_api.py -v`
Expected: 全部 PASS（9 个测试）。

- [ ] **Step 5: 跑全量回归确认无破坏**

Run: `cd apps/api && uv run pytest -q`
Expected: 全部 PASS（含既有 admin/permissions 测试）。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/api/admin.py tests/test_admin_api.py
git commit -m "feat(plan13): PATCH status + POST reset-password 端点 + 自我保护测试"
```

---

## Task 5：审计日志接入 set_global_llm + ban + reset（含 api_key 脱敏测试）

**Files:**
- Modify: `apps/api/app/api/admin.py`（set_global_llm 加审计）
- Modify: `apps/api/tests/test_admin_api.py`（追加脱敏测试）

ban/reset 的审计已在 Task 3 service 层写入。本任务补 `set_global_llm`（它调 `llm_config_service`，不走 `admin_service`，需在 API 层调 `_audit`）。为保持审计入口统一，把 `_audit` 从 admin_service 暴露或在 API 层复用。

- [ ] **Step 1: 写失败测试 — set_global_llm 写审计且 detail 不含 api_key**

追加到 `apps/api/tests/test_admin_api.py` 末尾：

```python
def test_set_global_llm_writes_audit_without_api_key(client, admin_and_login, db_session):
    """设置全局 LLM 后，审计日志记录变更但 detail 绝不含 api_key 明文。"""
    res = client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "sk-super-secret-key-1234567890",
        "model": "glm-4-flash",
    })
    assert res.status_code == 200

    from app.models import AuditLog
    from sqlalchemy import select
    logs = list(db_session.scalars(select(AuditLog).where(AuditLog.action == "set_global_llm")))
    assert len(logs) == 1
    log = logs[0]
    detail = log.detail or {}
    # 关键脱敏断言
    assert "api_key" not in detail
    assert "api_key_encrypted" not in detail
    assert "sk-super-secret-key-1234567890" not in str(detail)
    # 记录了变更摘要
    assert detail.get("model") == "glm-4-flash"
    assert detail.get("base_url") == "https://open.bigmodel.cn/api/paas/v4"
    assert detail.get("enabled") is True
    assert log.actor_email == admin_and_login.email
    assert log.target_type == "system_setting"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_admin_api.py::test_set_global_llm_writes_audit_without_api_key -v`
Expected: FAIL（`assert len(logs) == 1` 失败，因 set_global_llm 还没写审计 → logs 为空）

- [ ] **Step 3: 在 set_global_llm 端点加审计**

Modify `apps/api/app/api/admin.py` 的 `set_global_llm` 函数。当前实现：

```python
@router.put("/admin/llm-config")
def set_global_llm(
    payload: GlobalLLMSettings,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return llm_config_service.set_global_llm_settings(
        db, enabled=payload.enabled,
        base_url=payload.base_url, api_key=payload.api_key, model=payload.model,
    )
```

替换为（执行后写审计，detail 只含 model/base_url/enabled，绝不传 api_key）：

```python
@router.put("/admin/llm-config")
def set_global_llm(
    payload: GlobalLLMSettings,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = llm_config_service.set_global_llm_settings(
        db, enabled=payload.enabled,
        base_url=payload.base_url, api_key=payload.api_key, model=payload.model,
    )
    # 审计：detail 只记非敏感字段，绝不传 api_key 明文（设计 8.3 脱敏）
    admin_service._audit(
        db,
        actor=admin,
        action="set_global_llm",
        target_type="system_setting",
        target_id="llm_global_config",
        detail={
            "enabled": payload.enabled,
            "base_url": payload.base_url,
            "model": payload.model,
        },
    )
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_admin_api.py::test_set_global_llm_writes_audit_without_api_key -v`
Expected: PASS

- [ ] **Step 5: 跑 Task 3/4 全部审计相关测试确认无回归**

Run: `cd apps/api && uv run pytest tests/test_admin_service.py tests/test_admin_api.py -v`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/api/admin.py tests/test_admin_api.py
git commit -m "feat(plan13): set_global_llm 审计日志 + api_key 脱敏"
```

---

## Task 6：ai.py 三个 SSE 端点写 LLMCallLog

**Files:**
- Modify: `apps/api/app/api/ai.py`
- Modify: `apps/api/tests/test_ai.py`（若不存在则参考 plan 9 已建）

**前提**：plan 9 已把 `ai.py` 三个端点改 async（`astream_chat/generate/rewrite` + `_yield_with_heartbeat` + `async def generate()` + `asyncio.CancelledError` 分支）。本任务在 `generate()` 的 `finally`/`except` 写日志。

**MVP 简化**（设计 8.2④ 已认可）：token 字段先记 None（精确 usage 需把 LangChain chunk 透传，工程量大且非运营关键）。记 `action / model / provider / duration_ms / status / error`——这些是运营关键。`provider` 通过 `llm_config_service.resolve_llm_config` 的 `source` 字段判断（`user`/`global`），解析失败记 `global`。

- [ ] **Step 1: 写失败测试 — chat 成功写 LLMCallLog**

追加到 `apps/api/tests/test_ai.py` 末尾（复用 plan 9 的 `_make_logged_in_section` helper，若该 helper 不存在则用下面内联版）：

```python
def test_chat_writes_llm_call_log_on_success(client, registered_user, db_session, monkeypatch):
    """chat 端点成功完成时写一条 LLMCallLog（status=success）。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_chat(db, sec, history, msg):
        yield "hello"

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert "event: done" in res.text

    from app.models import LLMCallLog
    from sqlalchemy import select
    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "chat")))
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "success"
    assert log.action == "chat"
    assert log.user_id is not None
    assert log.project_id == section.project_id
    assert log.duration_ms is not None and log.duration_ms >= 0
    assert log.error is None
    # 红线：绝不存 prompt/completion 内容
    assert not hasattr(log, "prompt")
    assert not hasattr(log, "completion")


def test_generate_writes_llm_call_log_on_success(client, registered_user, db_session, monkeypatch):
    """generate 端点成功完成时写一条 LLMCallLog。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_generate(db, sec, history):
        yield "# 标题"

    monkeypatch.setattr("app.api.ai.astream_generate", fake_astream_generate)

    res = client.post(f"/api/v1/sections/{section.id}/generate")
    assert res.status_code == 200
    assert "event: done" in res.text

    from app.models import LLMCallLog
    from sqlalchemy import select
    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "generate")))
    assert len(logs) == 1
    assert logs[0].status == "success"


def test_chat_writes_llm_call_log_on_failure(client, registered_user, db_session, monkeypatch):
    """chat 端点 LLM 异常时写一条 LLMCallLog（status=failed, error 记原因）。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    async def fake_astream_chat(db, sec, history, msg):
        raise RuntimeError("boom")
        yield  # 让它成为 async generator

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert "event: error" in res.text

    from app.models import LLMCallLog
    from sqlalchemy import select
    logs = list(db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "chat")))
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "failed"
    assert log.error is not None
    assert "boom" in log.error
```

若 `_make_logged_in_section` 不存在于 test_ai.py，在文件顶部 helper 区加（与 plan 9 一致）：

```python
def _make_logged_in_section(client, registered_user, db_session):
    """登录 + 建项目 + 返回第一个 section 对象（含真实 id）。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from app.models import User
    from sqlalchemy import select

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    p = create_project(db_session, user=user, title="测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    return sections[0]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_ai.py::test_chat_writes_llm_call_log_on_success tests/test_ai.py::test_generate_writes_llm_call_log_on_success tests/test_ai.py::test_chat_writes_llm_call_log_on_failure -v`
Expected: FAIL（`assert len(logs) == 1` → 0，因 ai.py 还没写日志）

- [ ] **Step 3: 在 ai.py 加日志 helper + 接入三个 generate()**

Modify `apps/api/app/api/ai.py`。

**3a. 顶部 import 区加**（保留 plan 9 已有 import，只追加）：

```python
import time

from app.models import LLMCallLog, Message, Section, User
from app.services import llm_config_service, section_service
```

（`Message/Section/User/section_service` 已有，只需补 `time`、`LLMCallLog`、`llm_config_service`。）

**3b. 在 `_get_section_with_history` 之后、`_yield_with_heartbeat` 之前加日志 helper**：

```python
def _resolve_provider(db: Session, user_id) -> str:
    """判断本次 LLM 调用走用户自配还是全局配置（用于日志 provider 字段）。"""
    try:
        cfg = llm_config_service.resolve_llm_config(db, user_id=user_id)
        if cfg is not None:
            return cfg.source  # "user" / "global"
    except Exception:
        pass
    return "global"


def _resolve_model(db: Session, user_id) -> str:
    """取生效 model 名（用于日志 model 字段）。失败回退 settings.glm_model。"""
    try:
        cfg = llm_config_service.resolve_llm_config(db, user_id=user_id)
        if cfg is not None and cfg.model:
            return cfg.model
    except Exception:
        pass
    from app.core.config import get_settings
    return get_settings().glm_model


def _log_llm_call(
    db: Session, *,
    user_id, project_id, action: str, model: str, provider: str,
    status: str, tokens=None, duration_ms=None, error=None,
) -> None:
    """写一条 LLM 调用元数据日志（设计 8.3 红线：只存元数据，不存内容）。

    MVP 简化：token 先记 None（精确 usage 需透传 LangChain chunk.usage_metadata）。
    """
    try:
        log = LLMCallLog(
            user_id=user_id,
            project_id=project_id,
            action=action,
            model=model,
            provider=provider,
            token_prompt=tokens.get("prompt") if tokens else None,
            token_completion=tokens.get("completion") if tokens else None,
            duration_ms=duration_ms,
            status=status,
            error=(str(error)[:500] if error else None),
        )
        db.add(log)
        db.commit()
    except Exception:
        # 日志失败不阻断主流程（已 yield 给用户的内容不丢）
        db.rollback()
```

**3c. 改 chat 端点的 `generate()`**（plan 9 版本基础上加计时 + 日志）。把 chat 的 `async def generate():` 整体替换为：

```python
    async def generate():
        full_response = ""
        start = time.monotonic()
        status = "success"
        err = None
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_chat(db, section, history, payload.message)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    full_response += text
                    yield _sse_event("token", {"text": text})
            ai_msg = Message(section_id=section.id, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()
            yield _sse_event("done", {"message_id": str(ai_msg.id)})
        except asyncio.CancelledError:
            # 客户端断开：已生成的部分存为 assistant message（断线保留）
            if full_response:
                db.add(Message(section_id=section.id, role="assistant", content=full_response))
                db.commit()
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})
        finally:
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=section.project_id,
                action="chat",
                model=_resolve_model(db, current_user.id),
                provider=_resolve_provider(db, current_user.id),
                status=status,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )
```

**3d. 改 generate_draft 端点的 `generate()`** 整体替换为：

```python
    async def generate():
        full_md = ""
        start = time.monotonic()
        status = "success"
        err = None
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_generate(db, section, history)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    full_md += text
                    yield _sse_event("token", {"text": text})
            from app.ai.markdown_to_tiptap import markdown_to_tiptap
            section.content = markdown_to_tiptap(full_md)
            if section.status == "empty":
                section.status = "drafting"
            db.commit()
            yield _sse_event("done", {"section_id": str(section.id)})
        except asyncio.CancelledError:
            # 客户端断开：仅当 section 当前为空时落半截草稿
            if full_md and section.status == "empty":
                from app.ai.markdown_to_tiptap import markdown_to_tiptap
                section.content = markdown_to_tiptap(full_md)
                section.status = "drafting"
                db.commit()
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})
        finally:
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=section.project_id,
                action="generate",
                model=_resolve_model(db, current_user.id),
                provider=_resolve_provider(db, current_user.id),
                status=status,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )
```

**3e. 改 rewrite 端点的 `generate()`** 整体替换为：

```python
    async def generate():
        start = time.monotonic()
        status = "success"
        err = None
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_rewrite(section, payload.selected_text, payload.instruction)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    yield _sse_event("token", {"text": text})
            yield _sse_event("done", {})
        except asyncio.CancelledError:
            status = "failed"
            err = "client_cancelled"
            raise
        except Exception as e:
            status = "failed"
            err = e
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})
        finally:
            _log_llm_call(
                db,
                user_id=current_user.id,
                project_id=section.project_id,
                action="rewrite",
                model=_resolve_model(db, current_user.id),
                provider=_resolve_provider(db, current_user.id),
                status=status,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=err,
            )
```

- [ ] **Step 4: 跑新测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_ai.py::test_chat_writes_llm_call_log_on_success tests/test_ai.py::test_generate_writes_llm_call_log_on_success tests/test_ai.py::test_chat_writes_llm_call_log_on_failure -v`
Expected: 3 passed。

- [ ] **Step 5: 跑 ai 全量回归确认 plan 9 行为未破坏**

Run: `cd apps/api && uv run pytest tests/test_ai.py -v`
Expected: 全部 PASS（含 plan 9 的心跳/断线测试 + 新日志测试）。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/api/ai.py tests/test_ai.py
git commit -m "feat(plan13): ai.py 三个 SSE 端点写 LLMCallLog"
```

---

## Task 7：stats_service + GET /admin/stats/llm 端点

**Files:**
- Create: `apps/api/app/services/stats_service.py`
- Create: `apps/api/tests/test_stats_service.py`
- Modify: `apps/api/app/api/admin.py`

SQL 聚合：按 day/model/user 聚合，返回总调用数、总 token、平均耗时、失败率。**绝不返回 LLM 内容**（模型本身无内容字段，天然满足红线）。

- [ ] **Step 1: 写失败测试 — 聚合正确 + 无内容字段**

Create `apps/api/tests/test_stats_service.py`:

```python
"""stats_service 测试：LLM 调用聚合统计。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import LLMCallLog, User
from app.services import stats_service


@pytest.fixture
def admin_user(db_session):
    u = User(
        email="admin@example.com", password_hash="x", name="管理员",
        role="admin", status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _make_log(db_session, *, user_id, action="chat", model="glm-4-flash",
              provider="global", status="success", duration_ms=100,
              token_prompt=None, token_completion=None, error=None, days_ago=0):
    from datetime import timedelta
    log = LLMCallLog(
        user_id=user_id, project_id=None, action=action, model=model,
        provider=provider, token_prompt=token_prompt, token_completion=token_completion,
        duration_ms=duration_ms, status=status, error=error,
    )
    db_session.add(log)
    db_session.commit()
    # 回填 created_at（sqlite func.now() 用不了 days_ago，手动改）
    log.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.commit()
    return log


def test_get_llm_stats_aggregates(db_session, admin_user):
    """聚合：3 条 success + 1 条 failed，按 model 分组。"""
    _make_log(db_session, user_id=admin_user.id, model="glm-4-flash", status="success", duration_ms=100)
    _make_log(db_session, user_id=admin_user.id, model="glm-4-flash", status="success", duration_ms=200)
    _make_log(db_session, user_id=admin_user.id, model="glm-4-flash", status="failed", duration_ms=50, error="boom")
    _make_log(db_session, user_id=admin_user.id, model="glm-4-air", status="success", duration_ms=300)

    stats = stats_service.get_llm_stats(db_session, days=7)
    # 顶层汇总
    assert stats["total_calls"] == 4
    assert stats["total_success"] == 3
    assert stats["total_failed"] == 1
    assert stats["avg_duration_ms"] == 162  # (100+200+50+300)/4
    # 按 model 分组
    by_model = {m["model"]: m for m in stats["by_model"]}
    assert by_model["glm-4-flash"]["calls"] == 3
    assert by_model["glm-4-flash"]["failed"] == 1
    assert by_model["glm-4-air"]["calls"] == 1


def test_get_llm_stats_days_filter(db_session, admin_user):
    """days=7 只含近 7 天，老记录不计。"""
    _make_log(db_session, user_id=admin_user.id, status="success", days_ago=3)
    _make_log(db_session, user_id=admin_user.id, status="success", days_ago=30)  # 超出窗口

    stats = stats_service.get_llm_stats(db_session, days=7)
    assert stats["total_calls"] == 1


def test_get_llm_stats_by_user_shows_email_not_content(db_session, admin_user):
    """按用户聚合：显示 email + 计数，绝不返回 prompt/completion 内容字段。"""
    _make_log(db_session, user_id=admin_user.id, status="success")

    stats = stats_service.get_llm_stats(db_session, days=7)
    by_user = stats["by_user"]
    assert len(by_user) == 1
    row = by_user[0]
    assert row["email"] == "admin@example.com"
    assert row["calls"] == 1
    # 红线：返回结构里绝无 prompt/completion/content 字段
    for key in row:
        assert "prompt" not in key.lower()
        assert "completion" not in key.lower()
        assert "content" not in key.lower()


def test_get_llm_stats_empty(db_session):
    """无数据时返回零值结构，不报错。"""
    stats = stats_service.get_llm_stats(db_session, days=7)
    assert stats["total_calls"] == 0
    assert stats["total_success"] == 0
    assert stats["total_failed"] == 0
    assert stats["by_model"] == []
    assert stats["by_user"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_stats_service.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.stats_service'`）

- [ ] **Step 3: 实现 stats_service.py**

Create `apps/api/app/services/stats_service.py`:

```python
"""LLM 调用统计聚合（设计 8.2④ + 8.3 红线：只返回元数据聚合，不碰内容）。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import LLMCallLog, User


def get_llm_stats(db: Session, *, days: int = 7) -> dict:
    """聚合近 N 天 LLM 调用。

    返回结构（全部为元数据聚合，无 prompt/completion 内容）：
    {
      "days": 7,
      "total_calls": int,
      "total_success": int,
      "total_failed": int,
      "avg_duration_ms": float | None,
      "by_model": [{"model","calls","success","failed","avg_duration_ms"}],
      "by_user": [{"user_id","email","calls","success","failed"}],
    }
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 顶层汇总
    top = db.execute(
        select(
            func.count(LLMCallLog.id).label("total_calls"),
            func.sum(case((LLMCallLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((LLMCallLog.status != "success", 1), else_=0)).label("failed"),
            func.avg(LLMCallLog.duration_ms).label("avg_duration"),
        ).where(LLMCallLog.created_at >= since)
    ).one()
    total_calls = top.total_calls or 0
    total_success = int(top.success or 0)
    total_failed = int(top.failed or 0)
    avg_duration = float(top.avg_duration) if top.avg_duration is not None else None

    # 按 model 聚合
    model_rows = db.execute(
        select(
            LLMCallLog.model.label("model"),
            func.count(LLMCallLog.id).label("calls"),
            func.sum(case((LLMCallLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((LLMCallLog.status != "success", 1), else_=0)).label("failed"),
            func.avg(LLMCallLog.duration_ms).label("avg_duration"),
        )
        .where(LLMCallLog.created_at >= since)
        .group_by(LLMCallLog.model)
        .order_by(func.count(LLMCallLog.id).desc())
    ).all()
    by_model = [
        {
            "model": r.model,
            "calls": int(r.calls or 0),
            "success": int(r.success or 0),
            "failed": int(r.failed or 0),
            "avg_duration_ms": float(r.avg_duration) if r.avg_duration is not None else None,
        }
        for r in model_rows
    ]

    # 按用户聚合（user_id LEFT JOIN users 取 email；user_id 为 null 归到 anonymous）
    user_rows = db.execute(
        select(
            LLMCallLog.user_id.label("user_id"),
            User.email.label("email"),
            func.count(LLMCallLog.id).label("calls"),
            func.sum(case((LLMCallLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((LLMCallLog.status != "success", 1), else_=0)).label("failed"),
        )
        .select_from(LLMCallLog)
        .outerjoin(User, User.id == LLMCallLog.user_id)
        .where(LLMCallLog.created_at >= since)
        .group_by(LLMCallLog.user_id, User.email)
        .order_by(func.count(LLMCallLog.id).desc())
    ).all()
    by_user = [
        {
            "user_id": str(r.user_id) if r.user_id is not None else None,
            "email": r.email or "(anonymous)",
            "calls": int(r.calls or 0),
            "success": int(r.success or 0),
            "failed": int(r.failed or 0),
        }
        for r in user_rows
    ]

    return {
        "days": days,
        "total_calls": total_calls,
        "total_success": total_success,
        "total_failed": total_failed,
        "avg_duration_ms": avg_duration,
        "by_model": by_model,
        "by_user": by_user,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_stats_service.py -v`
Expected: 4 passed。

- [ ] **Step 5: 加 GET /admin/stats/llm 端点**

Modify `apps/api/app/api/admin.py` — import 区补 `stats_service`：

```python
from app.services import admin_service, llm_config_service, stats_service
```

在 `reset_user_password` 端点之后加：

```python
# ── 管理员：LLM 调用统计（设计 8.2④，仅元数据聚合）──

@router.get("/admin/stats/llm")
def get_llm_stats_endpoint(
    days: int = 7,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """LLM 调用统计聚合（绝不返回 prompt/completion 内容）。"""
    if days < 1 or days > 90:
        days = 7
    return stats_service.get_llm_stats(db, days=days)
```

- [ ] **Step 6: 写 API 测试 — 端点 + 权限**

追加到 `apps/api/tests/test_admin_api.py` 末尾：

```python
def test_get_llm_stats_endpoint_admin_ok(client, admin_and_login, db_session):
    """管理员可访问统计端点。"""
    from app.models import LLMCallLog
    import uuid as _uuid
    log = LLMCallLog(
        user_id=admin_and_login.id, project_id=None, action="chat",
        model="glm-4-flash", provider="global", duration_ms=100, status="success",
    )
    db_session.add(log)
    db_session.commit()

    res = client.get("/api/v1/admin/stats/llm?days=7")
    assert res.status_code == 200
    data = res.json()
    assert data["total_calls"] == 1
    assert data["total_success"] == 1
    assert len(data["by_model"]) == 1
    # 红线：响应里绝无内容字段
    assert "prompt" not in data
    assert "completion" not in data


def test_get_llm_stats_endpoint_normal_user_forbidden(client, registered_user):
    """普通用户 403。"""
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.get("/api/v1/admin/stats/llm")
    assert res.status_code == 403
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_admin_api.py::test_get_llm_stats_endpoint_admin_ok tests/test_admin_api.py::test_get_llm_stats_endpoint_normal_user_forbidden tests/test_stats_service.py -v`
Expected: 全部 PASS。

- [ ] **Step 8: 提交**

```bash
cd apps/api && git add app/services/stats_service.py app/api/admin.py tests/test_stats_service.py tests/test_admin_api.py
git commit -m "feat(plan13): stats_service + GET /admin/stats/llm 聚合端点"
```

---

## Task 8：GET /admin/audit-logs 端点

**Files:**
- Modify: `apps/api/app/api/admin.py`
- Create: `apps/api/tests/test_audit_logs_api.py`

分页 + 时间倒序。复用 `AuditLog` 模型。

- [ ] **Step 1: 写失败测试 — 分页/倒序/权限**

Create `apps/api/tests/test_audit_logs_api.py`:

```python
"""GET /admin/audit-logs 端点测试。"""

import pytest

from app.core.security import hash_password
from app.models import AuditLog, User


@pytest.fixture
def admin_and_login(client, db_session):
    admin = User(
        email="admin@example.com", password_hash=hash_password("Admin1234!"),
        name="管理员", role="admin", status="active",
    )
    db_session.add(admin)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "Admin1234!",
    })
    return admin


def _seed_logs(db_session, admin, n=5):
    """插 n 条审计日志（created_at 递增，靠 func.now 实际略有差异）。"""
    from datetime import datetime, timedelta, timezone
    base = datetime.now(timezone.utc) - timedelta(minutes=n)
    for i in range(n):
        db_session.add(AuditLog(
            actor_id=admin.id, actor_email=admin.email,
            action="ban_user", target_type="user", target_id=f"user-{i}",
            detail={"status": "disabled"},
        ))
    db_session.commit()
    # 手动调 created_at 确保倒序可验证
    logs = list(db_session.scalars(__import__("sqlalchemy").select(AuditLog)))
    for i, log in enumerate(logs):
        log.created_at = base + timedelta(minutes=i)
    db_session.commit()


def test_audit_logs_paginated_newest_first(client, admin_and_login, db_session):
    _seed_logs(db_session, admin_and_login, n=5)

    res = client.get("/api/v1/admin/audit-logs?page=1&size=2")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert data["page"] == 1
    assert data["size"] == 2
    assert len(data["items"]) == 2
    # 倒序：第一条应是最后插入（最新 created_at）
    assert data["items"][0]["target_id"] == "user-4"
    assert data["items"][1]["target_id"] == "user-3"


def test_audit_logs_page2(client, admin_and_login, db_session):
    _seed_logs(db_session, admin_and_login, n=5)

    res = client.get("/api/v1/admin/audit-logs?page=2&size=2")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 2
    assert data["items"][0]["target_id"] == "user-2"


def test_audit_logs_default_pagination(client, admin_and_login, db_session):
    """不传 page/size 用默认值。"""
    _seed_logs(db_session, admin_and_login, n=3)
    res = client.get("/api/v1/admin/audit-logs")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_audit_logs_normal_user_forbidden(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.get("/api/v1/admin/audit-logs")
    assert res.status_code == 403


def test_audit_logs_redacted_detail_no_api_key(client, admin_and_login, db_session):
    """审计响应的 detail 绝不含 api_key（即便历史数据混入也应过滤）。"""
    db_session.add(AuditLog(
        actor_id=admin_and_login.id, actor_email=admin_and_login.email,
        action="set_global_llm", target_type="system_setting", target_id="llm_global_config",
        detail={"model": "glm-4-flash", "base_url": "https://x", "enabled": True},
    ))
    db_session.commit()

    res = client.get("/api/v1/admin/audit-logs")
    assert res.status_code == 200
    item = res.json()["items"][0]
    detail = item["detail"]
    assert "api_key" not in detail
    assert "api_key_encrypted" not in detail
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_audit_logs_api.py -v`
Expected: FAIL（404 或路由不存在，因还没加端点）

- [ ] **Step 3: 加 GET /admin/audit-logs 端点**

Modify `apps/api/app/api/admin.py` — 在 `get_llm_stats_endpoint` 之后加：

```python
# ── 管理员：审计日志列表（设计 8.2⑤）──

@router.get("/admin/audit-logs")
def list_audit_logs(
    page: int = 1,
    size: int = 50,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """审计日志列表（分页，时间倒序）。"""
    if page < 1:
        page = 1
    if size < 1 or size > 200:
        size = 50

    total = db.scalar(select(func.count(AuditLog.id))) or 0
    rows = list(db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ))
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": str(r.id),
                "actor_id": str(r.actor_id) if r.actor_id else None,
                "actor_email": r.actor_email,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
```

同时在 import 区补 `AuditLog`：

```python
from app.models import AuditLog, Project, User, UserLLMConfig
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_audit_logs_api.py -v`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/api/admin.py tests/test_audit_logs_api.py
git commit -m "feat(plan13): GET /admin/audit-logs 分页审计日志端点"
```

---

## Task 9：前端 admin 页（封禁/重置按钮 + 统计面板 + 审计表）

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/app/(app)/admin/page.tsx`

- [ ] **Step 1: 加类型**

Modify `apps/web/src/types/api.ts` — 在 `GlobalLLMSettings` interface 之后追加：

```typescript
export interface LLMStatsByModel {
  model: string
  calls: number
  success: number
  failed: number
  avg_duration_ms: number | null
}

export interface LLMStatsByUser {
  user_id: string | null
  email: string
  calls: number
  success: number
  failed: number
}

export interface LLMStats {
  days: number
  total_calls: number
  total_success: number
  total_failed: number
  avg_duration_ms: number | null
  by_model: LLMStatsByModel[]
  by_user: LLMStatsByUser[]
}

export interface AuditLogItem {
  id: string
  actor_id: string | null
  actor_email: string
  action: string
  target_type: string
  target_id: string | null
  detail: Record<string, unknown> | null
  created_at: string | null
}

export interface AuditLogPage {
  total: number
  page: number
  size: number
  items: AuditLogItem[]
}
```

- [ ] **Step 2: 加 API 方法**

Modify `apps/web/src/lib/api.ts` — 在 `setGlobalLLM` 之后（管理员区）追加：

```typescript
  banUser: (userId: string, status: 'active' | 'disabled') =>
    request<{ id: string; status: string }>(`/admin/users/${userId}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  resetUserPassword: (userId: string, newPassword: string) =>
    request<{ ok: boolean }>(`/admin/users/${userId}/reset-password`, { method: 'POST', body: JSON.stringify({ new_password: newPassword }) }),
  listLLMStats: (days = 7) =>
    request<import('@/types/api').LLMStats>(`/admin/stats/llm?days=${days}`),
  listAuditLogs: (page = 1, size = 50) =>
    request<import('@/types/api').AuditLogPage>(`/admin/audit-logs?page=${page}&size=${size}`),
```

- [ ] **Step 3: 改 admin/page.tsx — 用户列表加封禁/重置按钮 + 统计面板 + 审计表**

Replace `apps/web/src/app/(app)/admin/page.tsx` 全部内容为：

```tsx
'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import type { AdminUser, AuditLogItem, GlobalLLMSettings, LLMStats } from '@/types/api'

export default function AdminPage() {
  const qc = useQueryClient()
  const { data: users } = useQuery({ queryKey: ['admin-users'], queryFn: () => api.listUsers() })
  const { data: llmSettings } = useQuery({ queryKey: ['global-llm'], queryFn: () => api.getGlobalLLM() })
  const { data: stats } = useQuery({ queryKey: ['llm-stats'], queryFn: () => api.listLLMStats(7) })
  const { data: auditPage } = useQuery({ queryKey: ['audit-logs'], queryFn: () => api.listAuditLogs(1, 50) })

  const [enabled, setEnabled] = useState(true)
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [resetTarget, setResetTarget] = useState<{ id: string; name: string } | null>(null)
  const [newPassword, setNewPassword] = useState('')

  if (llmSettings && !baseUrl && llmSettings.global_config) {
    setEnabled(llmSettings.llm_global_enabled)
    setBaseUrl(llmSettings.global_config.base_url)
    setModel(llmSettings.global_config.model)
  }

  const saveLLM = useMutation({
    mutationFn: () =>
      api.setGlobalLLM({ enabled, base_url: baseUrl || undefined, api_key: apiKey || undefined, model: model || undefined }),
    onSuccess: () => { toast.success('全局 LLM 配置已更新'); qc.invalidateQueries({ queryKey: ['global-llm'] }); setApiKey('') },
    onError: () => toast.error('保存失败'),
  })

  const banMutation = useMutation({
    mutationFn: ({ userId, status }: { userId: string; status: 'active' | 'disabled' }) =>
      api.banUser(userId, status),
    onSuccess: (_d, vars) => {
      toast.success(vars.status === 'disabled' ? '已封禁' : '已解禁')
      qc.invalidateQueries({ queryKey: ['admin-users'] })
    },
    onError: () => toast.error('操作失败（可能受自我保护约束）'),
  })

  const resetMutation = useMutation({
    mutationFn: () => api.resetUserPassword(resetTarget!.id, newPassword),
    onSuccess: () => { toast.success('密码已重置，请线下告知用户'); setResetTarget(null); setNewPassword('') },
    onError: () => toast.error('重置失败'),
  })

  const usersList: AdminUser[] = users ?? []
  const auditItems: AuditLogItem[] = auditPage?.items ?? []
  const statsData: LLMStats | undefined = stats

  return (
    <PageShell>
      <PageHeader title="管理后台" description="用户运营 · 监控 · 审计" />

      <div className="py-6 space-y-8">
        {/* 用户列表 + 封禁/重置 */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">
            用户<span className="ml-2 text-[13px] font-normal text-muted-foreground">{usersList.length}</span>
          </h2>
          <Card className="overflow-hidden">
            <div className="divide-y">
              {usersList.map((u) => (
                <div key={u.id} className="flex items-center justify-between px-4 py-3">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-medium">{u.name}</span>
                      <span className="text-[13px] text-muted-foreground">{u.email}</span>
                      {u.role === 'admin' && <Badge>管理员</Badge>}
                      {u.status === 'disabled' && <Badge variant="destructive">已封禁</Badge>}
                    </div>
                    <p className="text-[12px] text-muted-foreground">
                      {u.project_count} 个项目 · {u.has_own_llm_key ? '自配 Key' : '用全局 Key'} · {u.status}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {u.status === 'active' ? (
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={banMutation.isPending}
                        onClick={() => banMutation.mutate({ userId: u.id, status: 'disabled' })}
                      >
                        封禁
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        disabled={banMutation.isPending}
                        onClick={() => banMutation.mutate({ userId: u.id, status: 'active' })}
                      >
                        解禁
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => { setResetTarget({ id: u.id, name: u.name }); setNewPassword('') }}
                    >
                      重置密码
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </section>

        {/* 重置密码弹层（简易内联） */}
        {resetTarget && (
          <section className="space-y-3">
            <Card>
              <CardHeader className="pb-3"><CardTitle className="text-[14px]">重置 {resetTarget.name} 的密码</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="newPwd">新密码</Label>
                  <Input id="newPwd" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} type="password" />
                </div>
                <div className="flex gap-2">
                  <Button onClick={() => resetMutation.mutate()} disabled={resetMutation.isPending || !newPassword}>
                    {resetMutation.isPending ? '重置中...' : '确认重置'}
                  </Button>
                  <Button variant="outline" onClick={() => setResetTarget(null)}>取消</Button>
                </div>
              </CardContent>
            </Card>
          </section>
        )}

        {/* LLM 调用统计 */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">LLM 调用统计（近 7 天）</h2>
          {statsData ? (
            <Card>
              <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4 py-4 text-[13px]">
                <div><div className="text-muted-foreground">总调用</div><div className="text-[16px] font-semibold">{statsData.total_calls}</div></div>
                <div><div className="text-muted-foreground">成功</div><div className="text-[16px] font-semibold text-green-600">{statsData.total_success}</div></div>
                <div><div className="text-muted-foreground">失败</div><div className="text-[16px] font-semibold text-red-600">{statsData.total_failed}</div></div>
                <div><div className="text-muted-foreground">平均耗时</div><div className="text-[16px] font-semibold">{statsData.avg_duration_ms ? Math.round(statsData.avg_duration_ms) : 0} ms</div></div>
              </CardContent>
            </Card>
          ) : (
            <p className="text-[13px] text-muted-foreground">加载中...</p>
          )}
          {statsData && statsData.by_model.length > 0 && (
            <Card>
              <CardHeader className="pb-3"><CardTitle className="text-[14px]">按模型</CardTitle></CardHeader>
              <CardContent>
                <div className="divide-y text-[13px]">
                  {statsData.by_model.map((m) => (
                    <div key={m.model} className="flex justify-between py-2">
                      <span>{m.model}</span>
                      <span className="text-muted-foreground">{m.calls} 次 · 失败 {m.failed}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </section>

        {/* 全局 LLM 配置 */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">全局 LLM 配置</h2>
          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-[14px]">Provider</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <label className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} id="enabled" className="size-4 accent-primary" />
                <span>提供全局 Key（关闭则强制用户自配）</span>
              </label>
              <div className="space-y-2"><Label htmlFor="baseUrl">API Base URL</Label><Input id="baseUrl" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://open.bigmodel.cn/api/paas/v4" /></div>
              <div className="space-y-2"><Label htmlFor="apiKey">API Key（留空不修改）</Label><Input id="apiKey" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={llmSettings?.global_config?.api_key_masked || '输入新 Key'} type="password" /></div>
              <div className="space-y-2"><Label htmlFor="model">模型</Label><Input id="model" value={model} onChange={(e) => setModel(e.target.value)} placeholder="glm-4-flash" /></div>
              <Button onClick={() => saveLLM.mutate()} disabled={saveLLM.isPending}>{saveLLM.isPending ? '保存中...' : '保存'}</Button>
            </CardContent>
          </Card>
        </section>

        {/* 审计日志 */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">审计日志</h2>
          <Card>
            <div className="divide-y text-[13px]">
              {auditItems.length === 0 && <div className="px-4 py-3 text-muted-foreground">暂无记录</div>}
              {auditItems.map((a) => (
                <div key={a.id} className="px-4 py-3 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{a.action}</span>
                    <span className="text-muted-foreground">{a.actor_email}</span>
                    <span className="text-muted-foreground">→ {a.target_type}{a.target_id ? `:${a.target_id}` : ''}</span>
                  </div>
                  {a.detail && <p className="text-[12px] text-muted-foreground">{JSON.stringify(a.detail)}</p>}
                  <p className="text-[11px] text-muted-foreground">{a.created_at ? new Date(a.created_at).toLocaleString() : ''}</p>
                </div>
              ))}
            </div>
          </Card>
        </section>
      </div>
    </PageShell>
  )
}
```

- [ ] **Step 4: 前端类型检查**

Run: `cd apps/web && npx tsc --noEmit`
Expected: 无类型错误（若 Badge 无 `variant="destructive"`，检查 `components/ui/badge.tsx` 是否支持该 variant；如不支持改用 `variant="default"` + 红色 className）。

- [ ] **Step 5: 前端构建**

Run: `cd apps/web && npm run build`
Expected: 构建成功无报错。

- [ ] **Step 6: 提交**

```bash
cd apps/web && git add src/types/api.ts src/lib/api.ts "src/app/(app)/admin/page.tsx"
git commit -m "feat(plan13): 前端管理页封禁/重置 + 统计面板 + 审计表"
```

---

## Task 10：全量验证

**Files:** 无新增，仅跑测试 + 端到端确认。

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest -v`
Expected: 全部 PASS（含本计划新增 test_llm_call_log_model / test_audit_log_model / test_admin_service / test_admin_api / test_stats_service / test_audit_logs_api / test_ai 新测试，及既有测试无回归）。

- [ ] **Step 2: 确认迁移链健康**

Run:
```bash
cd apps/api && uv run alembic current && uv run alembic heads
```
Expected: `current` 与 `heads` 一致，指向 audit_logs 迁移（最新 head）。

- [ ] **Step 3: 端到端手测清单（手工，记录结果）**

启动后端 `cd apps/api && uv run uvicorn app.main:app --reload` + 前端 `cd apps/web && npm run dev`，用管理员账号登录后验证：

1. `/admin` 页面显示用户列表，每个用户有「封禁/解禁」+「重置密码」按钮。
2. 点普通用户的「封禁」→ 该用户状态变「已封禁」；该用户刷新页面被踢下线（401）。
3. 点自己（管理员）的「封禁」→ 前端 toast「操作失败」。
4. 「重置密码」弹层输入新密码确认 → 提示成功；用新密码登录目标用户成功。
5. LLM 统计面板显示近 7 天调用数/成功/失败/平均耗时（触发一次 chat 后刷新可见）。
6. 审计日志表显示 ban_user / reset_password / set_global_llm 记录，detail 中无 api_key 明文。

- [ ] **Step 4: 最终提交（若有遗留改动）**

```bash
cd "G:/03-Personal-Projects/TianGong" && git status
# 若有未提交改动：
git add -A && git commit -m "feat(plan13): 全量验证收尾"
```

---

## 自检清单（实施完成后核对）

- [ ] 自我保护三条全测：自身封禁、超管封禁、其他管理员封禁（test_admin_service + test_admin_api）
- [ ] 重置密码自身/超管禁、其他管理员放行（设计 8.1 仅禁封禁第三条）
- [ ] api_key 脱敏全测：set_global_llm 审计 detail（test_admin_api）+ 审计端点响应（test_audit_logs_api）
- [ ] 设计 8.3 红线：LLMCallLog 模型无 prompt/completion 字段；stats 响应无内容字段；by_user 只显 email+计数
- [ ] 日志表不随用户删除：LLMCallLog.user_id 无 FK；AuditLog.actor_id FK SET NULL + actor_email 冗余
- [ ] 两个迁移可逆（downgrade -1 + upgrade head）
- [ ] ai.py 三个端点（chat/generate/rewrite）均写日志（成功 + 失败 + 断线）
- [ ] 前端三类功能可见且可操作
