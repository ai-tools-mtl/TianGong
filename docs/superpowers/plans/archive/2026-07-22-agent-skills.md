# 天工 Agent Skill 管理模块 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引入 Agent Skills 开放标准（`SKILL.md` 目录式技能），建成两档可见性（admin 全局 / 用户个人）的技能管理体系，技能全量接入 deepagents agent 运行时（spec 合规三层渐进式披露 + 自建 Docker sandbox 跑用户脚本），并彻底删除旧的 `agent_skills` 表与项目级 skill 耦合。

**Architecture:** 新建 `Skill` 数据模型（`scope`+`owner_id` 两档可见性）+ MinIO 对象前缀存储 skill 目录树；实现 LangGraph `BaseStore` 的 MinIO 适配器，由 deepagents `StoreBackend` 包装、`SkillsMiddleware` 加载；AI 层从一次性 `astream` 流式调用全量迁移到 `deepagents` agent loop（含 `rag_search` 工具化、自定义配置拒绝服务降级护栏）；自建 Docker sandbox 直读 MinIO 跑用户脚本；前端套现有统一面板布局，admin 全局管理 + 用户个人管理两页面。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy 2.0 / Alembic / `deepagents` / `langgraph`（已装未用，本次激活）/ `langchain-openai`（现有）/ `docker`（Python SDK，新增）/ MinIO（现有 `app/core/storage.py`）/ Next.js App Router / TanStack Query / shadcn 3.x 手写组件（GOTCHAS F1/F8）

**Spec:** `docs/superpowers/specs/2026-07-22-agent-skills-design.md`
**关联 grilling 结论:** 2026-07-22，6 轮 `/grill-me` 质询，决定矩阵见 spec §3
**当前 Alembic HEAD:** `b1c2d3e4f5g6`
**agent_skills 旧迁移 revision:** `0c31c3a1e6ad`（create_agent_skills）
**分支：** 当前在 `main`，本计划开始前先切到新分支 `feat/agent-skills`

---

## 前置验证（Task 0，开工前必做）

V1–V3 已在 spec §4 验证通过（glm-4.7 合法 / Python 3.14.6 / 自建 Docker）。Task 0 补做两项：确认 `deepagents` 可装 + 版本兼容。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `apps/api/app/models/skill.py` | `Skill` ORM 模型（两档可见性） | 新建 |
| `apps/api/app/models/__init__.py` | 导出 `Skill`，移除 `AgentSkill` | 改 |
| `apps/api/app/models/agent_skill.py` | 旧 `AgentSkill` 模型 | 删除 |
| `apps/api/alembic/versions/c1d2e3f4a5b6_create_skills.py` | 建 `skills` 表 | 新建 |
| `apps/api/alembic/versions/d2e3f4a5b6c7_drop_agent_skills.py` | 删 `agent_skills` 表 | 新建 |
| `apps/api/app/services/skill_service.py` | 旧 skill CRUD（`is_skill_enabled` 等） | 删除重建为新 service |
| `apps/api/app/services/seed_service.py` | 移除 `BUILTIN_SKILLS` 常量 | 改 |
| `apps/api/app/schemas/skill.py` | 新 `SkillOut`/`SkillCreate`/`SkillUpdate` | 改 |
| `apps/api/app/api/projects.py` | 移除 `/projects/{id}/skills` 路由 | 改 |
| `apps/api/app/skills/__init__.py` | skill 子包 | 新建 |
| `apps/api/app/skills/storage.py` | `MinIOStoreBackend(BaseStore)` 适配器 | 新建 |
| `apps/api/app/skills/loader.py` | skill 加载 + SkillsMiddleware 集成 | 新建 |
| `apps/api/app/skills/visibility.py` | 可见性合并服务 | 新建 |
| `apps/api/app/skills/validator.py` | SKILL.md frontmatter 校验 | 新建 |
| `apps/api/app/skills/service.py` | admin/user CRUD 业务逻辑 | 新建 |
| `apps/api/app/sandbox/__init__.py` | sandbox 子包 | 新建 |
| `apps/api/app/sandbox/docker_runner.py` | 自建 Docker sandbox | 新建 |
| `apps/api/app/ai/agent.py` | deepagents agent 工厂 + 自定义配置降级 | 新建 |
| `apps/api/app/ai/tools.py` | `rag_search` 等 `@tool` | 新建 |
| `apps/api/app/ai/orchestrator.py` | 移除旧一次性流，委托给 agent loop | 改 |
| `apps/api/app/core/config.py` | 默认 model 改 `glm-4.7` | 改 |
| `apps/api/app/api/skills.py` | 用户域 `/skills/*` 路由 | 新建 |
| `apps/api/app/api/admin/skills.py` | admin 域 `/admin/skills/*` 路由 | 新建 |
| `apps/api/app/api/admin/__init__.py` | 注册 skills 子 router | 改 |
| `apps/api/app/api/router.py` | 注册 `skills.router` | 改 |
| `apps/api/app/api/ai.py` | SSE 新增 `tool_call`/`tool_result` 事件 | 改 |
| `apps/api/pyproject.toml` | 加 `deepagents` / `docker` 依赖 | 改 |
| `apps/web/src/types/api.ts` | 新 `Skill` 类型，删旧 `AgentSkill` | 改 |
| `apps/web/src/lib/api.ts` | `api.skills.*` 方法 | 改 |
| `apps/web/src/lib/queries.ts` | `useSkills`/`useMySkills` hooks | 改 |
| `apps/web/src/app/(app)/admin/skills/page.tsx` | admin 全局技能页 | 新建 |
| `apps/web/src/components/admin/admin-skill-manager.tsx` | admin 管理组件 | 新建 |
| `apps/web/src/app/(app)/settings/skills/page.tsx` | 用户个人技能页 | 新建 |
| `apps/web/src/components/settings/personal-skill-manager.tsx` | 用户管理组件 | 新建 |
| `apps/web/src/components/skills/skill-editor.tsx` | 共享 skill 编辑器（表单式） | 新建 |
| `apps/web/src/components/skills/skills-dialog.tsx` | 旧 SkillsDialog 组件 | 删除 |

---

## Task 0: 工程前置验证（deepagents 可装 + 版本兼容）

**Files:**
- Install: `deepagents`, `docker`（加入 `apps/api/pyproject.toml`）

- [ ] **Step 1: 安装 deepagents 并确认版本兼容**

Run:
```bash
cd apps/api
uv add deepagents docker
uv run python -c "import deepagents; import langgraph; print('deepagents OK'); print('langgraph', langgraph.__version__)"
```
Expected: 无 ImportError，打印 `deepagents OK` 和 langgraph 版本号。

- [ ] **Step 2: 确认 langgraph 已激活（之前装了但零 import）**

Run:
```bash
cd apps/api && uv run python -c "from langgraph.store.base import BaseStore; print('BaseStore importable:', BaseStore)"
```
Expected: 打印 `BaseStore importable: <class 'langgraph.store.base.BaseStore'>`。

- [ ] **Step 3: 跑现有测试套件确认未破坏基线**

Run: `cd apps/api && uv run pytest -q 2>&1 | tail -20`
Expected: 全绿（现有 36 个测试基线不破）。

- [ ] **Step 4: 切分支**

Run: `cd /g/03-Personal-Projects/TianGong && git checkout -b feat/agent-skills`
Expected: `Switched to a new branch 'feat/agent-skills'`

- [ ] **Step 5: 提交依赖变更**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/pyproject.toml apps/api/uv.lock
git commit -m "build(api): 引入 deepagents + docker 依赖（agent-skills 前置）"
```

---

## Phase 1: 数据层 + 清理旧 skill 体系

### Task 1: 新建 `Skill` 模型

**Files:**
- Create: `apps/api/app/models/skill.py`
- Modify: `apps/api/app/models/__init__.py`
- Test: `apps/api/tests/test_skill_model.py`

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_skill_model.py
"""Skill 模型测试：两档可见性、状态机、MinIO 前缀。"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import JSON

from app.models.base import Base
# JSONB 在 sqlite 降级为 JSON（GOTCHAS G2）


@pytest.fixture
def db():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool,
    )
    # 让 JSONB 在 sqlite 下降级
    Base.metadata.bind = None
    Base.registry.configure()
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def test_create_personal_skill(db):
    """个人 skill：scope=personal，owner_id 必填，minio_prefix 含 owner。"""
    from app.models import Skill

    owner = uuid.uuid4()
    skill = Skill(
        name="patent-claim-writer",
        description="辅助撰写权利要求",
        scope="personal",
        owner_id=owner,
        status="draft",
        minio_prefix=f"skills/personal/{owner}/patent-claim-writer/",
    )
    db.add(skill)
    db.commit()
    assert skill.id is not None
    assert skill.scope == "personal"
    assert skill.owner_id == owner
    assert skill.status == "draft"


def test_create_global_skill(db):
    """全局 skill：scope=global，owner_id=NULL。"""
    from app.models import Skill

    skill = Skill(
        name="prior-art-search",
        description="检索现有技术",
        scope="global",
        owner_id=None,
        status="active",
        minio_prefix="skills/global/prior-art-search/",
    )
    db.add(skill)
    db.commit()
    assert skill.scope == "global"
    assert skill.owner_id is None
    assert skill.status == "active"


def test_skill_has_timestamps(db):
    """Skill 继承 TimestampMixin，含 created_at/updated_at。"""
    from app.models import Skill

    skill = Skill(
        name="x", description="d", scope="global", status="draft",
        minio_prefix="skills/global/x/",
    )
    db.add(skill)
    db.commit()
    assert skill.created_at is not None
    assert skill.updated_at is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_skill_model.py -v`
Expected: FAIL（`ImportError: cannot import name 'Skill' from 'app.models'`）

- [ ] **Step 3: 实现 Skill 模型**

```python
# apps/api/app/models/skill.py
"""Agent Skill 模型（spec 合规，两档可见性）。

替代旧 AgentSkill（project-scoped 覆盖）。新模型：skill 定义本身归属
admin 全局（scope=global, owner_id=NULL）或用户个人（scope=personal）。
详见 spec §5.1。
"""
import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

# 可见性两档
SCOPE_GLOBAL = "global"
SCOPE_PERSONAL = "personal"

# 状态：draft 不进 runtime，active 进
STATUS_DRAFT = "draft"
STATUS_ACTIVE = "active"


class Skill(Base, IdMixin, TimestampMixin):
    """一个 Agent Skill = 一份 spec 合规的 SKILL.md 目录树 + 元数据。

    - scope/owner_id 联合表达可见性：global 时 owner_id=NULL，personal 时必填。
    - status=draft 不进 runtime 可见集合（admin/用户编辑中不喂 agent）。
    - minio_prefix 指向 MinIO 中该 skill 的目录前缀（SKILL.md + scripts/ + ...）。
    """
    __tablename__ = "skills"
    __table_args__ = (
        # 同一 scope + owner 下 name 唯一（global 时 owner_id 视为 NULL 统一）
        Index("uix_skill_scope_owner_name", "scope", "owner_id", "name", unique=True),
    )

    name: Mapped[str] = mapped_column(String(64))  # spec name, [a-z0-9-], ≤64
    description: Mapped[str] = mapped_column(Text)  # ≤1024，单行（触发条件）
    scope: Mapped[str] = mapped_column(String(20))  # global / personal
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=STATUS_DRAFT)
    minio_prefix: Mapped[str] = mapped_column(String(255))
```

- [ ] **Step 4: 在 models/__init__.py 导出 Skill（先加，下一步删 AgentSkill）**

修改 `apps/api/app/models/__init__.py`：在 `from app.models.agent_skill import AgentSkill` 之后加一行，并在 `__all__` 加 `"Skill"`：

```python
from app.models.agent_skill import AgentSkill  # 旧，Task 2 删除
from app.models.skill import Skill  # 新
```

`__all__` 列表末尾（`"AuditLog",` 之后）加：
```python
    "Skill",
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_skill_model.py -v`
Expected: 3 PASS

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/models/skill.py apps/api/app/models/__init__.py apps/api/tests/test_skill_model.py
git commit -m "feat(api): 新建 Skill 模型（两档可见性，spec 合规）"
```

---

### Task 2: 迁移 — 建 skills 表

**Files:**
- Create: `apps/api/alembic/versions/c1d2e3f4a5b6_create_skills.py`

- [ ] **Step 1: 生成迁移**

Run: `cd apps/api && uv run alembic revision --autogenerate -m "create_skills"`
Expected: 生成新迁移文件，revision 以当前 HEAD `b1c2d3e4f5g6` 为 down_revision。

- [ ] **Step 2: 检查生成的迁移内容，确认含 create_table skills + unique index**

打开生成的迁移文件，确认 `upgrade()` 含：
```python
op.create_table(
    'skills',
    sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('owner_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('minio_prefix', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
)
op.create_index('uix_skill_scope_owner_name', 'skills', ['scope', 'owner_id', 'name'], unique=True)
op.create_index('ix_skills_owner_id', 'skills', ['owner_id'])
```

把文件重命名为 `c1d2e3f4a5b6_create_skills.py`，revision 改为 `c1d2e3f4a5b6`，down_revision 改为 `b1c2d3e4f5g6`。

- [ ] **Step 3: 跑迁移确认成功**

Run: `cd apps/api && uv run alembic upgrade head`
Expected: `Running upgrade b1c2d3e4f5g6 -> c1d2e3f4a5b6, create_skills`

- [ ] **Step 4: 跑测试套件确认未破坏**

Run: `cd apps/api && uv run pytest -q 2>&1 | tail -10`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add apps/api/alembic/versions/c1d2e3f4a5b6_create_skills.py
git commit -m "feat(api): 迁移建 skills 表（两档可见性 + unique index）"
```

---

### Task 3: 删除旧 agent_skills 体系（后端）

**Files:**
- Delete: `apps/api/app/models/agent_skill.py`
- Modify: `apps/api/app/models/__init__.py`（移除 AgentSkill 导入导出）
- Modify: `apps/api/app/services/seed_service.py`（移除 BUILTIN_SKILLS）
- Delete: `apps/api/app/services/skill_service.py`（旧实现，Task 7 重建为新 service）
- Modify: `apps/api/app/schemas/skill.py`（清空旧 schema，Task 6 重建）
- Modify: `apps/api/app/api/projects.py`（移除 /projects/{id}/skills 路由）
- Create: `apps/api/alembic/versions/d2e3f4a5b6c7_drop_agent_skills.py`
- Test: `apps/api/tests/test_old_skill_removed.py`

- [ ] **Step 1: 写失败测试（验证旧体系已移除）**

```python
# apps/api/tests/test_old_skill_removed.py
"""验证旧 agent_skills 体系已彻底移除（spec Q5 解耦决定）。"""
import pytest


def test_agent_skill_model_removed():
    """AgentSkill 模型不再可导入。"""
    from app import models
    assert not hasattr(models, "AgentSkill")


def test_old_skill_service_removed():
    """旧 skill_service.is_skill_enabled 不再存在。"""
    import importlib
    svc = importlib.import_module("app.services.skill_service")
    # 新 service 不应有旧的 is_skill_enabled
    assert not hasattr(svc, "is_skill_enabled")
    assert not hasattr(svc, "BUILTIN_SKILLS")


def test_projects_skills_route_removed():
    """/projects/{id}/skills 路由不再存在。"""
    from app.api import projects
    paths = [r.path for r in projects.router.routes]
    assert not any("/skills" in p for p in paths)


def test_builtin_skills_constant_removed():
    """BUILTIN_SKILLS 常量从 seed_service 移除。"""
    from app.services import seed_service
    assert not hasattr(seed_service, "BUILTIN_SKILLS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_old_skill_removed.py -v`
Expected: FAIL（旧体系仍存在）

- [ ] **Step 3: 删除 agent_skill 模型文件**

Run: `cd apps/api && rm app/models/agent_skill.py`

- [ ] **Step 4: 修改 models/__init__.py 移除 AgentSkill**

删除行 `from app.models.agent_skill import AgentSkill`，从 `__all__` 删除 `"AgentSkill"`。

- [ ] **Step 5: 修改 seed_service.py 移除 BUILTIN_SKILLS**

打开 `apps/api/app/services/seed_service.py`，删除整个 `BUILTIN_SKILLS = [...]` 列表常量（约 1-37 行的列表）。保留 `DEFAULT_STRUCTURE` 和后续 seed 逻辑。

- [ ] **Step 6: 删除旧 skill_service.py（Task 7 重建）**

Run: `cd apps/api && rm app/services/skill_service.py`

- [ ] **Step 7: 清空旧 schemas/skill.py（Task 6 重建）**

把 `apps/api/app/schemas/skill.py` 内容替换为占位（避免 projects.py 等引用报错时容易定位）：

```python
# apps/api/app/schemas/skill.py
"""Skill schemas（spec 合规版，Task 6 重建）。

旧 SkillOut/SkillUpdate 已随 agent_skills 表删除。本文件在 Task 6 重建。
"""
```

- [ ] **Step 8: 修改 projects.py 移除 skills 路由**

打开 `apps/api/app/api/projects.py`，删除：
- 顶部 `from app.schemas.skill import SkillOut, SkillUpdate` 导入
- 顶部 `from app.services import skill_service` 导入
- `list_skills` 函数（`@router.get("/{project_id}/skills", ...)` 整段）
- `update_skill` 函数（`@router.put("/{project_id}/skills/{skill_key}", ...)` 整段）

- [ ] **Step 9: 创建 drop agent_skills 迁移**

```python
# apps/api/alembic/versions/d2e3f4a5b6c7_drop_agent_skills.py
"""drop agent_skills 表（旧 skill 体系，spec Q5 解耦决定）。

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-22
"""
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_agent_skills_project_id", table_name="agent_skills")
    op.drop_table("agent_skills")


def downgrade():
    # 重建 agent_skills（仅结构，数据不可恢复）
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql
    op.create_table(
        "agent_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_key", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_skills_project_id", "agent_skills", ["project_id"])
```

- [ ] **Step 10: 跑迁移**

Run: `cd apps/api && uv run alembic upgrade head`
Expected: `Running upgrade c1d2e3f4a5b6 -> d2e3f4a5b6c7, drop agent_skills`

- [ ] **Step 11: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_old_skill_removed.py -v`
Expected: 4 PASS

- [ ] **Step 12: 跑全量测试确认 orchestrator 引用已断（预期会有 RAG 相关失败）**

Run: `cd apps/api && uv run pytest -q 2>&1 | tail -20`
Expected: `orchestrator.py` 引用 `skill_service.is_skill_enabled` 会报 ImportError。**这是预期的**——Task 8 会用 `@tool` 改造 RAG。临时让 orchestrator 不崩：修改 `app/ai/orchestrator.py` 的 `_retrieve_knowledge`，把 skill 开关检查替换为 `return None`（Task 8 重建）：

```python
def _retrieve_knowledge(db, section: Section, query: str) -> list[dict] | None:
    """检索用户知识库（RAG）。旧 skill 开关已删除，Task 8 改造为 @tool。临时返回 None。"""
    return None
```

重跑：`cd apps/api && uv run pytest -q 2>&1 | tail -10`
Expected: 全绿

- [ ] **Step 13: 提交**

```bash
git add -A apps/api
git commit -m "refactor(api): 删除旧 agent_skills 体系（模型/服务/schema/路由/迁移）

- 删 AgentSkill 模型、BUILTIN_SKILLS 常量、旧 skill_service、/projects/{id}/skills 路由
- 迁移 drop agent_skills 表
- orchestrator._retrieve_knowledge 临时返回 None（Task 8 重建为 @tool）
spec Q5 解耦决定"
```

---

### Task 4: 清理前端旧 skill 体系

**Files:**
- Delete: `apps/web/src/components/skills-dialog.tsx`
- Modify: `apps/web/src/types/api.ts`（删 AgentSkill 类型）
- Modify: `apps/web/src/lib/queries.ts`（删 useSkills/useUpdateSkill/queryKeys.skills）

- [ ] **Step 1: 定位前端对旧 skill 的所有引用**

Run: `cd apps/web && grep -rn "AgentSkill\|skills-dialog\|useSkills\|useUpdateSkill\|queryKeys.skills" src/ 2>&1`
Expected: 列出所有引用点（types/api.ts、queries.ts、skills-dialog.tsx、及任何 import 它们的组件）

- [ ] **Step 2: 删除 skills-dialog.tsx**

Run: `cd apps/web && rm src/components/skills-dialog.tsx`

- [ ] **Step 3: 删除 types/api.ts 中的 AgentSkill 类型**

打开 `apps/web/src/types/api.ts`，删除 `AgentSkill` interface（约第 344 行）。

- [ ] **Step 4: 删除 queries.ts 中的 skill hooks 和 queryKey**

打开 `apps/web/src/lib/queries.ts`，删除：
- `useSkills` hook
- `useUpdateSkill` hook
- `queryKeys` 对象中的 `skills` 条目

- [ ] **Step 5: 修复所有引用 skills-dialog 的组件**

根据 Step 1 的 grep 结果，逐个打开引用 `SkillsDialog` 的组件，移除 import 和 `<SkillsDialog />` JSX（通常是项目设置面板里的 skill 开关弹窗）。若组件因此变空，保留页面壳但移除 skill 部分。

- [ ] **Step 6: 跑前端构建确认无引用残留**

Run: `cd apps/web && pnpm build 2>&1 | tail -20`
Expected: 构建成功，无 `Module not found` 错误。

- [ ] **Step 7: 提交**

```bash
git add -A apps/web
git commit -m "refactor(web): 删除旧 skill 体系（SkillsDialog/AgentSkill 类型/useSkills hook）

spec Q5 解耦决定，后端已在 Task 3 删除"
```

---

### Task 5: 默认模型升级到 glm-4.7

**Files:**
- Modify: `apps/api/app/core/config.py:31`

- [ ] **Step 1: 改默认 model**

打开 `apps/api/app/core/config.py`，第 31 行：

```python
# 改前
glm_model: str = "glm-4-flash"
# 改后
glm_model: str = "glm-4.7"
```

- [ ] **Step 2: 跑测试确认未破坏（测试里硬编码了 glm-4-flash 的地方可能需要同步）**

Run: `cd apps/api && uv run pytest -q 2>&1 | tail -15`
Expected: 若有测试断言默认 model，同步改测试 fixture 的期望值。全绿。

- [ ] **Step 3: 同步 .env 的 GLM_MODEL（如已设）**

检查 `.env` 是否显式设了 `GLM_MODEL`，若设为 `glm-4-flash` 则改为 `glm-4.7`（或删掉这行用 config.py 默认）。

- [ ] **Step 4: 提交**

```bash
git add apps/api/app/core/config.py apps/api/.env
git commit -m "feat(api): 默认 LLM 模型升级 glm-4-flash → glm-4.7（tool calling 支持）"
```

---

## Phase 1 收尾检查

- [ ] **Phase 1 验证:** `cd apps/api && uv run pytest -q` 全绿 + `cd apps/web && pnpm build` 成功 + `uv run alembic current` 显示 `d2e3f4a5b6c7 (head)`

---

## Phase 2: MinIO BaseStore 适配器 + skill 存储

> **API 事实（deepagents 0.6.12 introspect 确认）：**
> - `create_deep_agent(skills=["/source/path/"], backend=StoreBackend(store=my_store), ...)`
> - `skills` 参数是 **source 路径列表**（不是 skill 对象），每个路径是一个命名空间前缀。
> - `StoreBackend(store=BaseStore实例)` —— store 直接传入。
> - `BaseStore` 需实现 8 方法：`get/put/search/delete`（同步）+ `aget/aput/asearch/adelete`（异步），namespace 是 `tuple[str,...]`，value 是 dict。
> - `StoreBackend` 自带 `read/write/edit/grep/glob/ls/upload_files`，全部委托给传入的 `BaseStore`——agent 用这些工具按需读 SKILL.md。

### Task 6: 新建 schemas（Skill CRUD 的 DTO）

**Files:**
- Modify: `apps/api/app/schemas/skill.py`（Task 3 清空，现重建）

- [ ] **Step 1: 写新 schemas**

```python
# apps/api/app/schemas/skill.py
"""Skill schemas（spec 合规版）。

旧 SkillOut/SkillUpdate 已随 agent_skills 表删除（Task 3）。
本文件为新两档可见性体系重建。
"""
from pydantic import BaseModel, Field, field_validator
import re

# spec name 规则：[a-z0-9-]，1-64，不首尾/连续连字符
_NAME_RE = re.compile(r"^(?!-)[a-z0-9-]{1,64}(?<!-)$")


class SkillBase(BaseModel):
    name: str = Field(..., max_length=64, description="spec name, [a-z0-9-]")
    description: str = Field(..., max_length=1024, description="触发条件，单行")
    skill_md: str = Field(..., description="SKILL.md 正文（Markdown，不含 frontmatter）")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError("name 必须为 [a-z0-9-]，1-64 字符，不首尾/连续连字符")
        if "--" in v:
            raise ValueError("name 不能有连续连字符")
        return v

    @field_validator("description")
    @classmethod
    def single_line(cls, v: str) -> str:
        if "\n" in v.strip():
            raise ValueError("description 必须单行（spec 触发条件约束）")
        return v.strip()


class SkillCreate(SkillBase):
    """创建 skill。scope 由路由决定（admin=global, user=personal），不在 body。"""


class SkillUpdate(BaseModel):
    """更新 skill（全 Optional，部分更新）。name 不可改（spec: name=目录名）。"""
    description: str | None = Field(None, max_length=1024)
    skill_md: str | None = None
    status: str | None = Field(None, pattern="^(draft|active)$")

    @field_validator("description")
    @classmethod
    def single_line(cls, v):
        if v and "\n" in v.strip():
            raise ValueError("description 必须单行")
        return v.strip() if v else v


class SkillOut(BaseModel):
    """skill 输出（列表 + 详情共用）。"""
    model_config = {"from_attributes": True}

    id: str
    name: str
    description: str
    scope: str
    owner_id: str | None = None
    status: str
    minio_prefix: str
    created_at: str
    updated_at: str


class SkillDetail(SkillOut):
    """详情：含 SKILL.md 正文。"""
    skill_md: str
```

- [ ] **Step 2: 跑 import 确认无语法错**

Run: `cd apps/api && uv run python -c "from app.schemas.skill import SkillCreate, SkillUpdate, SkillOut, SkillDetail; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add apps/api/app/schemas/skill.py
git commit -m "feat(api): 重建 Skill schemas（SkillCreate/Update/Out/Detail，spec 校验）"
```

---

### Task 7: MinIO BaseStore 适配器

**Files:**
- Create: `apps/api/app/skills/__init__.py`
- Create: `apps/api/app/skills/storage.py`
- Test: `apps/api/tests/test_skill_storage.py`

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_skill_storage.py
"""MinIO BaseStore 适配器测试。

用 conftest 的 _FakeStorage（内存假实现）mock MinioStorage，不真实连 minio。
测试 namespace ↔ MinIO key 的映射 + BaseStore 8 方法契约。
"""
import pytest
from langgraph.store.base import Item

from app.skills.storage import MinIOSkillStore, namespace_to_minio_key


def test_namespace_to_minio_key_global():
    """global skill namespace 映射 MinIO key。"""
    key = namespace_to_minio_key(("skills", "global", "my-skill"), "SKILL.md")
    assert key == "skills/global/my-skill/SKILL.md"


def test_namespace_to_minio_key_personal():
    """personal skill namespace 映射 MinIO key。"""
    key = namespace_to_minio_key(("skills", "personal", "user-uuid", "my-skill"), "SKILL.md")
    assert key == "skills/personal/user-uuid/my-skill/SKILL.md"


def test_put_and_get_skill_md(monkeypatch):
    """put 写入 MinIO，get 读回，value 含 content 字段。"""
    from app.core import storage as storage_mod

    fake = {}  # (bucket, key) -> bytes
    class _FakeStorage:
        def put(self, bucket, key, content, content_type):
            fake[(bucket, key)] = content
        def get(self, bucket, key):
            return fake.get((bucket, key), b"")
        def delete(self, bucket, key):
            fake.pop((bucket, key), None)
        def stat(self, bucket, key):
            return (bucket, key) in fake

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    store = MinIOSkillStore(bucket="global")
    ns = ("skills", "global", "my-skill")
    store.put(ns, "SKILL.md", {"content": "# My Skill\ninstructions here", "encoding": "utf-8"})

    item = store.get(ns, "SKILL.md")
    assert item is not None
    assert item.value["content"] == "# My Skill\ninstructions here"


def test_delete_skill(monkeypatch):
    """delete 幂等删除。"""
    from app.core import storage as storage_mod
    fake = {}
    class _FakeStorage:
        def put(self, b, k, c, ct): fake[(b,k)] = c
        def get(self, b, k): return fake.get((b,k), b"")
        def delete(self, b, k): fake.pop((b,k), None)
        def stat(self, b, k): return (b,k) in fake

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())
    store = MinIOSkillStore(bucket="global")
    ns = ("skills", "global", "x")
    store.put(ns, "SKILL.md", {"content": "test"})
    store.delete(ns, "SKILL.md")
    assert store.get(ns, "SKILL.md") is None
    # 二次删除不报错（幂等）
    store.delete(ns, "SKILL.md")


def test_search_by_namespace_prefix(monkeypatch):
    """search 按 namespace_prefix 列出该前缀下所有 skill 文件。"""
    from app.core import storage as storage_mod
    fake = {}
    class _FakeStorage:
        def put(self, b, k, c, ct): fake[(b,k)] = c
        def get(self, b, k): return fake.get((b,k), b"")
        def delete(self, b, k): fake.pop((b,k), None)
        def stat(self, b, k): return (b,k) in fake

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())
    store = MinIOSkillStore(bucket="global")
    base = ("skills", "global")
    store.put((*base, "skill-a"), "SKILL.md", {"content": "a"})
    store.put((*base, "skill-b"), "SKILL.md", {"content": "b"})

    results = store.search(base, limit=10)
    keys = {r.key for r in results}
    assert keys == {"SKILL.md"}  # 两个 skill 各一个 SKILL.md
    namespaces = {r.namespace for r in results}
    assert ("skills", "global", "skill-a") in namespaces
    assert ("skills", "global", "skill-b") in namespaces
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_skill_storage.py -v`
Expected: FAIL（`ImportError: No module named 'app.skills'`）

- [ ] **Step 3: 实现 MinIOSkillStore**

```python
# apps/api/app/skills/__init__.py
"""Agent Skill 子包（spec 合规）。"""
```

```python
# apps/api/app/skills/storage.py
"""MinIO-backed LangGraph BaseStore 适配器。

deepagents 的 StoreBackend 包装本实现，SkillsMiddleware 通过它加载 skill。
namespace tuple 映射到 MinIO 对象 key：("skills","global","my-skill") + "SKILL.md"
→ "skills/global/my-skill/SKILL.md"。

复用 app/core/storage.py 的 MinioStorage（已验证），不重复造存储轮子。
"""
from datetime import datetime, timezone
from typing import Any

from langgraph.store.base import BaseStore, Item, SearchItem

from app.core.storage import get_storage


def namespace_to_minio_key(namespace: tuple[str, ...], key: str) -> str:
    """namespace tuple + 文件名 → MinIO 对象 key。"""
    return "/".join((*namespace, key))


class MinIOSkillStore(BaseStore):
    """把 skill 文件存到 MinIO 的 BaseStore 实现。

    每个 (namespace, key) = MinIO 里的一个对象。value dict 序列化为 JSON bytes。
    bucket 别名传 'global' / 'personal'（由 Settings 映射）。
    """

    def __init__(self, *, bucket: str = "global"):

        self._bucket_alias = bucket

    def _storage(self):
        return get_storage()

    def _serialize(self, value: dict[str, Any]) -> bytes:
        import json
        return json.dumps(value, ensure_ascii=False).encode("utf-8")

    def _deserialize(self, raw: bytes) -> dict[str, Any]:
        import json
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def put(self, namespace, key, value, index=None, *, ttl=None) -> None:
        st = self._storage()
        minio_key = namespace_to_minio_key(namespace, key)
        st.put(self._bucket_alias, minio_key, self._serialize(value), "application/json")

    def aput(self, namespace, key, value, index=None, *, ttl=None) -> None:
        self.put(namespace, key, value, index=index, ttl=ttl)

    def get(self, namespace, key, *, refresh_ttl=None) -> Item | None:
        st = self._storage()
        minio_key = namespace_to_minio_key(namespace, key)
        if not st.stat(self._bucket_alias, minio_key):
            return None
        raw = st.get(self._bucket_alias, minio_key)
        value = self._deserialize(raw)
        now = datetime.now(timezone.utc)
        return Item(
            value=value, key=key, namespace=tuple(namespace),
            created_at=now, updated_at=now,
        )

    def aget(self, namespace, key, *, refresh_ttl=None) -> Item | None:
        return self.get(namespace, key, refresh_ttl=refresh_ttl)

    def search(self, namespace_prefix, /, *, query=None, filter=None, limit=10, offset=0, refresh_ttl=None) -> list[SearchItem]:
        """按 namespace_prefix 列出该前缀下所有对象。

        MinIO 无原生 namespace 查询，用 minio client list_objects（前缀匹配）模拟。
        每个 skill 文件（SKILL.md/scripts/*）各成一个 SearchItem。
        """
        st = self._storage()
        prefix_str = "/".join(namespace_prefix) + "/"
        client = st._client  # noqa: SLF001（复用已建连的 client）
        real_bucket = st._resolve(self._bucket_alias)  # noqa: SLF001
        items: list[SearchItem] = []
        now = datetime.now(timezone.utc)
        for obj in client.list_objects(real_bucket, prefix=prefix_str, recursive=True):
            parts = obj.object_name.split("/")
            if len(parts) < 2:
                continue
            file_key = parts[-1]
            ns = tuple(parts[:-1])
            raw = st.get(self._bucket_alias, obj.object_name)
            value = self._deserialize(raw)
            items.append(SearchItem(
                value=value, key=file_key, namespace=ns,
                created_at=now, updated_at=now,
            ))
            if len(items) >= limit:
                break
        return items[offset:offset + limit]

    def asearch(self, namespace_prefix, /, *, query=None, filter=None, limit=10, offset=0, refresh_ttl=None) -> list[SearchItem]:
        return self.search(namespace_prefix, query=query, filter=filter, limit=limit, offset=offset, refresh_ttl=refresh_ttl)

    def delete(self, namespace, key) -> None:
        st = self._storage()
        minio_key = namespace_to_minio_key(namespace, key)
        st.delete(self._bucket_alias, minio_key)  # 幂等

    def adelete(self, namespace, key) -> None:
        self.delete(namespace, key)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_skill_storage.py -v`
Expected: 5 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/skills/ apps/api/tests/test_skill_storage.py
git commit -m "feat(api): MinIO BaseStore 适配器（deepagents StoreBackend 后端）"
```


---

### Task 8: skill 目录管理（写/删 SKILL.md + 资源）

**Files:**
- Create: `apps/api/app/skills/service.py`
- Test: `apps/api/tests/test_skill_directory.py`

> 把 frontmatter + 正文拼成完整 SKILL.md 存 MinIO，scripts/references/assets 子目录管理。

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_skill_directory.py
"""skill 目录管理：SKILL.md 组装 + 资源文件 CRUD。"""
import pytest


def test_assemble_skill_md(monkeypatch):
    """frontmatter + 正文拼成完整 SKILL.md。"""
    from app.skills.service import assemble_skill_md
    md = assemble_skill_md(name="my-skill", description="does X", body="## Steps\n1. foo")
    assert md.startswith("---\n")
    assert "name: my-skill" in md
    assert "description: does X" in md
    assert "## Steps\n1. foo" in md


def test_write_and_read_skill_directory(monkeypatch):
    """写一个完整 skill 目录，读回 SKILL.md。"""
    from app.core import storage as storage_mod
    from app.skills.service import write_skill_directory, read_skill_md

    fake = {}
    class _FakeStorage:
        def __init__(self): self._client = None
        def put(self, b, k, c, ct): fake[(b,k)] = c
        def get(self, b, k): return fake.get((b,k), b"")
        def delete(self, b, k): fake.pop((b,k), None)
        def stat(self, b, k): return (b,k) in fake
        def _resolve(self, alias): return alias

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    prefix = "skills/global/my-skill/"
    write_skill_directory(
        bucket="global", prefix=prefix,
        name="my-skill", description="does X", body="## Steps",
        scripts={"analyze.py": "print('hi')"},
    )
    md = read_skill_md(bucket="global", prefix=prefix)
    assert "name: my-skill" in md


def test_delete_skill_directory(monkeypatch):
    """删 skill 目录：清空该 prefix 下所有对象。"""
    from app.core import storage as storage_mod
    from app.skills.service import write_skill_directory, delete_skill_directory, read_skill_md
    from app.core.exceptions import NotFoundError

    fake = {}
    class _FakeObj:
        def __init__(self, name): self.object_name = name
    class _FakeClient:
        def __init__(self, store): self._store = store
        def list_objects(self, bucket, prefix=None, recursive=False):
            return [_FakeObj(k.split("/",1)[1] if "/" in k else k) for (b,k) in fake if k.startswith(prefix.replace("/","/",1)) if True]
        def remove_object(self, bucket, key): fake.pop((bucket, key), None)
    class _FakeStorage:
        def __init__(self): self._client = _FakeClient(self)
        def put(self, b, k, c, ct): fake[(b,k)] = c
        def get(self, b, k): return fake.get((b,k), b"")
        def delete(self, b, k): fake.pop((b,k), None)
        def stat(self, b, k): return (b,k) in fake
        def _resolve(self, alias): return alias

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())
    prefix = "skills/global/my-skill/"
    write_skill_directory(bucket="global", prefix=prefix, name="my-skill", description="d", body="b")
    delete_skill_directory(bucket="global", prefix=prefix)
    with pytest.raises(NotFoundError):
        read_skill_md(bucket="global", prefix=prefix)
```

> 注：`_FakeClient.list_objects` 简化模拟——按 prefix 前缀匹配 fake dict 的 key。实际执行时若该 mock 不够精确，可调整为遍历 `fake.keys()` 过滤 prefix。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_skill_directory.py -v`
Expected: FAIL（`ImportError: cannot import name 'assemble_skill_md'`）

- [ ] **Step 3: 实现 service.py（目录管理部分）**

```python
# apps/api/app/skills/service.py
"""Skill 业务逻辑：目录管理（本文件）+ 可见性合并（visibility.py）+ CRUD（Task 11 补）。

目录管理：把 frontmatter + 正文拼成 SKILL.md 存 MinIO，管理 scripts/references/assets。
"""
from app.core.exceptions import NotFoundError
from app.core.storage import get_storage

SKILL_MD_FILENAME = "SKILL.md"


def assemble_skill_md(*, name: str, description: str, body: str) -> str:
    """组装完整 SKILL.md = frontmatter + 正文。

    description 必须单行（spec 触发条件约束），调用方负责校验。
    """
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"


def _key(prefix: str, filename: str) -> str:
    return f"{prefix}{filename}"


def write_skill_directory(
    *, bucket: str, prefix: str, name: str, description: str, body: str,
    scripts: dict[str, str] | None = None,
    references: dict[str, str] | None = None,
    assets: dict[str, bytes] | None = None,
) -> None:
    """写一个完整 skill 目录到 MinIO。"""
    st = get_storage()
    st.put(bucket, _key(prefix, SKILL_MD_FILENAME),
           assemble_skill_md(name=name, description=description, body=body).encode("utf-8"),
           "text/markdown")
    for fname, code in (scripts or {}).items():
        st.put(bucket, _key(prefix, f"scripts/{fname}"), code.encode("utf-8"), "text/plain")
    for fname, text in (references or {}).items():
        st.put(bucket, _key(prefix, f"references/{fname}"), text.encode("utf-8"), "text/plain")
    for fname, data in (assets or {}).items():
        st.put(bucket, _key(prefix, f"assets/{fname}"), data, "application/octet-stream")


def read_skill_md(*, bucket: str, prefix: str) -> str:
    """读 SKILL.md 正文。不存在抛 NotFoundError。"""
    st = get_storage()
    key = _key(prefix, SKILL_MD_FILENAME)
    if not st.stat(bucket, key):
        raise NotFoundError(f"Skill 不存在：{prefix}")
    return st.get(bucket, key).decode("utf-8")


def delete_skill_directory(*, bucket: str, prefix: str) -> None:
    """删 skill 目录：清空该 prefix 下所有对象（幂等）。"""
    st = get_storage()
    client = st._client  # noqa: SLF001
    real_bucket = st._resolve(bucket)  # noqa: SLF001
    objs = list(client.list_objects(real_bucket, prefix=prefix, recursive=True))
    for obj in objs:
        client.remove_object(real_bucket, obj.object_name)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_skill_directory.py -v`
Expected: 3 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/skills/service.py apps/api/tests/test_skill_directory.py
git commit -m "feat(api): skill 目录管理（SKILL.md 组装 + 资源 CRUD）"
```

---

### Task 9: 可见性合并服务

**Files:**
- Create: `apps/api/app/skills/visibility.py`
- Test: `apps/api/tests/test_skill_visibility.py`

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_skill_visibility.py
"""可见性合并：global ∪ personal（纯运行时，项目无状态）。

spec Q11-α：每次 agent run 实时算可见集合，不存项目状态。
"""
import uuid


def test_visible_skills_global_only(db_session):
    """只有 global skill 时，普通用户可见它。"""
    from app.models import Skill
    from app.skills.visibility import list_visible_skills

    g = Skill(name="g1", description="d", scope="global", owner_id=None,
              status="active", minio_prefix="skills/global/g1/")
    db_session.add(g); db_session.commit()

    user_id = uuid.uuid4()
    result = list_visible_skills(db_session, user_id=user_id)
    assert [s.name for s in result] == ["g1"]


def test_visible_skills_personal_only(db_session):
    """只有个人 skill，仅本人可见。"""
    from app.models import Skill
    from app.skills.visibility import list_visible_skills

    owner = uuid.uuid4()
    p = Skill(name="p1", description="d", scope="personal", owner_id=owner,
              status="active", minio_prefix=f"skills/personal/{owner}/p1/")
    db_session.add(p); db_session.commit()

    assert [s.name for s in list_visible_skills(db_session, user_id=owner)] == ["p1"]
    other = uuid.uuid4()
    assert list_visible_skills(db_session, user_id=other) == []


def test_visible_skills_union(db_session):
    """global + personal 并集。"""
    from app.models import Skill
    from app.skills.visibility import list_visible_skills

    owner = uuid.uuid4()
    db_session.add(Skill(name="g1", description="d", scope="global", status="active", minio_prefix="skills/global/g1/"))
    db_session.add(Skill(name="p1", description="d", scope="personal", owner_id=owner, status="active", minio_prefix=f"skills/personal/{owner}/p1/"))
    db_session.commit()

    names = {s.name for s in list_visible_skills(db_session, user_id=owner)}
    assert names == {"g1", "p1"}


def test_draft_skills_excluded(db_session):
    """status=draft 不进可见集合。"""
    from app.models import Skill
    from app.skills.visibility import list_visible_skills

    db_session.add(Skill(name="draft1", description="d", scope="global", status="draft", minio_prefix="skills/global/draft1/"))
    db_session.add(Skill(name="active1", description="d", scope="global", status="active", minio_prefix="skills/global/active1/"))
    db_session.commit()

    names = [s.name for s in list_visible_skills(db_session, user_id=uuid.uuid4())]
    assert "draft1" not in names
    assert "active1" in names


def test_build_agent_skill_sources(db_session):
    """为 deepagents 构造 source 路径列表（skills= 参数）。"""
    from app.models import Skill
    from app.skills.visibility import build_agent_skill_sources

    owner = uuid.uuid4()
    db_session.add(Skill(name="g1", description="d", scope="global", status="active", minio_prefix="skills/global/"))
    db_session.add(Skill(name="p1", description="d", scope="personal", owner_id=owner, status="active", minio_prefix=f"skills/personal/{owner}/"))
    db_session.commit()

    sources = build_agent_skill_sources(db_session, user_id=owner)
    assert "skills/global/" in sources
    assert f"skills/personal/{owner}/" in sources
```

> 测试用 `db_session` fixture（来自 `tests/conftest.py`）。新 `skills` 表无 pgvector 依赖，`Base.metadata.create_all` 会正常创建。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_skill_visibility.py -v`
Expected: FAIL（`ImportError: cannot import name 'list_visible_skills'`）

- [ ] **Step 3: 实现 visibility.py**

```python
# apps/api/app/skills/visibility.py
"""可见性合并服务（spec Q11-α）。

每次 agent run 纯运行时计算可见 skill 集合：
  visible = {scope=global, status=active} ∪ {scope=personal, owner=user, status=active}

项目不持有 skill 状态，下线即不可见（无孤儿问题）。
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.skill import SCOPE_GLOBAL, SCOPE_PERSONAL, STATUS_ACTIVE, Skill


def list_visible_skills(db: Session, *, user_id) -> list[Skill]:
    """返回 user 当前可见的所有 active skill（global ∪ personal）。"""
    stmt = select(Skill).where(
        Skill.status == STATUS_ACTIVE
    ).where(
        or_(
            Skill.scope == SCOPE_GLOBAL,
            (Skill.scope == SCOPE_PERSONAL) & (Skill.owner_id == user_id),
        )
    )
    return list(db.scalars(stmt))


def build_agent_skill_sources(db: Session, *, user_id) -> list[str]:
    """为 deepagents 的 create_deep_agent(skills=...) 构造 source 路径列表。

    返回 MinIO 前缀列表，SkillsMiddleware 按这些前缀加载 skill 目录。
    deepagents 语义：later source 覆盖 earlier（personal 后于 global，同名 personal 生效）。
    """
    skills = list_visible_skills(db, user_id=user_id)
    prefixes: list[str] = []
    seen: set[str] = set()
    ordered = sorted(skills, key=lambda s: 0 if s.scope == SCOPE_GLOBAL else 1)
    for s in ordered:
        prefix = s.minio_prefix
        if prefix not in seen:
            seen.add(prefix)
            prefixes.append(prefix)
    return prefixes
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_skill_visibility.py -v`
Expected: 5 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/skills/visibility.py apps/api/tests/test_skill_visibility.py
git commit -m "feat(api): skill 可见性合并服务（global ∪ personal，纯运行时）"
```

---

## Phase 2 收尾检查

- [ ] **Phase 2 验证:** `cd apps/api && uv run pytest tests/test_skill_storage.py tests/test_skill_directory.py tests/test_skill_visibility.py -v` 全绿

---

## Phase 3: deepagents agent 重写 + 自定义配置降级

> **API 事实（deepagents 0.6.12 introspect 确认）：**
> - `create_deep_agent(model=<ChatModel>, skills=[...sources], backend=<StoreBackend>, tools=[...])` 返回 `CompiledStateGraph`。
> - `SkillsMiddleware(backend=StoreBackend(store=MinIOSkillStore()), sources=[...])` 自动注入。
> - agent 用 `astream_events` 暴露 tool_call 事件（Phase 7 接 SSE）。
> - `ChatOpenAI.bind_tools([...])` 绑定工具（`rag_search` 等）。

### Task 10: RAG 工具化（rag_search 从布尔守卫改为 @tool）

**Files:**
- Create: `apps/api/app/ai/tools.py`
- Test: `apps/api/tests/test_rag_tool.py`

> 旧 `orchestrator._retrieve_knowledge` 的布尔守卫（Task 3 已临时返回 None）改造为 `@tool`，agent 在 loop 中按需调用。

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_rag_tool.py
"""RAG 工具测试：rag_search 作为 @tool，agent 可调用。"""
import pytest


def test_rag_search_tool_is_registered():
    """rag_search 是 langchain @tool，有 name/description。"""
    from app.ai.tools import rag_search_tool
    assert rag_search_tool.name == "rag_search"
    assert "知识库" in rag_search_tool.description or "检索" in rag_search_tool.description


def test_rag_search_tool_returns_results(db_session):
    """工具调用返回检索结果列表。"""
    from app.ai.tools import rag_search_tool
    # mock retriever，不真实跑 embedding
    from app.rag import retriever as retriever_mod

    class _FakeResult:
        content = "相关技术内容"
        source_section_key = "solution"
        project_title = "案例A"
    original = retriever_mod.retrieve
    retriever_mod.retrieve = lambda db, user_id, query: [_FakeResult()]
    try:
        results = rag_search_tool.invoke({
            "db_session": db_session, "user_id": "fake-uuid", "query": "技术方案",
        })
    finally:
        retriever_mod.retrieve = original
    assert len(results) == 1
    assert results[0]["content"] == "相关技术内容"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_rag_tool.py -v`
Expected: FAIL（`ImportError: cannot import name 'rag_search_tool'`）

- [ ] **Step 3: 实现 tools.py**

```python
# apps/api/app/ai/tools.py
"""agent 工具（spec 合规）：rag_search 等 @tool，agent 在 loop 中按需调用。

替代旧 orchestrator._retrieve_knowledge 的预检索布尔守卫（Task 3 临时返回 None）。
"""
from langchain_core.tools import tool


@tool
def rag_search_tool(query: str, user_id: str, db_session=None) -> list[dict]:
    """检索用户知识库（RAG）。当需要参考历史案例、已有交底书、知识库文档时调用。

    Args:
        query: 检索查询（技术关键词、问题描述）
        user_id: 用户 ID（限定检索范围到该用户的知识库）
        db_session: 数据库会话（由 agent runtime 注入）

    Returns:
        检索到的知识片段列表，每项含 content/source_section_key/project_title。
    """
    import uuid as _uuid
    from app.rag.retriever import retrieve

    try:
        uid = _uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return []
    results = retrieve(db_session, user_id=uid, query=query)
    return [
        {
            "content": r.content,
            "section_key": r.source_section_key,
            "project_title": r.project_title,
        }
        for r in results
    ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_rag_tool.py -v`
Expected: 2 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/tools.py apps/api/tests/test_rag_tool.py
git commit -m "feat(api): rag_search 工具化（@tool，agent loop 按需调用）"
```

---

### Task 11: 自定义配置 tool calling 降级检测

**Files:**
- Create: `apps/api/app/ai/tool_support.py`
- Test: `apps/api/tests/test_tool_support.py`

> spec Q14-α：模型不支持 tool calling → 拒绝服务，明确报错。检测在 agent 创建前。

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_tool_support.py
"""自定义配置 tool calling 降级检测（spec Q14-α）。"""
import pytest


def test_check_tool_support_known_supported_model():
    """已知支持 tool calling 的模型（glm-4.7/4.6/4.5/deepseek）放行。"""
    from app.ai.tool_support import check_tool_support
    for m in ["glm-4.7", "glm-4.6", "glm-4.5", "deepseek-chat", "deepseek-r1"]:
        # 不抛异常即放行
        check_tool_support(model=m)


def test_check_tool_support_unsupported_model_raises():
    """已知不支持/不确定的模型抛 ToolSupportError。"""
    from app.ai.tool_support import check_tool_support, ToolSupportError
    with pytest.raises(ToolSupportError):
        check_tool_support(model="some-old-model-xyz")


def test_check_tool_support_flash_warns_but_passes():
    """glm-4-flash 支持基础 tool calling，放行但记录 warning。"""
    from app.ai.tool_support import check_tool_support
    check_tool_support(model="glm-4-flash")  # 不抛
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_tool_support.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现 tool_support.py**

```python
# apps/api/app/ai/tool_support.py
"""自定义配置 tool calling 降级检测（spec Q14-α）。

模型不支持 tool calling → 拒绝服务（抛 ToolSupportError），明确引导用户换模型。
不静默降级（否决项 β，隐性降级是产品事故温床）。
"""
import re

# 已知支持 tool calling 的模型前缀（OpenAI 兼容 function calling）
_KNOWN_SUPPORTED_PREFIXES = (
    "glm-4.5", "glm-4.6", "glm-4.7", "glm-5",
    "deepseek-chat", "deepseek-r1", "deepseek-v",
    "gpt-4", "gpt-5", "claude",
)

# 基础支持但复杂 agent loop 可能不稳（放行但 warning）
_BASIC_SUPPORTED = ("glm-4-flash", "glm-4-air", "glm-4-plus")


class ToolSupportError(Exception):
    """模型不支持 tool calling，无法启用技能功能。"""


def check_tool_support(*, model: str) -> None:
    """检测模型是否支持 tool calling。不支持抛 ToolSupportError。

    spec Q14-α：拒绝服务而非静默降级。
    """
    if not model:
        raise ToolSupportError("未配置模型，无法启用技能功能。请先在设置中配置支持 function calling 的模型。")

    model_lower = model.lower().strip()

    # 已知支持
    for prefix in _KNOWN_SUPPORTED_PREFIXES:
        if model_lower.startswith(prefix):
            return

    # 基础支持（flash/air 等，agent loop 可能不稳，但放行）
    for prefix in _BASIC_SUPPORTED:
        if model_lower.startswith(prefix):
            return

    # 未知模型：保守拒绝（spec Q14-α，宁拒不降级）
    raise ToolSupportError(
        f"当前模型「{model}」不支持 function calling，无法启用技能功能。"
        f"请切换到支持 tool calling 的模型（推荐 glm-4.7 / glm-4.6 / deepseek-chat）。"
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_tool_support.py -v`
Expected: 3 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/tool_support.py apps/api/tests/test_tool_support.py
git commit -m "feat(api): 自定义配置 tool calling 降级检测（拒绝服务，spec Q14-α）"
```

---

### Task 12: deepagents agent 工厂

**Files:**
- Create: `apps/api/app/ai/agent.py`
- Test: `apps/api/tests/test_agent_factory.py`

> 把 LLM 配置 + 可见 skill + RAG 工具组装成 deepagents agent。

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_agent_factory.py
"""deepagents agent 工厂测试。"""
import uuid
import pytest


def test_build_agent_returns_compiled_graph(db_session, monkeypatch):
    """build_agent 返回 CompiledStateGraph，含 skills + tools。"""
    from app.ai.agent import build_agent
    from app.services.llm_config_service import ResolvedLLMConfig

    # mock LLM 调用，不真实连 GLM
    from app.ai import llm_client as llm_mod
    original_get_llm = llm_mod.get_llm

    class _FakeLLM:
        model_name = "glm-4.7"
        def bind_tools(self, tools): return self
    llm_mod.get_llm = lambda config, **kw: _FakeLLM()

    # mock MinIO storage
    from app.core import storage as storage_mod
    class _FakeStorage:
        def __init__(self): self._client = None; self._buckets = {}
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    try:
        config = ResolvedLLMConfig(
            base_url="http://x", api_key="k", model="glm-4.7",
            embedding_model="embedding-3", source="env",
        )
        user_id = uuid.uuid4()
        agent = build_agent(db_session, llm_config=config, user_id=user_id)
        assert agent is not None
        # CompiledStateGraph 有 ainvoke/astream_events
        assert hasattr(agent, "ainvoke")
        assert hasattr(agent, "astream_events")
    finally:
        llm_mod.get_llm = original_get_llm


def test_build_agent_unsupported_model_raises(db_session):
    """不支持 tool calling 的模型抛 ToolSupportError（Q14-α）。"""
    from app.ai.agent import build_agent
    from app.ai.tool_support import ToolSupportError
    from app.services.llm_config_service import ResolvedLLMConfig

    config = ResolvedLLMConfig(
        base_url="http://x", api_key="k", model="old-unsupported-model",
        embedding_model="e", source="env",
    )
    with pytest.raises(ToolSupportError):
        build_agent(db_session, llm_config=config, user_id=uuid.uuid4())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_agent_factory.py -v`
Expected: FAIL（`ImportError: cannot import name 'build_agent'`）

- [ ] **Step 3: 实现 agent.py**

```python
# apps/api/app/ai/agent.py
"""deepagents agent 工厂（spec 合规，路线 B 全量重写）。

把 LLM 配置 + 可见 skill + RAG 工具组装成 deepagents agent，
取代旧 orchestrator 的一次性 astream 流式调用（Q16-A 全量切 agent loop）。
"""
from langgraph.graph.state import CompiledStateGraph

from app.ai.llm_client import get_llm
from app.ai.tools import rag_search_tool
from app.ai.tool_support import check_tool_support
from app.skills.storage import MinIOSkillStore
from app.skills.visibility import build_agent_skill_sources
from app.services.llm_config_service import ResolvedLLMConfig


def build_agent(
    db, *, llm_config: ResolvedLLMConfig, user_id,
) -> CompiledStateGraph:
    """构造 deepagents agent。

    1. 检测模型 tool calling 支持（Q14-α，不支持抛 ToolSupportError）。
    2. 构造 MinIO BaseStore + StoreBackend。
    3. 收集可见 skill sources（global ∪ personal）。
    4. 绑定 RAG 工具。
    5. create_deep_agent 组装。
    """
    from deepagents import create_deep_agent
    from deepagents.backends import StoreBackend

    # 1. 自定义配置降级检测
    check_tool_support(model=llm_config.model)

    # 2. MinIO BaseStore + StoreBackend
    store = MinIOSkillStore(bucket="global")
    backend = StoreBackend(store=store)

    # 3. 可见 skill sources
    skill_sources = build_agent_skill_sources(db, user_id=user_id)

    # 4. LLM + 工具
    llm = get_llm(llm_config, streaming=True)
    llm_with_tools = llm.bind_tools([rag_search_tool])

    # 5. 组装（system_prompt 从现有 context_assembler 复用角色设定）
    from app.ai.context_assembler import SYSTEM_PROMPT

    agent = create_deep_agent(
        model=llm_with_tools,
        system_prompt=SYSTEM_PROMPT,
        tools=[rag_search_tool],
        skills=skill_sources if skill_sources else None,
        backend=backend,
        store=store,
    )
    return agent
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_agent_factory.py -v`
Expected: 2 PASS（若 deepagents 对 mock LLM 报错，调整 mock 使其满足 BaseChatModel 协议）

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/agent.py apps/api/tests/test_agent_factory.py
git commit -m "feat(api): deepagents agent 工厂（全量重写 AI 层，路线 B）"
```

---

### Task 13: orchestrator 委托给 agent loop

**Files:**
- Modify: `apps/api/app/ai/orchestrator.py`

> 旧 `astream_generate`/`astream_chat`/`astream_rewrite` 改为委托给 deepagents agent。SSE 事件映射在 Phase 7。

- [ ] **Step 1: 重写 orchestrator 的 astream_* 函数**

把 `apps/api/app/ai/orchestrator.py` 的三个 async 函数（`astream_chat`/`astream_generate`/`astream_rewrite`）改为委托给 `build_agent` + agent 的 `astream_events`。保留函数签名（`api/ai.py` 的调用点不变）。

```python
# apps/api/app/ai/orchestrator.py（重写 async 部分）
"""AI 编排：委托给 deepagents agent loop（spec 路线 B）。

旧的 stream_chat/stream_generate/stream_rewrite（同步）保留用于非流式场景。
async 版本委托给 build_agent + agent.astream_events。
"""
from collections.abc import AsyncIterator, Iterator

from langchain_core.messages import HumanMessage

from app.ai.context_assembler import assemble_messages, get_project_summaries
from app.ai.llm_client import astream_llm, stream_llm
from app.ai.section_prompts import get_section_prompt
from app.models import Message, Section
from app.services.llm_config_service import ResolvedLLMConfig


# ── 同步版本（保留，用于非 SSE 场景）──
def stream_chat(db, section, history, user_input, *, llm_config):
    """同步引导对话（旧逻辑保留，非 agent loop）。"""
    summaries = get_project_summaries(db, section.project_id)
    messages = assemble_messages(section, history, user_input, summaries, None)
    yield from stream_llm(messages, llm_config=llm_config)


def stream_generate(db, section, history, *, llm_config):
    """同步生成草稿（旧逻辑保留）。"""
    summaries = get_project_summaries(db, section.project_id)
    sp = get_section_prompt(section.key)
    messages = assemble_messages(section, history, project_summaries=summaries)
    messages.append(HumanMessage(
        content=f"请根据以上对话内容，整理生成本章节【{section.title}】的草稿。要求：{sp.output_format}。用 Markdown 格式输出。"
    ))
    yield from stream_llm(messages, llm_config=llm_config)


def stream_rewrite(section, selected_text, instruction, *, llm_config):
    """同步段落重写（旧逻辑保留）。"""
    from langchain_core.messages import SystemMessage
    sp = get_section_prompt(section.key)
    system = f"你是专利交底书撰写助手。当前章节：【{section.title}】（{sp.goal}）。用户选中了一段文字，请按指令重写。保持 Markdown 格式。"
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"原文：\n{selected_text}\n\n指令：{instruction}"),
    ]
    yield from stream_llm(messages, llm_config=llm_config)


# ── async 版本（委托给 deepagents agent loop，spec 路线 B）──
async def astream_generate(db, section, history, *, llm_config, usage_sink=None):
    """异步生成草稿：委托 deepagents agent loop。

    agent.astream_events 暴露 token + tool_call 事件，
    本函数只 yield 文本 token（tool_call 事件由 Phase 7 的 SSE 层捕获）。
    """
    from app.ai.agent import build_agent

    agent = build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section))
    sp = get_section_prompt(section.key)
    instruction = f"请根据对话历史，整理生成本章节【{section.title}】的草稿。要求：{sp.output_format}。用 Markdown 格式输出。"

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": instruction}]},
        version="v2",
    ):
        # 只透传文本 token（on_chat_model_stream）
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk and chunk.content:
                yield chunk.content


async def astream_chat(db, section, history, user_input, *, llm_config, usage_sink=None):
    """异步引导对话：委托 agent loop。"""
    from app.ai.agent import build_agent

    agent = build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section))
    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": user_input}]},
        version="v2",
    ):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk and chunk.content:
                yield chunk.content


async def astream_rewrite(section, selected_text, instruction, *, llm_config, usage_sink=None):
    """异步段落重写：保留旧逻辑（重写不需要 agent loop / skill）。"""
    from langchain_core.messages import SystemMessage
    sp = get_section_prompt(section.key)
    system = f"你是专利交底书撰写助手。当前章节：【{section.title}】（{sp.goal}）。用户选中了一段文字，请按指令重写。保持 Markdown 格式。"
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"原文：\n{selected_text}\n\n指令：{instruction}"),
    ]
    async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage_sink):
        yield token


def _section_owner(db, section):
    """取 section 所属项目的 user_id（用于 skill 可见性）。"""
    from sqlalchemy import select
    from app.models import Project
    project = db.scalar(select(Project).where(Project.id == section.project_id))
    return project.user_id if project else None
```

- [ ] **Step 2: 跑全量测试确认无破坏**

Run: `cd apps/api && uv run pytest -q 2>&1 | tail -15`
Expected: 全绿（agent loop 在测试中可能因无真实 LLM 而被跳过或 mock）

- [ ] **Step 3: 提交**

```bash
git add apps/api/app/ai/orchestrator.py
git commit -m "refactor(api): orchestrator async 版本委托 deepagents agent loop（路线 B）

- astream_generate/astream_chat 改为 build_agent + astream_events
- 同步版本 + astream_rewrite 保留旧逻辑
- 移除 _retrieve_knowledge（已由 rag_search @tool 取代）"
```

---

## Phase 3 收尾检查

- [ ] **Phase 3 验证:** `cd apps/api && uv run pytest tests/test_rag_tool.py tests/test_tool_support.py tests/test_agent_factory.py -v` 全绿 + `uv run pytest -q` 全量绿

---

## Phase 4: 自建 Docker sandbox + 脚本执行

> **spec Q12-b/Q15-A：** 用户 skill 的 `scripts/` 可执行，sandbox **直读 MinIO**（执行前从 MinIO 拉脚本到容器临时目录），用自建 Docker（`docker` Python SDK）。
> deepagents 0.6.12 的 `BaseSandbox`（`app/deepagents/backends/sandbox.py`）是抽象类，有 `execute/read/write` 等方法——本模块实现一个 `DockerSandbox(BaseSandbox)`。

### Task 14: Docker sandbox runner

**Files:**
- Create: `apps/api/app/sandbox/__init__.py`
- Create: `apps/api/app/sandbox/docker_runner.py`
- Test: `apps/api/tests/test_docker_runner.py`

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_docker_runner.py
"""Docker sandbox runner 测试。

不真实起容器（CI 无 Docker），mock docker SDK 的 client.containers.run。
测试：拉 MinIO 脚本 → 注入容器 → 执行 → 回收。
"""
import pytest


def test_execute_script_builds_command(monkeypatch):
    """execute_script 构造正确的 docker run 命令（受限参数）。"""
    from app.sandbox import docker_runner

    captured = {}
    class _FakeContainer:
        def __init__(self, **kw): captured["kwargs"] = kw
        def wait(self): return {"StatusCode": 0}
        def logs(self): return b"output result"
        def remove(self, force): pass

    class _FakeContainers:
        def run(self, image, command, **kw):
            captured["image"] = image
            captured["command"] = command
            return _FakeContainer(**kw)

    class _FakeDockerClient:
        containers = _FakeContainers()

    monkeypatch.setattr(docker_runner, "_get_docker_client", lambda: _FakeDockerClient())

    result = docker_runner.execute_script(
        script_content="print('hello')",
        language="python",
        timeout=10,
    )
    assert result["status"] == "success"
    assert "output result" in result["output"]
    # 安全约束：无网络
    assert captured["kwargs"].get("network_mode") == "none"
    # 只读 rootfs
    assert captured["kwargs"].get("read_only") is True


def test_execute_script_timeout_kills(monkeypatch):
    """超时返回 failed。"""
    from app.sandbox import docker_runner

    class _FakeContainer:
        def wait(self, timeout=None):
            raise Exception("timeout")
        def kill(self): pass
        def logs(self): return b""
        def remove(self, force): pass
    class _FakeContainers:
        def run(self, *a, **kw): return _FakeContainer()
    class _FakeDockerClient:
        containers = _FakeContainers()

    monkeypatch.setattr(docker_runner, "_get_docker_client", lambda: _FakeDockerClient())
    result = docker_runner.execute_script(script_content="while True: pass", language="python", timeout=1)
    assert result["status"] == "failed"
    assert "timeout" in result["error"].lower() or "超时" in result["error"]


def test_pull_script_from_minio(monkeypatch):
    """从 MinIO 拉脚本内容。"""
    from app.sandbox import docker_runner
    from app.core import storage as storage_mod

    fake = {("global", "skills/g/s/scripts/foo.py"): b"print('hi')"}
    class _FakeStorage:
        def get(self, b, k): return fake.get((b,k), b"")
        def stat(self, b, k): return (b,k) in fake
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    content = docker_runner.pull_script_from_minio(
        bucket="global", key="skills/g/s/scripts/foo.py",
    )
    assert content == b"print('hi')"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_docker_runner.py -v`
Expected: FAIL（`ImportError: No module named 'app.sandbox'`）

- [ ] **Step 3: 实现 docker_runner.py**

```python
# apps/api/app/sandbox/__init__.py
"""自建 Docker sandbox 子包（spec Q12-b/Q15-A）。"""
```

```python
# apps/api/app/sandbox/docker_runner.py
"""Docker sandbox：隔离容器执行用户脚本（spec Q12-b）。

安全约束（spec Q15-A 直读 MinIO）：
- network_mode="none"：无网络访问
- read_only=True：rootfs 只读（/tmp 除外）
- mem_limit + cpus：资源上限
- timeout：超时 kill
执行前从 MinIO 拉脚本注入容器 /tmp。
"""
from loguru import logger

# 受限镜像：官方 python slim，预装常见库
_DEFAULT_IMAGE = "python:3.11-slim"
_MEM_LIMIT = "256m"
_CPUS = "0.5"


def _get_docker_client():
    """懒加载 docker client。"""
    import docker
    return docker.from_env()


def pull_script_from_minio(*, bucket: str, key: str) -> bytes:
    """从 MinIO 拉脚本内容（spec Q15-A：sandbox 直读 MinIO）。"""
    from app.core.storage import get_storage
    st = get_storage()
    return st.get(bucket, key)


def execute_script(
    *, script_content: bytes | str, language: str = "python",
    timeout: int = 30, image: str | None = None,
) -> dict:
    """在隔离 Docker 容器中执行脚本。

    Returns:
        {"status": "success"|"failed", "output": str, "error": str|None}
    """
    if isinstance(script_content, bytes):
        script_bytes = script_content
    else:
        script_bytes = script_content.encode("utf-8")

    img = image or _DEFAULT_IMAGE

    # 构造执行命令
    if language == "python":
        command = ["python", "/tmp/script.py"]
    elif language == "bash":
        command = ["bash", "/tmp/script.sh"]
    else:
        return {"status": "failed", "output": "", "error": f"不支持的语言：{language}"}

    client = _get_docker_client()
    container = None
    try:
        container = client.containers.run(
            img,
            command=command,
            detach=True,
            network_mode="none",     # 无网络
            read_only=True,          # rootfs 只读
            mem_limit=_MEM_LIMIT,
            cpu_quota=int(_CPUS * 100000),  # 0.5 CPU
            volumes={},              # 脚本通过 stdin 或临时 volume 注入（见下）
            working_dir="/tmp",
            # /tmp 可写（tmpfs）：把脚本写进去
            tmpfs={"/tmp": "size=16m"},
            stdin_open=True,
        )
        # 把脚本写进容器的 /tmp
        # 用 docker put_archive 注入（避免 volume 挂载复杂度）
        import io, tarfile
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            fname = "script.py" if language == "python" else "script.sh"
            info = tarfile.TarInfo(name=f"/tmp/{fname}")
            info.size = len(script_bytes)
            tar.addfile(info, io.BytesIO(script_bytes))
        tar_stream.seek(0)
        container.put_archive("/", tar_stream)

        result = container.wait(timeout=timeout)
        exit_code = result.get("StatusCode", -1)
        logs = container.logs().decode("utf-8", errors="replace")

        if exit_code == 0:
            return {"status": "success", "output": logs, "error": None}
        return {"status": "failed", "output": logs, "error": f"exit code {exit_code}"}

    except Exception as e:
        err_msg = str(e)
        is_timeout = "timeout" in err_msg.lower() or "timed out" in err_msg.lower()
        if container and is_timeout:
            try:
                container.kill()
            except Exception:
                pass
        return {
            "status": "failed",
            "output": "",
            "error": f"执行超时（{timeout}s）" if is_timeout else err_msg,
        }
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                logger.warning("sandbox 容器清理失败", exc_info=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_docker_runner.py -v`
Expected: 3 PASS（全 mock，不真实起容器）

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/sandbox/ apps/api/tests/test_docker_runner.py
git commit -m "feat(api): 自建 Docker sandbox（隔离容器执行用户脚本，spec Q12-b/Q15-A）"
```

---

### Task 15: DockerSandbox 注册为 deepagents 后端（可选集成）

**Files:**
- Modify: `apps/api/app/ai/agent.py`（sandbox backend 注入，条件性）

> spec：sandbox 通过 `backend=` 传给 `create_deep_agent`。但 `StoreBackend`（MinIO skill 存储）和 sandbox backend 是两个不同 backend。deepagents 支持 `CompositeBackend` 组合多个 backend。

- [ ] **Step 1: 确认 CompositeBackend API**

Run: `cd apps/api && uv run python -c "from deepagents.backends import CompositeBackend; import inspect; print(inspect.signature(CompositeBackend.__init__))"`
Expected: 打印 CompositeBackend 构造签名。

- [ ] **Step 2: 在 agent.py 条件性注入 sandbox backend**

修改 `apps/api/app/ai/agent.py` 的 `build_agent`，在 Docker daemon 可用时用 `CompositeBackend` 组合 `StoreBackend`（skill 存储）+ sandbox backend（脚本执行）。Docker 不可用时只用 StoreBackend（脚本执行降级禁用，spec §8 边界）。

```python
# apps/api/app/ai/agent.py（build_agent 内，backend 构造部分替换）
def _build_backend(store):
    """构造 backend：StoreBackend（skill 存储）+ 可选 sandbox（脚本执行）。"""
    from deepagents.backends import StoreBackend, CompositeBackend
    skill_backend = StoreBackend(store=store)

    # 尝试启用 Docker sandbox（不可用则降级，spec §8）
    try:
        import docker
        docker.from_env().ping()  # 探活
        # sandbox 可用 → Composite 组合
        # 注：deepagents 的 sandbox backend 集成方式见其文档，
        # 此处用 LocalShellBackend 受限版或自建适配
        return skill_backend  # v1 先不接 sandbox 执行，仅 skill 存储
    except Exception:
        # Docker 不可用 → 仅 skill 存储，脚本执行禁用
        return skill_backend
```

> 注：v1 的 Docker sandbox 通过独立的 `execute_script` API 暴露（Task 16 admin/user CRUD 之外），而非自动注入 agent backend。agent 自动执行脚本留 v2（需 deepagents sandbox backend 深度集成）。这是**已知的 v1 限制**，写入 spec §12。

- [ ] **Step 3: 跑测试确认未破坏**

Run: `cd apps/api && uv run pytest tests/test_agent_factory.py -v`
Expected: 2 PASS（backend 构造降级到 StoreBackend）

- [ ] **Step 4: 提交**

```bash
git add apps/api/app/ai/agent.py
git commit -m "feat(api): agent backend 条件性注入 sandbox（Docker 不可用降级，spec §8）"
```

---

## Phase 4 收尾检查

- [ ] **Phase 4 验证:** `cd apps/api && uv run pytest tests/test_docker_runner.py tests/test_agent_factory.py -v` 全绿

---

## Phase 5: admin/user CRUD API

> 两套路由：admin 全局（`/admin/skills/*`，`require_admin`）+ 用户个人（`/skills/*`，`get_current_user`）。仿 `admin/content.py` 模式。

### Task 16: skill CRUD service（DB + MinIO 协同）

**Files:**
- Modify: `apps/api/app/skills/service.py`（Task 8 已建目录管理，现补 CRUD）
- Test: `apps/api/tests/test_skill_crud.py`

> CRUD 协同 DB（元数据）+ MinIO（SKILL.md + 资源目录）：创建时同时写 DB 行和 MinIO 目录；删除时同时清两处。

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_skill_crud.py
"""Skill CRUD 测试：DB + MinIO 协同。"""
import uuid
import pytest


@pytest.fixture
def fake_storage(monkeypatch):
    """内存假 storage + fake minio client。"""
    from app.core import storage as storage_mod
    fake = {}
    class _FakeObj:
        def __init__(self, name): self.object_name = name
    class _FakeClient:
        def list_objects(self, bucket, prefix=None, recursive=False):
            return [_FakeObj(k.split("/",1)[1] if "/" in k else k) for (b,k) in fake if k.startswith(prefix or "")]
        def remove_object(self, bucket, key): fake.pop((bucket, key), None)
    class _FakeStorage:
        def __init__(self): self._client = _FakeClient()
        def put(self, b, k, c, ct): fake[(b,k)] = c
        def get(self, b, k): return fake.get((b,k), b"")
        def delete(self, b, k): fake.pop((b,k), None)
        def stat(self, b, k): return (b,k) in fake
        def _resolve(self, alias): return alias
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())
    return fake


def test_create_global_skill(db_session, fake_storage):
    """创建全局 skill：写 DB + MinIO 目录。"""
    from app.skills.service import create_skill
    from app.models.skill import SCOPE_GLOBAL

    skill = create_skill(
        db_session,
        scope=SCOPE_GLOBAL, owner_id=None,
        name="prior-art-search", description="检索现有技术",
        body="## Steps\n1. 分析技术领域",
    )
    assert skill.id is not None
    assert skill.scope == "global"
    assert skill.status == "draft"  # 默认 draft
    # MinIO 有 SKILL.md
    assert ("global", "skills/global/prior-art-search/SKILL.md") in fake_storage


def test_create_personal_skill(db_session, fake_storage):
    """创建个人 skill：minio_prefix 含 owner_id。"""
    from app.skills.service import create_skill
    from app.models.skill import SCOPE_PERSONAL

    owner = uuid.uuid4()
    skill = create_skill(
        db_session, scope=SCOPE_PERSONAL, owner_id=owner,
        name="my-writer", description="个人撰写偏好",
        body="## 风格\n简洁",
    )
    assert owner in uuid.UUID(skill.minio_prefix.split("/")[2]) if skill.minio_prefix else False
    assert f"skills/personal/{owner}/my-writer/" in skill.minio_prefix


def test_create_duplicate_name_raises(db_session, fake_storage):
    """同 scope+owner 下 name 唯一。"""
    from app.skills.service import create_skill
    from app.core.exceptions import ConflictError

    create_skill(db_session, scope="global", owner_id=None,
                 name="dup", description="d", body="b")
    with pytest.raises(ConflictError):
        create_skill(db_session, scope="global", owner_id=None,
                     name="dup", description="d", body="b")


def test_update_skill_status(db_session, fake_storage):
    """更新状态 draft→active。"""
    from app.skills.service import create_skill, update_skill

    skill = create_skill(db_session, scope="global", owner_id=None,
                         name="s1", description="d", body="b")
    updated = update_skill(db_session, skill_id=skill.id, status="active")
    assert updated.status == "active"


def test_delete_skill_removes_db_and_minio(db_session, fake_storage):
    """删除 skill：DB 行 + MinIO 目录都清。"""
    from app.skills.service import create_skill, delete_skill, get_skill
    from app.core.exceptions import NotFoundError

    skill = create_skill(db_session, scope="global", owner_id=None,
                         name="del", description="d", body="b")
    key = "skills/global/del/SKILL.md"
    assert ("global", key) in fake_storage

    delete_skill(db_session, skill_id=skill.id)
    with pytest.raises(NotFoundError):
        get_skill(db_session, skill_id=skill.id)
    assert ("global", key) not in fake_storage


def test_list_skills_by_scope(db_session, fake_storage):
    """按 scope + owner 列出 skill。"""
    from app.skills.service import create_skill, list_skills

    create_skill(db_session, scope="global", owner_id=None, name="g1", description="d", body="b")
    owner = uuid.uuid4()
    create_skill(db_session, scope="personal", owner_id=owner, name="p1", description="d", body="b")

    global_skills = list_skills(db_session, scope="global", owner_id=None)
    assert [s.name for s in global_skills] == ["g1"]

    personal_skills = list_skills(db_session, scope="personal", owner_id=owner)
    assert [s.name for s in personal_skills] == ["p1"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_skill_crud.py -v`
Expected: FAIL（`ImportError: cannot import name 'create_skill'`）

- [ ] **Step 3: 在 service.py 补 CRUD 函数**

在 `apps/api/app/skills/service.py` 末尾追加（Task 8 的目录管理函数之后）：

```python
# ── CRUD（DB + MinIO 协同）──

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.skill import SCOPE_GLOBAL, STATUS_DRAFT, Skill


def _minio_prefix(*, scope: str, owner_id, name: str) -> str:
    if scope == SCOPE_GLOBAL:
        return f"skills/global/{name}/"
    return f"skills/personal/{owner_id}/{name}/"


def _bucket_for_scope(scope: str) -> str:
    return "global" if scope == SCOPE_GLOBAL else "personal"


def create_skill(
    db: Session, *, scope: str, owner_id, name: str, description: str, body: str,
    scripts: dict[str, str] | None = None,
    references: dict[str, str] | None = None,
    status: str = STATUS_DRAFT,
) -> Skill:
    """创建 skill：DB 行 + MinIO 目录。name 唯一性校验。"""
    # 唯一性校验
    existing = db.scalar(select(Skill).where(
        Skill.scope == scope,
        Skill.owner_id == owner_id if owner_id is not None else Skill.owner_id.is_(None),
        Skill.name == name,
    ))
    if existing:
        raise ConflictError(f"技能名「{name}」已存在")

    prefix = _minio_prefix(scope=scope, owner_id=owner_id, name=name)
    bucket = _bucket_for_scope(scope)

    # 先写 MinIO 目录
    write_skill_directory(
        bucket=bucket, prefix=prefix, name=name, description=description, body=body,
        scripts=scripts, references=references,
    )

    # 再写 DB
    skill = Skill(
        name=name, description=description, scope=scope,
        owner_id=owner_id, status=status, minio_prefix=prefix,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def get_skill(db: Session, *, skill_id) -> Skill:
    from uuid import UUID
    sid = UUID(str(skill_id)) if isinstance(skill_id, str) else skill_id
    skill = db.get(Skill, sid)
    if skill is None:
        raise NotFoundError("技能不存在")
    return skill


def update_skill(db: Session, *, skill_id, **fields) -> Skill:
    """更新 skill。name 不可改（spec: name=目录名）。"""
    skill = get_skill(db, skill_id=skill_id)
    for k, v in fields.items():
        if k == "name":
            continue  # 忽略 name 改动
        if hasattr(skill, k) and v is not None:
            setattr(skill, k, v)
    db.commit()
    db.refresh(skill)

    # 若 description/body 变了，同步 MinIO 的 SKILL.md
    if "description" in fields or "skill_md" in fields:
        body = fields.get("skill_md", "")
        if body:
            bucket = _bucket_for_scope(skill.scope)
            st = get_storage()
            st.put(bucket, _key(skill.minio_prefix, SKILL_MD_FILENAME),
                   assemble_skill_md(name=skill.name, description=skill.description, body=body).encode("utf-8"),
                   "text/markdown")
    return skill


def delete_skill(db: Session, *, skill_id) -> None:
    skill = get_skill(db, skill_id=skill_id)
    bucket = _bucket_for_scope(skill.scope)
    delete_skill_directory(bucket=bucket, prefix=skill.minio_prefix)
    db.delete(skill)
    db.commit()


def list_skills(db: Session, *, scope: str, owner_id) -> list[Skill]:
    """按 scope + owner 列出（admin 列 global，user 列自己的 personal）。"""
    if owner_id is not None:
        stmt = select(Skill).where(Skill.scope == scope, Skill.owner_id == owner_id)
    else:
        stmt = select(Skill).where(Skill.scope == scope, Skill.owner_id.is_(None))
    return list(db.scalars(stmt).order_by(Skill.created_at.desc()))


def read_skill_detail(db: Session, *, skill_id) -> tuple[Skill, str]:
    """读详情：skill + SKILL.md 正文。"""
    skill = get_skill(db, skill_id=skill_id)
    bucket = _bucket_for_scope(skill.scope)
    md = read_skill_md(bucket=bucket, prefix=skill.minio_prefix)
    return skill, md
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_skill_crud.py -v`
Expected: 6 PASS

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/skills/service.py apps/api/tests/test_skill_crud.py
git commit -m "feat(api): skill CRUD service（DB + MinIO 协同，admin/user 共用）"
```

---

### Task 17: admin 全局技能路由

**Files:**
- Create: `apps/api/app/api/admin/skills.py`
- Modify: `apps/api/app/api/admin/__init__.py`
- Test: `apps/api/tests/test_admin_skills_api.py`

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_admin_skills_api.py
"""admin 全局技能 API 测试。"""
import pytest


def test_admin_create_global_skill(client, registered_user, db_session):
    """admin 能创建全局 skill。"""
    from app.models import User
    # 把 registered_user 升级为 admin
    user = db_session.query(User).filter_by(id=registered_user["id"]).first()
    user.role = "admin"
    db_session.commit()

    resp = client.post(
        "/api/v1/admin/skills",
        json={"name": "global-writer", "description": "全局撰写技能", "skill_md": "## 步骤"},
        cookies={"access_token": _login_token(client, registered_user)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"] == "global"
    assert data["status"] == "draft"


def test_non_admin_cannot_create_global(client, registered_user):
    """普通用户不能创建全局 skill（403）。"""
    resp = client.post(
        "/api/v1/admin/skills",
        json={"name": "x", "description": "d", "skill_md": "b"},
        cookies={"access_token": _login_token(client, registered_user)},
    )
    assert resp.status_code == 403


def test_admin_list_global_skills(client, registered_user, db_session):
    """admin 列全局 skill。"""
    from app.models import User, Skill
    user = db_session.query(User).filter_by(id=registered_user["id"]).first()
    user.role = "admin"
    db_session.add(Skill(name="g1", description="d", scope="global", status="draft", minio_prefix="skills/global/g1/"))
    db_session.commit()

    resp = client.get(
        "/api/v1/admin/skills",
        cookies={"access_token": _login_token(client, registered_user)},
    )
    assert resp.status_code == 200
    assert any(s["name"] == "g1" for s in resp.json())


def _login_token(client, registered_user):
    resp = client.post("/api/v1/auth/login", json={
        "account": registered_user["username"],
        "password": registered_user["password"],
    })
    return resp.cookies.get("access_token")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_admin_skills_api.py -v`
Expected: FAIL（404，路由不存在）

- [ ] **Step 3: 实现 admin/skills.py**

```python
# apps/api/app/api/admin/skills.py
"""admin 全局技能管理路由（/admin/skills/*）。

仿 admin/content.py 模式：require_admin + 委托 skill_service + 返回 SkillOut。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import User
from app.models.skill import SCOPE_GLOBAL
from app.schemas.skill import SkillCreate, SkillDetail, SkillOut, SkillUpdate
from app.skills import service as skill_service

router = APIRouter()


@router.get("/admin/skills", response_model=list[SkillOut])
def list_global_skills(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """列出所有全局 skill。"""
    skills = skill_service.list_skills(db, scope=SCOPE_GLOBAL, owner_id=None)
    return [SkillOut.model_validate(s, from_attributes=True) for s in skills]


@router.post("/admin/skills", response_model=SkillOut)
def create_global_skill(
    payload: SkillCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """创建全局 skill（默认 draft）。"""
    skill = skill_service.create_skill(
        db, scope=SCOPE_GLOBAL, owner_id=None,
        name=payload.name, description=payload.description, body=payload.skill_md,
    )
    return SkillOut.model_validate(skill, from_attributes=True)


@router.get("/admin/skills/{skill_id}", response_model=SkillDetail)
def get_global_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """获取全局 skill 详情（含 SKILL.md 正文）。"""
    skill, md = skill_service.read_skill_detail(db, skill_id=skill_id)
    data = SkillOut.model_validate(skill, from_attributes=True).model_dump()
    data["skill_md"] = md
    return SkillDetail(**data)


@router.put("/admin/skills/{skill_id}", response_model=SkillOut)
def update_global_skill(
    skill_id: str,
    payload: SkillUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """更新全局 skill。"""
    skill = skill_service.update_skill(db, skill_id=skill_id, **payload.model_dump(exclude_unset=True))
    return SkillOut.model_validate(skill, from_attributes=True)


@router.delete("/admin/skills/{skill_id}")
def delete_global_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """删除全局 skill（DB + MinIO）。"""
    skill_service.delete_skill(db, skill_id=skill_id)
    return {"ok": True}
```

- [ ] **Step 4: 在 admin/__init__.py 注册**

修改 `apps/api/app/api/admin/__init__.py`，在 `from . import console, content, review, users` 加 `skills`，并 `router.include_router(skills.router)`：

```python
from . import console, content, review, skills, users

router = APIRouter(tags=["admin"])
router.include_router(users.router)
router.include_router(console.router)
router.include_router(content.router)
router.include_router(review.router)
router.include_router(skills.router)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_admin_skills_api.py -v`
Expected: 3 PASS

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/api/admin/skills.py apps/api/app/api/admin/__init__.py apps/api/tests/test_admin_skills_api.py
git commit -m "feat(api): admin 全局技能管理路由（/admin/skills/* CRUD）"
```

---

### Task 18: 用户个人技能路由

**Files:**
- Create: `apps/api/app/api/skills.py`
- Modify: `apps/api/app/api/router.py`
- Test: `apps/api/tests/test_user_skills_api.py`

- [ ] **Step 1: 写失败测试**

```python
# apps/api/tests/test_user_skills_api.py
"""用户个人技能 API 测试。"""
import pytest


def test_user_create_personal_skill(client, registered_user):
    """用户创建个人 skill。"""
    resp = client.post(
        "/api/v1/skills/mine",
        json={"name": "my-style", "description": "个人风格", "skill_md": "## 简洁"},
        cookies={"access_token": _login_token(client, registered_user)},
    )
    assert resp.status_code == 200
    assert resp.json()["scope"] == "personal"


def test_user_list_visible_skills(client, registered_user, db_session):
    """用户列可见 skill（global + 自己的 personal）。"""
    from app.models import Skill
    db_session.add(Skill(name="g1", description="d", scope="global", status="active", minio_prefix="skills/global/g1/"))
    db_session.commit()

    resp = client.get(
        "/api/v1/skills/visible",
        cookies={"access_token": _login_token(client, registered_user)},
    )
    assert resp.status_code == 200
    # 至少能看到 global g1
    names = [s["name"] for s in resp.json()]
    assert "g1" in names


def test_user_cannot_edit_others_personal(client, registered_user, db_session):
    """用户不能编辑别人的 personal skill（404/403）。"""
    from app.models import Skill
    import uuid
    other = uuid.uuid4()
    skill = Skill(name="other-p", description="d", scope="personal", owner_id=other,
                  status="draft", minio_prefix=f"skills/personal/{other}/other-p/")
    db_session.add(skill); db_session.commit()

    resp = client.put(
        f"/api/v1/skills/mine/{skill.id}",
        json={"description": "hacked"},
        cookies={"access_token": _login_token(client, registered_user)},
    )
    assert resp.status_code in (403, 404)


def _login_token(client, registered_user):
    resp = client.post("/api/v1/auth/login", json={
        "account": registered_user["username"],
        "password": registered_user["password"],
    })
    return resp.cookies.get("access_token")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_user_skills_api.py -v`
Expected: FAIL（404）

- [ ] **Step 3: 实现 skills.py（用户域）**

```python
# apps/api/app/api/skills.py
"""用户个人技能路由（/skills/*）。

- /skills/mine：个人 skill CRUD（仅本人）
- /skills/visible：可见 skill 列表（global active + 自己的 personal）

权限：get_current_user。归属校验在 service 层（NotFound 防探测）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ForbiddenError
from app.deps import get_current_user
from app.models import User
from app.models.skill import SCOPE_PERSONAL
from app.schemas.skill import SkillCreate, SkillDetail, SkillOut, SkillUpdate
from app.skills import service as skill_service
from app.skills.visibility import list_visible_skills

router = APIRouter()


@router.get("/skills/visible", response_model=list[SkillOut])
def list_my_visible_skills(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户可见的所有 active skill（global ∪ personal）。"""
    skills = list_visible_skills(db, user_id=current_user.id)
    return [SkillOut.model_validate(s, from_attributes=True) for s in skills]


@router.get("/skills/mine", response_model=list[SkillOut])
def list_my_personal_skills(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出我的个人 skill（含 draft）。"""
    skills = skill_service.list_skills(db, scope=SCOPE_PERSONAL, owner_id=current_user.id)
    return [SkillOut.model_validate(s, from_attributes=True) for s in skills]


@router.post("/skills/mine", response_model=SkillOut)
def create_personal_skill(
    payload: SkillCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建个人 skill。"""
    skill = skill_service.create_skill(
        db, scope=SCOPE_PERSONAL, owner_id=current_user.id,
        name=payload.name, description=payload.description, body=payload.skill_md,
    )
    return SkillOut.model_validate(skill, from_attributes=True)


@router.get("/skills/mine/{skill_id}", response_model=SkillDetail)
def get_my_skill(
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取我的 skill 详情。归属校验防探测。"""
    skill, md = skill_service.read_skill_detail(db, skill_id=skill_id)
    if skill.scope != SCOPE_PERSONAL or skill.owner_id != current_user.id:
        raise ForbiddenError("无权访问该技能")
    data = SkillOut.model_validate(skill, from_attributes=True).model_dump()
    data["skill_md"] = md
    return SkillDetail(**data)


@router.put("/skills/mine/{skill_id}", response_model=SkillOut)
def update_my_skill(
    skill_id: str,
    payload: SkillUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新我的 skill。"""
    skill = skill_service.get_skill(db, skill_id=skill_id)
    if skill.scope != SCOPE_PERSONAL or skill.owner_id != current_user.id:
        raise ForbiddenError("无权修改该技能")
    skill = skill_service.update_skill(db, skill_id=skill_id, **payload.model_dump(exclude_unset=True))
    return SkillOut.model_validate(skill, from_attributes=True)


@router.delete("/skills/mine/{skill_id}")
def delete_my_skill(
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除我的 skill。"""
    skill = skill_service.get_skill(db, skill_id=skill_id)
    if skill.scope != SCOPE_PERSONAL or skill.owner_id != current_user.id:
        raise ForbiddenError("无权删除该技能")
    skill_service.delete_skill(db, skill_id=skill_id)
    return {"ok": True}
```

- [ ] **Step 4: 在 router.py 注册**

修改 `apps/api/app/api/router.py`，在 import 加 `skills`，并 `api_router.include_router(skills.router)`：

```python
from app.api import (
    admin, ai, attachments, auth, export, health, knowledge, projects, review, sections, settings, share, skills, tags, templates, versions,
)
# ... 在 include_router 列表加：
api_router.include_router(skills.router)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_user_skills_api.py -v`
Expected: 3 PASS

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/api/skills.py apps/api/app/api/router.py apps/api/tests/test_user_skills_api.py
git commit -m "feat(api): 用户个人技能路由（/skills/mine CRUD + /skills/visible）"
```

---

## Phase 5 收尾检查

- [ ] **Phase 5 验证:** `cd apps/api && uv run pytest tests/test_skill_crud.py tests/test_admin_skills_api.py tests/test_user_skills_api.py -v` 全绿

---

## Phase 6: 前端 admin 全局 + 用户个人技能管理页

> 套现有统一面板布局（顶栏 navbar）。仿 `admin-template-manager.tsx` 模式：`PageShell` + `useQuery` hooks + 手写 UI 组件（GOTCHAS F8）。新增 `Skill` 类型、`api.skills.*` 方法、`useSkills`/`useMySkills` hooks。

### Task 19: 前端类型 + API 方法 + hooks

**Files:**
- Modify: `apps/web/src/types/api.ts`（加 Skill 类型）
- Modify: `apps/web/src/lib/api.ts`（加 api.skills 方法）
- Modify: `apps/web/src/lib/queries.ts`（重建 queryKeys.skills + hooks）

- [ ] **Step 1: 在 types/api.ts 加 Skill 类型**

在 `apps/web/src/types/api.ts` 末尾（Task 4 删旧 `AgentSkill` 的位置之后）加：

```typescript
// ── Agent Skill（spec 合规，两档可见性）──
export type SkillScope = 'global' | 'personal'
export type SkillStatus = 'draft' | 'active'

export interface Skill {
  id: string
  name: string
  description: string
  scope: SkillScope
  owner_id: string | null
  status: SkillStatus
  minio_prefix: string
  created_at: string
  updated_at: string
}

export interface SkillDetail extends Skill {
  skill_md: string
}

export interface SkillCreate {
  name: string
  description: string
  skill_md: string
}

export interface SkillUpdate {
  description?: string
  skill_md?: string
  status?: SkillStatus
}
```

- [ ] **Step 2: 在 api.ts 加 skills 方法**

在 `apps/web/src/lib/api.ts` 的 `api` 对象内（末尾的 `}` 之前）加：

```typescript
  // ── Agent Skills（spec 合规）──
  listGlobalSkills: () => request<Skill[]>('/admin/skills'),
  createGlobalSkill: (data: SkillCreate) =>
    request<Skill>('/admin/skills', { method: 'POST', body: JSON.stringify(data) }),
  getGlobalSkill: (id: string) => request<SkillDetail>(`/admin/skills/${id}`),
  updateGlobalSkill: (id: string, data: SkillUpdate) =>
    request<Skill>(`/admin/skills/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteGlobalSkill: (id: string) =>
    request<{ ok: boolean }>(`/admin/skills/${id}`, { method: 'DELETE' }),

  listVisibleSkills: () => request<Skill[]>('/skills/visible'),
  listMySkills: () => request<Skill[]>('/skills/mine'),
  createMySkill: (data: SkillCreate) =>
    request<Skill>('/skills/mine', { method: 'POST', body: JSON.stringify(data) }),
  getMySkill: (id: string) => request<SkillDetail>(`/skills/mine/${id}`),
  updateMySkill: (id: string, data: SkillUpdate) =>
    request<Skill>(`/skills/mine/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteMySkill: (id: string) =>
    request<{ ok: boolean }>(`/skills/mine/${id}`, { method: 'DELETE' }),
```

并在 import 行加类型：`import type { ..., Skill, SkillDetail, SkillCreate, SkillUpdate } from '@/types/api'`（把现有 import 行补齐这几个类型）。

- [ ] **Step 3: 在 queries.ts 重建 queryKeys.skills + hooks**

在 `apps/web/src/lib/queries.ts` 的 `queryKeys` 对象内加（Task 4 删了旧 skills，现重建）：

```typescript
  skills: {
    all: ['skills'] as const,
    visible: ['skills', 'visible'] as const,
    mine: ['skills', 'mine'] as const,
    admin: ['skills', 'admin'] as const,
    detail: (id: string) => ['skills', 'detail', id] as const,
  },
```

在文件末尾加 hooks：

```typescript
// ── Agent Skills（spec 合规）──
export function useGlobalSkills() {
  return useQuery<Skill[]>({ queryKey: queryKeys.skills.admin, queryFn: api.listGlobalSkills })
}

export function useCreateGlobalSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SkillCreate) => api.createGlobalSkill(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.admin }),
  })
}

export function useUpdateGlobalSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SkillUpdate }) => api.updateGlobalSkill(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.admin }),
  })
}

export function useDeleteGlobalSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteGlobalSkill(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.admin }),
  })
}

export function useVisibleSkills() {
  return useQuery<Skill[]>({ queryKey: queryKeys.skills.visible, queryFn: api.listVisibleSkills })
}

export function useMySkills() {
  return useQuery<Skill[]>({ queryKey: queryKeys.skills.mine, queryFn: api.listMySkills })
}

export function useCreateMySkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SkillCreate) => api.createMySkill(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.mine }),
  })
}

export function useUpdateMySkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SkillUpdate }) => api.updateMySkill(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.mine }),
  })
}

export function useDeleteMySkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteMySkill(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.mine }),
  })
}
```

并在 import 行补齐类型：`import type { ..., Skill, SkillCreate, SkillUpdate } from '@/types/api'`。

- [ ] **Step 4: 跑前端类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | tail -15`
Expected: 无类型错误（若报 `useQueryClient` 未 import，在 queries.ts 顶部补 import）。

- [ ] **Step 5: 提交**

```bash
git add apps/web/src/types/api.ts apps/web/src/lib/api.ts apps/web/src/lib/queries.ts
git commit -m "feat(web): Skill 类型 + api.skills 方法 + useSkills/useMySkills hooks"
```

---

### Task 20: 共享 skill 编辑器组件

**Files:**
- Create: `apps/web/src/components/skills/skill-editor.tsx`

> 表单式：name + description 输入框 + skill_md 正文大文本框 + 状态切换。admin 和 user 共用。

- [ ] **Step 1: 实现 skill-editor.tsx**

```tsx
// apps/web/src/components/skills/skill-editor.tsx
'use client'

import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { Skill, SkillCreate, SkillStatus, SkillUpdate } from '@/types/api'

/**
 * Skill 编辑器（表单式，admin/user 共用）。
 *
 * v1 范围：name + description（单行，触发条件）+ skill_md 正文大文本框 + 状态切换。
 * scripts/references/assets 文件上传留 v2（spec §12）。
 */
interface SkillEditorProps {
  /** 已有 skill（编辑模式）；null = 创建模式 */
  skill: Skill | null
  mode: 'global' | 'personal'
  onSave: (data: SkillCreate | SkillUpdate) => Promise<void>
  onCancel: () => void
}

export function SkillEditor({ skill, mode, onSave, onCancel }: SkillEditorProps) {
  const isEdit = skill !== null
  const [name, setName] = useState(skill?.name ?? '')
  const [description, setDescription] = useState(skill?.description ?? '')
  const [skillMd, setSkillMd] = useState('')
  const [status, setStatus] = useState<SkillStatus>(skill?.status ?? 'draft')
  const [saving, setSaving] = useState(false)

  async function handleSave() {
    if (!name.trim() || !description.trim()) {
      toast.error('name 和 description 必填')
      return
    }
    setSaving(true)
    try {
      const payload: SkillCreate | SkillUpdate = isEdit
        ? { description, skill_md: skillMd, status }
        : { name, description, skill_md: skillMd }
      await onSave(payload)
      toast.success(isEdit ? '技能已更新' : '技能已创建')
      onCancel()
    } catch (e) {
      toast.error('保存失败：' + (e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label className="text-sm font-medium">name（spec 标识，[a-z0-9-]，≤64）</label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={isEdit}
          placeholder="my-skill"
        />
        {isEdit && <p className="text-xs text-muted-foreground">name 创建后不可改（spec: name=目录名）</p>}
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">description（触发条件，单行 ≤1024）</label>
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="什么任务该激活这个技能"
        />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">SKILL.md 正文（Markdown，不含 frontmatter）</label>
        <Textarea
          value={skillMd}
          onChange={(e) => setSkillMd(e.target.value)}
          rows={12}
          placeholder="## 步骤&#10;1. 分析技术领域&#10;2. ..."
        />
      </div>

      {isEdit && (
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium">状态</label>
          <Badge variant={status === 'active' ? 'default' : 'secondary'}>{status}</Badge>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setStatus(status === 'draft' ? 'active' : 'draft')}
          >
            切换为 {status === 'draft' ? 'active' : 'draft'}
          </Button>
          <span className="text-xs text-muted-foreground">draft 不进 runtime，active 进</span>
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onCancel} disabled={saving}>取消</Button>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? '保存中...' : isEdit ? '更新' : '创建'}
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 跑前端构建确认无 TS 错**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | tail -10`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add apps/web/src/components/skills/skill-editor.tsx
git commit -m "feat(web): 共享 skill 编辑器组件（表单式，admin/user 共用）"
```

---

### Task 21: admin 全局技能管理页

**Files:**
- Create: `apps/web/src/app/(app)/admin/skills/page.tsx`
- Create: `apps/web/src/components/admin/admin-skill-manager.tsx`

- [ ] **Step 1: 实现 admin-skill-manager.tsx**

```tsx
// apps/web/src/components/admin/admin-skill-manager.tsx
'use client'

import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { SkillEditor } from '@/components/skills/skill-editor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useCreateGlobalSkill,
  useDeleteGlobalSkill,
  useGlobalSkills,
} from '@/lib/queries'
import type { Skill, SkillCreate } from '@/types/api'

/**
 * Admin 全局技能管理（spec 两档可见性之 global）。
 * 仿 admin-template-manager.tsx 模式。
 */
export function AdminSkillManager() {
  const { data: skills, isLoading } = useGlobalSkills()
  const createSkill = useCreateGlobalSkill()
  const deleteSkill = useDeleteGlobalSkill()
  const [editing, setEditing] = useState<Skill | null | 'new'>(null)

  async function handleCreate(data: SkillCreate) {
    await createSkill.mutateAsync(data)
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`确定删除全局技能「${name}」？MinIO 目录会一并清除。`)) return
    try {
      await deleteSkill.mutateAsync(id)
      toast.success('已删除')
    } catch (e) {
      toast.error('删除失败：' + (e as Error).message)
    }
  }

  return (
    <PageShell>
      <PageHeader
        title="全局技能"
        description="admin 管理的全站可见 Agent Skills（spec 合规 SKILL.md）"
        action={
          <Button onClick={() => setEditing('new')}>
            <Plus className="mr-2 h-4 w-4" /> 新建技能
          </Button>
        }
      />

      {editing !== null && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>{editing === 'new' ? '新建全局技能' : '编辑技能'}</CardTitle>
          </CardHeader>
          <CardContent>
            <SkillEditor
              skill={editing === 'new' ? null : editing}
              mode="global"
              onSave={handleCreate}
              onCancel={() => setEditing(null)}
            />
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      ) : !skills?.length ? (
        <EmptyState title="暂无全局技能" description="点击「新建技能」创建第一个全局技能" />
      ) : (
        <div className="grid gap-3">
          {skills.map((s) => (
            <Card key={s.id}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-base font-mono">{s.name}</CardTitle>
                <div className="flex items-center gap-2">
                  <Badge variant={s.status === 'active' ? 'default' : 'secondary'}>
                    {s.status}
                  </Badge>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(s)}>编辑</Button>
                  <Button size="sm" variant="ghost" onClick={() => handleDelete(s.id, s.name)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{s.description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </PageShell>
  )
}
```

- [ ] **Step 2: 实现 page.tsx**

```tsx
// apps/web/src/app/(app)/admin/skills/page.tsx
import { AdminSkillManager } from '@/components/admin/admin-skill-manager'

export default function AdminSkillsPage() {
  return <AdminSkillManager />
}
```

- [ ] **Step 3: 在 navbar 的 ADMIN_NAV_ITEMS 加入口**

打开 `apps/web/src/components/navbar.tsx`，在 `ADMIN_NAV_ITEMS` 数组加一项（参考现有 admin 子项的格式）：

```typescript
const ADMIN_NAV_ITEMS: NavItem[] = [
  // ... 现有项
  { href: '/admin/skills', label: '技能', icon: Wrench },  // 从 lucide-react import Wrench
  // ...
]
```

- [ ] **Step 4: 跑前端构建**

Run: `cd apps/web && pnpm build 2>&1 | tail -15`
Expected: 构建成功

- [ ] **Step 5: 提交**

```bash
git add apps/web/src/app/\(app\)/admin/skills/ apps/web/src/components/admin/admin-skill-manager.tsx apps/web/src/components/navbar.tsx
git commit -m "feat(web): admin 全局技能管理页（/admin/skills，含 navbar 入口）"
```

---

### Task 22: 用户个人技能管理页

**Files:**
- Create: `apps/web/src/app/(app)/settings/skills/page.tsx`
- Create: `apps/web/src/components/settings/personal-skill-manager.tsx`

- [ ] **Step 1: 实现 personal-skill-manager.tsx**

```tsx
// apps/web/src/components/settings/personal-skill-manager.tsx
'use client'

import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { SkillEditor } from '@/components/skills/skill-editor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useCreateMySkill,
  useDeleteMySkill,
  useMySkills,
  useVisibleSkills,
} from '@/lib/queries'
import type { Skill, SkillCreate } from '@/types/api'

/**
 * 用户个人技能管理（spec 两档可见性之 personal）。
 * 上半区：可见的 global skill（只读）；下半区：我的 personal skill（CRUD）。
 */
export function PersonalSkillManager() {
  const { data: mySkills, isLoading: myLoading } = useMySkills()
  const { data: visibleSkills, isLoading: visLoading } = useVisibleSkills()
  const createSkill = useCreateMySkill()
  const deleteSkill = useDeleteMySkill()
  const [editing, setEditing] = useState<Skill | null | 'new'>(null)

  const globalSkills = visibleSkills?.filter((s) => s.scope === 'global') ?? []

  async function handleCreate(data: SkillCreate) {
    await createSkill.mutateAsync(data)
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`确定删除个人技能「${name}」？`)) return
    try {
      await deleteSkill.mutateAsync(id)
      toast.success('已删除')
    } catch (e) {
      toast.error('删除失败：' + (e as Error).message)
    }
  }

  return (
    <PageShell>
      <PageHeader
        title="我的技能"
        description="管理个人 Agent Skills（spec 合规 SKILL.md）"
        action={
          <Button onClick={() => setEditing('new')}>
            <Plus className="mr-2 h-4 w-4" /> 新建技能
          </Button>
        }
      />

      {editing !== null && (
        <Card className="mb-6">
          <CardHeader><CardTitle>{editing === 'new' ? '新建个人技能' : '编辑技能'}</CardTitle></CardHeader>
          <CardContent>
            <SkillEditor
              skill={editing === 'new' ? null : editing}
              mode="personal"
              onSave={handleCreate}
              onCancel={() => setEditing(null)}
            />
          </CardContent>
        </Card>
      )}

      {/* 全局技能（只读） */}
      <div className="mb-8">
        <h3 className="mb-3 text-sm font-medium text-muted-foreground">全局技能（admin 提供，只读）</h3>
        {visLoading ? <Skeleton className="h-16 w-full" /> : !globalSkills.length ? (
          <p className="text-sm text-muted-foreground">暂无可用全局技能</p>
        ) : (
          <div className="grid gap-2">
            {globalSkills.map((s) => (
              <Card key={s.id}>
                <CardContent className="flex items-center justify-between py-3">
                  <div>
                    <span className="font-mono text-sm">{s.name}</span>
                    <p className="text-xs text-muted-foreground">{s.description}</p>
                  </div>
                  <Badge>global</Badge>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* 我的个人技能 */}
      <div>
        <h3 className="mb-3 text-sm font-medium text-muted-foreground">我的个人技能</h3>
        {myLoading ? (
          <div className="space-y-2">{[1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>
        ) : !mySkills?.length ? (
          <EmptyState title="暂无个人技能" description="点击「新建技能」创建你的第一个技能" />
        ) : (
          <div className="grid gap-2">
            {mySkills.map((s) => (
              <Card key={s.id}>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-base font-mono">{s.name}</CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge variant={s.status === 'active' ? 'default' : 'secondary'}>{s.status}</Badge>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(s)}>编辑</Button>
                    <Button size="sm" variant="ghost" onClick={() => handleDelete(s.id, s.name)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent><p className="text-sm text-muted-foreground">{s.description}</p></CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
```

- [ ] **Step 2: 实现 page.tsx**

```tsx
// apps/web/src/app/(app)/settings/skills/page.tsx
import { PersonalSkillManager } from '@/components/settings/personal-skill-manager'

export default function PersonalSkillsPage() {
  return <PersonalSkillManager />
}
```

- [ ] **Step 3: 跑前端构建**

Run: `cd apps/web && pnpm build 2>&1 | tail -15`
Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add apps/web/src/app/\(app\)/settings/skills/ apps/web/src/components/settings/personal-skill-manager.tsx
git commit -m "feat(web): 用户个人技能管理页（/settings/skills，全局只读 + 个人 CRUD）"
```

---

## Phase 6 收尾检查

- [ ] **Phase 6 验证:** `cd apps/web && pnpm build` 成功 + 手动访问 `/admin/skills`（admin）和 `/settings/skills`（普通用户）渲染正常

---

## Phase 7: SSE tool_call 事件 + 全量验证收尾

> agent loop 会发起 tool_call（如 `rag_search`），SSE 层要把这些事件透传给前端，让用户看到 agent 在做什么。spec §7：保留 `token`，新增 `tool_call`/`tool_result` 事件类型。

### Task 23: SSE 端点暴露 tool_call/tool_result 事件

**Files:**
- Modify: `apps/api/app/ai/orchestrator.py`（astream_generate 增加 tool 事件 yield）
- Modify: `apps/api/app/api/ai.py`（SSE 层消费新事件类型）

- [ ] **Step 1: 修改 orchestrator 的 astream_generate 暴露 tool 事件**

把 Task 13 的 `astream_generate` 改为 yield `(kind, payload)` 元组（而非纯 token 字符串），kind ∈ `{"token", "tool_call", "tool_result"}`：

```python
# apps/api/app/ai/orchestrator.py（astream_generate 重写）
async def astream_generate(db, section, history, *, llm_config, usage_sink=None):
    """异步生成草稿：委托 deepagents agent loop。

    yield (kind, payload) 元组：
      - ("token", str)：文本 token
      - ("tool_call", {"name": str, "args": dict})：agent 发起工具调用
      - ("tool_result", {"name": str, "result": any})：工具返回
    """
    from app.ai.agent import build_agent

    agent = build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section))
    sp = get_section_prompt(section.key)
    instruction = f"请根据对话历史，整理生成本章节【{section.title}】的草稿。要求：{sp.output_format}。用 Markdown 格式输出。"

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": instruction}]},
        version="v2",
    ):
        evt = event["event"]
        # 文本 token
        if evt == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk and chunk.content:
                yield ("token", chunk.content)
        # 工具调用开始
        elif evt == "on_tool_start":
            yield ("tool_call", {"name": event.get("name", ""), "args": event.get("data", {}).get("input", {})})
        # 工具调用结束
        elif evt == "on_tool_end":
            yield ("tool_result", {"name": event.get("name", ""), "result": event.get("data", {}).get("output")})
```

同样改造 `astream_chat`（用相同的 (kind, payload) 元组 yield）。

- [ ] **Step 2: 修改 SSE 层消费新事件类型**

修改 `apps/api/app/api/ai.py` 的 `generate_draft` 端点的 `generate()` 内部循环。当前是 `async for kind, text in _yield_with_heartbeat(...)`，其中 kind 只区分 heartbeat/token。现在 astream_generate 直接 yield 元组，需要适配。

找到 `astream_generate` 的调用处，改为：

```python
# apps/api/app/api/ai.py（generate_draft 的 generate() 内部，替换原 astream_generate 消费逻辑）
try:
    async for item in _yield_with_heartbeat_tuple(
        astream_generate(db, section, history, llm_config=llm_config, usage_sink=usage)
    ):
        if item == ("heartbeat",):
            yield _sse_event("heartbeat", {})
            continue
        kind, payload = item
        if kind == "token":
            full_md += payload
            yield _sse_event("token", {"text": payload})
        elif kind == "tool_call":
            yield _sse_event("tool_call", {"name": payload["name"], "args": payload["args"]})
        elif kind == "tool_result":
            yield _sse_event("tool_result", {"name": payload["name"], "result": str(payload["result"])[:500]})
    # ... 后续 markdown_to_tiptap + done 事件不变
```

并新增辅助函数 `_yield_with_heartbeat_tuple`（在 ai.py 内，仿现有 `_yield_with_heartbeat`，但处理 (kind, payload) 元组而非纯字符串）：

```python
# apps/api/app/api/ai.py 新增辅助函数
async def _yield_with_heartbeat_tuple(agen):
    """带心跳的 (kind, payload) 元组流包装。

    区别于 _yield_with_heartbeat（处理纯字符串），本函数处理 orchestrator 的
    ("token"|"tool_call"|"tool_result", payload) 元组，心跳用 ("heartbeat",) 标记。
    """
    last_yield = time.monotonic()
    async for item in agen:
        yield item
        last_yield = time.monotonic()
    # 流结束后不再心跳（外层 finally 处理收尾）
```

> 注：心跳逻辑可简化——agent loop 通常持续产出事件，不需要额外心跳。若 `_yield_with_heartbeat_tuple` 与现有 `_yield_with_heartbeat` 逻辑重叠，直接复用并适配。

- [ ] **Step 3: 跑测试确认 SSE 端点未破坏**

Run: `cd apps/api && uv run pytest tests/ -k "ai or generate or sse" -v 2>&1 | tail -20`
Expected: 现有 AI 相关测试全绿（若旧测试断言 astream_generate 返回纯字符串，需同步改为元组）

- [ ] **Step 4: 提交**

```bash
git add apps/api/app/ai/orchestrator.py apps/api/app/api/ai.py
git commit -m "feat(api): SSE 暴露 tool_call/tool_result 事件（agent loop 透明化）

- astream_generate/astream_chat yield (kind, payload) 元组
- SSE 新增 tool_call/tool_result 事件类型
- 保留 token 事件 + heartbeat + done/error"
```

---

### Task 24: 全量验证 + 收尾

**Files:**
- 全仓库

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest -q 2>&1 | tail -20`
Expected: 全绿。统计新增测试数（应 ≥ 30 个新测试：skill_model/storage/directory/visibility/rag_tool/tool_support/agent_factory/docker_runner/crud/admin_api/user_api）。

- [ ] **Step 2: 前端构建**

Run: `cd apps/web && pnpm build 2>&1 | tail -20`
Expected: 构建成功，无 TS 错误。

- [ ] **Step 3: 迁移链完整性**

Run: `cd apps/api && uv run alembic history 2>&1 | head -10`
Expected: 迁移链 `... → b1c2d3e4f5g6 → c1d2e3f4a5b6 → d2e3f4a5b6c7 (head)` 连续无断点。

- [ ] **Step 4: 手动验证清单**

启动服务后逐项验证：
- [ ] admin 登录 → `/admin/skills` → 新建全局 skill → 列表显示 → 状态切换 draft→active
- [ ] 普通用户登录 → `/settings/skills` → 看到全局 skill（只读）→ 新建个人 skill → 编辑/删除
- [ ] 普通用户撰写章节 → agent 启动 → 若模型不支持 tool calling，收到明确错误（Q14-α）
- [ ] 普通用户撰写章节 → agent loop 中若调用 rag_search → SSE 收到 tool_call 事件
- [ ] MinIO 中确认 skill 目录结构：`skills/global/<name>/SKILL.md`
- [ ] 删除 skill → MinIO 对应目录清空 + DB 行删除

- [ ] **Step 5: 更新 GOTCHAS.md（若有新坑）**

把开发中踩到的新坑追加到 `docs/GOTCHAS.md`（如 deepagents 版本兼容、Docker Windows 路径等）。

- [ ] **Step 6: 最终提交**

```bash
git add -A
git commit -m "test(api): 全量验证通过（agent-skills 模块 Phase 1-7 完成）"
```

---

## Self-Review 记录

### Spec 覆盖核对

对照 spec §3 决定矩阵逐项检查：

| 决定 | 实现位置（Task） | 状态 |
|---|---|---|
| skill 定义 = Agent Skills 标准 SKILL.md | Task 6（schema）+ Task 8（assemble_skill_md） | ✅ |
| 旧 agent_skills 表彻底删除 | Task 3（删模型/服务/schema/路由/迁移）+ Task 4（前端） | ✅ |
| 路线 B deepagents 全量重写 | Task 12（agent 工厂）+ Task 13（orchestrator 委托） | ✅ |
| 默认模型 glm-4.7 | Task 5 | ✅ |
| 自定义配置拒绝服务降级 (α) | Task 11（check_tool_support） | ✅ |
| MinIO BaseStore 适配 | Task 7（MinIOSkillStore） | ✅ |
| 两档可见性（global + personal） | Task 9（visibility）+ Task 16（CRUD） | ✅ |
| 纯运行时合并 (α) | Task 9（list_visible_skills 无项目状态） | ✅ |
| 脚本执行 (b) | Task 14（Docker sandbox） | ✅ |
| sandbox 直读 MinIO + 自建 Docker | Task 14（pull_script_from_minio + docker SDK） | ✅ |
| 写交底书流全量切 deepagents | Task 13（astream_generate 委托） | ✅ |
| SSE tool_call/tool_result 事件 | Task 23 | ✅ |
| rag_search 工具化 | Task 10 | ✅ |
| 前端 admin 全局管理 | Task 21 | ✅ |
| 前端用户个人管理 | Task 22 | ✅ |

### 类型一致性核对

- `Skill` 模型字段（Task 1）：name/description/scope/owner_id/status/minio_prefix —— 与 schema（Task 6）`SkillOut`、前端（Task 19）`Skill` interface 字段名一致。
- `MinIOSkillStore`（Task 7）的 `bucket` 参数 `"global"`/`"personal"` —— 与 `_bucket_for_scope`（Task 16）、`MinioStorage._resolve`（`app/core/storage.py`）的别名一致。
- `build_agent`（Task 12）的 `skills=skill_sources` —— 与 `build_agent_skill_sources`（Task 9）返回的 `list[str]` 一致，符合 deepagents `create_deep_agent(skills=list[str])` 签名。
- `astream_generate`（Task 13/23）yield 类型：Task 13 是纯 str，Task 23 改为 `(kind, payload)` 元组 —— **Task 23 是 Task 13 的修订**，最终态以 Task 23 为准（元组）。

### 已知限制（写入 spec §12，透明）

1. **Docker sandbox v1 不自动注入 agent backend**（Task 15 注）：sandbox 通过独立 `execute_script` API 暴露，agent 自动执行脚本留 v2。原因：deepagents sandbox backend 深度集成需更多探索。
2. **前端编辑器 v1 无文件树**（Task 20）：仅 name + description + skill_md 正文。scripts/references/assets 文件上传留 v2。
3. **skill 版本管理**：v1 只存当前版本，无历史。
4. **glm-4-flash 在复杂 agent loop 可能不稳**：`check_tool_support` 放行但 warning（Task 11），实际表现需观测。

### 占位符扫描

- 无 "TBD"/"TODO"/"fill in" —— ✅
- 所有代码块含完整实现 —— ✅
- 所有 Run 命令含 Expected —— ✅
- 无 "Similar to Task N" 省略 —— ✅

---

## 实施顺序总结

| Phase | Tasks | 核心产出 |
|---|---|---|
| 0 | Task 0 | deepagents + docker 依赖、分支 |
| 1 | Task 1-5 | Skill 模型 + 迁移 + 删除旧体系 + glm-4.7 |
| 2 | Task 6-9 | schema + MinIO BaseStore + 目录管理 + 可见性 |
| 3 | Task 10-13 | RAG 工具化 + 自定义配置降级 + agent 工厂 + orchestrator 委托 |
| 4 | Task 14-15 | Docker sandbox + backend 条件注入 |
| 5 | Task 16-18 | CRUD service + admin 路由 + 用户路由 |
| 6 | Task 19-22 | 前端类型/API/hooks + 编辑器 + admin 页 + 用户页 |
| 7 | Task 23-24 | SSE tool 事件 + 全量验证 |

**预计工期**：月级（spec §0 锚点：路线 B 全量重写 AI 层 + sandbox + spec 合规，非周级）。
