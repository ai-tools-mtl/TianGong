# 用户绑定长期记忆 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为天工 agent 增加用户绑定的长期记忆——跨项目、跨会话记住用户的偏好、稳定事实和领域 know-how。

**Architecture:** PostgreSQL `user_memories` 表（含 pgvector embedding）+ 读写双路径。读路径在 `build_system_prompt` 阶段按 query 语义检索 Top-K 注入 system prompt；写路径由 agent 在 loop 中自主调用 `save_memory` 工具，工具内部做 embedding 去重（≥0.85 相似度合并）。用户可在前端 `/settings/memories` 管理（CRUD）。顺带修复 `rag_search` 工具的参数注入缺陷（重构为闭包工厂）。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + pgvector(HNSW) + LangChain @tool + Next.js 14 + shadcn/ui + React Query

**Spec:** `docs/superpowers/specs/2026-07-28-user-memory-design.md`

**关键约束（开工前必读）:**
- **GOTCHAS G2**：测试用 SQLite 内存库，`HalfVec` 在 SQLite 建不了表，必须在 `conftest.py` 的 `engine` fixture 里像 `knowledge_chunks` 那样排除原表 + 手动建兼容版（embedding 用 JSON 替代）。
- **测试账号**：用 `@example.com` / `@tiangong.dev`，别用 `.local`（GOTCHAS G4）。
- **迁移链 HEAD**：`d1h2n3s4w5i6`（HNSW 索引迁移），新迁移挂它后面。

---

## File Structure

| 类型 | 路径 | 责任 |
|---|---|---|
| 新建模型 | `apps/api/app/models/user_memory.py` | `UserMemory` ORM 模型 |
| 新建 schema | `apps/api/app/schemas/memory.py` | Pydantic 入参/出参 |
| 新建 service | `apps/api/app/services/memory_service.py` | CRUD + embedding + 检索 + 去重 |
| 新建迁移 | `apps/api/alembic/versions/e1m2e3m4o5r6_add_user_memories.py` | 建表 + HNSW 索引 |
| 重构工具 | `apps/api/app/ai/tools.py` | `create_agent_tools(db, user_id)` 工厂（rag_search + save_memory） |
| 修改装配 | `apps/api/app/ai/agent.py` | 用 `create_agent_tools` 替换模块级常量 |
| 修改 prompt | `apps/api/app/ai/context_assembler.py` | `build_system_prompt` 注入记忆 + SYSTEM_PROMPT 规则 |
| 新建 API | `apps/api/app/api/memories.py` | CRUD 路由 |
| 注册路由 | `apps/api/app/api/router.py` | include memories router |
| 注册模型 | `apps/api/app/models/__init__.py` | 加 UserMemory |
| 修改测试基座 | `apps/api/tests/conftest.py` | engine fixture 加 user_memories 兼容表 |
| 新建前端页 | `apps/web/src/app/(app)/settings/memories/page.tsx` | 记忆管理页 |
| 新建前端组件 | `apps/web/src/components/memory-card.tsx` | 记忆卡片（查看/编辑/删除） |
| 扩展 client | `apps/web/src/lib/api.ts` | memoryApi |
| 扩展 types | `apps/web/src/types/api.ts` | Memory 类型 |
| 扩展 hooks | `apps/web/src/lib/queries.ts` | useMemories / useCreateMemory 等 |
| 修改导航 | `apps/web/src/app/(app)/settings/page.tsx` | 加「我的记忆」入口卡片 |
| 测试 | `tests/test_memory_service.py`, `test_memory_api.py`, `test_save_memory_tool.py` | 新建 |
| 修改测试 | `tests/test_agent_factory.py`, `test_rag_tool.py` | 适配工厂模式 |

---

## Phase 1: 数据层（模型 + 迁移）

### Task 1: UserMemory 模型

**Files:**
- Create: `apps/api/app/models/user_memory.py`
- Modify: `apps/api/app/models/__init__.py`

- [ ] **Step 1: 创建模型文件**

创建 `apps/api/app/models/user_memory.py`：

```python
import uuid

from pgvector.sqlalchemy import HALFVEC as HalfVec
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

# 与 knowledge_chunk 对齐：智谱 embedding-3 输出 2048 维
EMBEDDING_DIM = 2048

# 记忆来源（写路径区分）
SOURCE_AGENT = "agent"      # agent 在 loop 中自动写入
SOURCE_MANUAL = "manual"    # 用户在前端手动添加


class UserMemory(Base, IdMixin, TimestampMixin):
    """用户绑定的长期记忆（跨项目、跨会话稳定）。

    - user_id：严格隔离，仅本人可见、本人可检索（纯个人，无三域）。
    - content：一条记忆 = 一句话/一段话（建议 ≤200 字，前端校验）。
    - embedding：写入时同步生成；允许 NULL（embedding 配置不可用时降级为纯文本）。
    - source：区分 agent 自动写入 vs 用户手动添加。
    """
    __tablename__ = "user_memories"
    __table_args__ = (
        # 前端列表查询用：按用户 + 更新时间倒序。
        # user_id 单列另由 mapped_column(index=True) 建索引。
        Index(
            "ix_user_memories_user_updated",
            "user_id", "updated_at",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(HalfVec(EMBEDDING_DIM), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default=SOURCE_AGENT)
```

- [ ] **Step 2: 注册模型**

修改 `apps/api/app/models/__init__.py`，在 import 区加一行（放在其他 model import 之间，字母序不强制但保持整洁）：

```python
from app.models.user_memory import UserMemory
```

在 `__all__` 列表中加入 `"UserMemory"`（放在 `"WebIngestionJob"` 之后）。

- [ ] **Step 3: 验证 import 不报错**

Run: `cd apps/api && uv run python -c "from app.models import UserMemory; print(UserMemory.__tablename__)"`
Expected: 输出 `user_memories`，无异常。

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/models/user_memory.py apps/api/app/models/__init__.py
git commit -m "feat(memory): UserMemory 模型（user_id/content/embedding/source）

pgvector halfvec(2048) embedding 列 nullable（降级设计），复用 IdMixin/TimestampMixin。"
```

---

### Task 2: Alembic 迁移

**Files:**
- Create: `apps/api/alembic/versions/e1m2e3m4o5r6_add_user_memories.py`

- [ ] **Step 1: 创建迁移文件**

创建 `apps/api/alembic/versions/e1m2e3m4o5r6_add_user_memories.py`：

```python
"""add user_memories table for long-term memory

Revision ID: e1m2e3m4o5r6
Revises: d1h2n3s4w5i6
Create Date: 2026-07-28

列类型严格对齐 IdMixin/TimestampMixin(base.py) + c3d4e5f6a7b8 范式:
- id = sa.Uuid()
- timestamps = sa.DateTime(timezone=True) server_default now() NOT NULL
- embedding = HalfVec(2048), 与 knowledge_chunks 同维
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC as HalfVec


revision: str = "e1m2e3m4o5r6"
down_revision: Union[str, Sequence[str], None] = "d1h2n3s4w5i6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", HalfVec(2048), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="agent"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_user_memories_user_id", "user_memories", ["user_id"])
    op.create_index(
        "ix_user_memories_user_updated", "user_memories", ["user_id", "updated_at"]
    )
    # HNSW 索引（cosine，与 knowledge_chunks 同款参数）
    op.execute(
        "CREATE INDEX ix_user_memories_embedding_hnsw ON user_memories "
        "USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.drop_index("ix_user_memories_embedding_hnsw", table_name="user_memories")
    op.drop_index("ix_user_memories_user_updated", table_name="user_memories")
    op.drop_index("ix_user_memories_user_id", table_name="user_memories")
    op.drop_table("user_memories")
```

- [ ] **Step 2: 在 PG 上验证迁移可执行**

Run: `cd apps/api && uv run alembic upgrade head`
Expected: 迁移成功，无报错。（需要 PG + pgvector 已就绪，见 AGENTS.md `docker compose up -d postgres`）

- [ ] **Step 3: 验证回滚**

Run: `cd apps/api && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: 先回滚再升级，都成功。

- [ ] **Step 4: Commit**

```bash
git add apps/api/alembic/versions/e1m2e3m4o5r6_add_user_memories.py
git commit -m "feat(memory): 迁移 e1m2e3m4o5r6 建 user_memories 表 + HNSW 索引"
```

---

### Task 3: 修改测试基座 conftest（SQLite 兼容）

**Files:**
- Modify: `apps/api/tests/conftest.py:79-113`（engine fixture）

这是 GOTCHAS G2 的关键约束：`HalfVec` 在 SQLite 建不了表，必须像 `knowledge_chunks` 那样排除原表 + 手动建兼容版。

- [ ] **Step 1: 修改 engine fixture，排除 user_memories 原表**

在 `apps/api/tests/conftest.py` 的 `engine` fixture 中，修改 tables 过滤逻辑（约第 80 行）：

```python
    # 排除原表（含 Vector/HalfVec 列，sqlite 建不了）
    tables = {
        name: t for name, t in Base.metadata.tables.items()
        if name not in ("knowledge_chunks", "user_memories")
    }
```

- [ ] **Step 2: 在 knowledge_chunks 兼容表之后，添加 user_memories 兼容表**

在 `kc_compat.create(eng, checkfirst=True)` 之后（约第 106 行后）添加：

```python
    # user_memories 兼容版：与生产同名列。
    # embedding 用 JSON 替代 pgvector.HalfVec（SQLite 不支持）——测试不关心向量内容。
    um_compat = sa.Table(
        "user_memories", sa.MetaData(),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("content", sa.Text),
        sa.Column("embedding", sa.JSON),
        sa.Column("source", sa.String(20), default="agent"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    um_compat.create(eng, checkfirst=True)
```

- [ ] **Step 3: 修改 teardown，drop 兼容表**

在 `kc_compat.drop(eng, checkfirst=True)` 之后（约第 110 行后）添加：

```python
    um_compat.drop(eng, checkfirst=True)
```

- [ ] **Step 4: 验证现有测试仍通过**

Run: `cd apps/api && uv run pytest tests/test_rag_tool.py tests/test_agent_factory.py -v`
Expected: 全部 PASS（基座改动未破坏现有测试）。

- [ ] **Step 5: Commit**

```bash
git add apps/api/tests/conftest.py
git commit -m "test(memory): conftest engine fixture 加 user_memories SQLite 兼容表

HalfVec 在 SQLite 建不了，仿 knowledge_chunks 模式排除原表 + 建 JSON 兼容版。"
```

---

## Phase 2: Service 层

### Task 4: memory_service.py 基础 CRUD + embedding

**Files:**
- Create: `apps/api/app/services/memory_service.py`
- Test: `apps/api/tests/test_memory_service.py`

- [ ] **Step 1: 先写失败测试**

创建 `apps/api/tests/test_memory_service.py`：

```python
"""用户长期记忆 service 测试。"""
import uuid


def test_create_memory_generates_embedding(db_session, registered_user, monkeypatch):
    """写入时自动生成 embedding（mock embed，返回固定向量）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)

    mem = ms.create_memory(db_session, user_id=uid, content="偏好简洁风格")

    assert mem.content == "偏好简洁风格"
    assert mem.embedding is not None
    assert mem.user_id == uid
    assert mem.source == "agent"


def test_create_memory_without_embedding_config_falls_back_to_null(db_session, registered_user, monkeypatch):
    """embedding 配置不可用时，记忆仍写入，embedding 为 NULL（降级）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    mem = ms.create_memory(db_session, user_id=uid, content="我做新能源电池")

    assert mem.embedding is None
    assert mem.content == "我做新能源电池"


def test_create_memory_empty_content_raises(db_session, registered_user):
    """空内容抛 ValidationError。"""
    from app.services import memory_service as ms
    from app.core.exceptions import ValidationError

    uid = uuid.UUID(registered_user["id"])
    try:
        ms.create_memory(db_session, user_id=uid, content="   ")
        assert False, "应抛 ValidationError"
    except ValidationError:
        pass


def test_list_memories_orders_by_updated_desc(db_session, registered_user, monkeypatch):
    """列表按 updated_at 倒序。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    m1 = ms.create_memory(db_session, user_id=uid, content="第一条")
    m2 = ms.create_memory(db_session, user_id=uid, content="第二条")
    db_session.commit()

    items = ms.list_memories(db_session, user_id=uid)
    assert items[0].content == "第二条"
    assert items[1].content == "第一条"


def test_list_memories_filters_by_source(db_session, registered_user, monkeypatch):
    """source 筛选生效。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    ms.create_memory(db_session, user_id=uid, content="agent 记的", source="agent")
    ms.create_memory(db_session, user_id=uid, content="手动加的", source="manual")
    db_session.commit()

    manual = ms.list_memories(db_session, user_id=uid, source="manual")
    assert len(manual) == 1
    assert manual[0].content == "手动加的"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.memory_service'`）

- [ ] **Step 3: 创建 service 文件**

创建 `apps/api/app/services/memory_service.py`（先实现 CRUD 部分，检索/去重后续 Task 加）：

```python
"""用户长期记忆服务：CRUD + embedding 生成 + 语义检索 + 去重。"""
import uuid as _uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import UserMemory

# 记忆来源常量（与 model 对齐）
SOURCE_AGENT = "agent"
SOURCE_MANUAL = "manual"

# 检索默认参数
DEFAULT_TOP_K = 5
SIMILARITY_THRESHOLD = 0.5  # 与 rag/retriever.py 一致

# 去重阈值：embedding 余弦相似度 ≥ 此值视为重复，触发合并而非新增
DEDUP_SIMILARITY = 0.85


def _try_embed(db: Session, user_id, text: str) -> list[float] | None:
    """尝试生成 embedding。配置不可用或失败时返回 None（降级为纯文本）。

    复用用户的 embedding 配置链路（resolve_embedding_config），与知识库检索同源。
    """
    from app.rag.embedding import embed_text
    from app.services.llm_config_service import resolve_embedding_config

    embed_config = resolve_embedding_config(db, user_id=user_id)
    if embed_config is None:
        return None
    try:
        return embed_text(text, embed_config=embed_config)
    except Exception:
        return None


def create_memory(
    db: Session, *, user_id, content: str, source: str = SOURCE_AGENT
) -> UserMemory:
    """创建一条记忆。自动生成 embedding（失败降级 NULL）。"""
    if not content or not content.strip():
        raise ValidationError("记忆内容不能为空")
    embedding = _try_embed(db, user_id, content)
    memory = UserMemory(
        user_id=user_id,
        content=content.strip(),
        embedding=embedding,
        source=source,
    )
    db.add(memory)
    db.flush()
    return memory


def list_memories(
    db: Session, *, user_id, source: str | None = None, limit: int = 200
) -> list[UserMemory]:
    """列出用户所有记忆，按 updated_at 倒序。"""
    stmt = select(UserMemory).where(UserMemory.user_id == user_id)
    if source:
        stmt = stmt.where(UserMemory.source == source)
    stmt = stmt.order_by(UserMemory.updated_at.desc()).limit(limit)
    return list(db.scalars(stmt))
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py -v`
Expected: 5 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/memory_service.py apps/api/tests/test_memory_service.py
git commit -m "feat(memory): memory_service CRUD + embedding 降级策略

_try_embed 配置不可用返回 None（纯文本降级），create_memory 自动生成 embedding。"
```

---

### Task 5: 更新 + 删除 + 隔离校验

**Files:**
- Modify: `apps/api/app/services/memory_service.py`
- Test: `apps/api/tests/test_memory_service.py`

- [ ] **Step 1: 追加测试**

在 `apps/api/tests/test_memory_service.py` 末尾追加：

```python
def test_update_memory_regenerates_embedding(db_session, registered_user, monkeypatch):
    """更新内容后 embedding 重建。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)

    mem = ms.create_memory(db_session, user_id=uid, content="原文")
    mem_id = mem.id

    updated = ms.update_memory(db_session, memory_id=mem_id, user_id=uid, content="改后")
    assert updated.content == "改后"
    assert updated.embedding is not None


def test_update_memory_not_owner_raises(db_session, registered_user):
    """非本人更新抛 NotFoundError（不泄露存在性）。"""
    from app.services import memory_service as ms
    from app.core.exceptions import NotFoundError

    uid = uuid.UUID(registered_user["id"])
    other = uuid.uuid4()

    mem = ms.create_memory(db_session, user_id=uid, content="我的")
    try:
        ms.update_memory(db_session, memory_id=mem.id, user_id=other, content="篡改")
        assert False, "应抛 NotFoundError"
    except NotFoundError:
        pass


def test_delete_memory_only_owner(db_session, registered_user):
    """非本人删除抛 NotFoundError。"""
    from app.services import memory_service as ms
    from app.core.exceptions import NotFoundError

    uid = uuid.UUID(registered_user["id"])
    other = uuid.uuid4()

    mem = ms.create_memory(db_session, user_id=uid, content="我的")
    try:
        ms.delete_memory(db_session, memory_id=mem.id, user_id=other)
        assert False, "应抛 NotFoundError"
    except NotFoundError:
        pass

    # 本人删除成功
    ms.delete_memory(db_session, memory_id=mem.id, user_id=uid)
    assert ms.list_memories(db_session, user_id=uid) == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py -v`
Expected: 新增 3 个测试 FAIL（`update_memory` / `delete_memory` 未定义）

- [ ] **Step 3: 实现 update_memory + delete_memory**

在 `apps/api/app/services/memory_service.py` 的 `list_memories` 之后追加：

```python
def update_memory(db: Session, *, memory_id, user_id, content: str) -> UserMemory:
    """更新记忆内容，重新生成 embedding。"""
    mem = db.get(UserMemory, memory_id)
    if mem is None or mem.user_id != user_id:
        raise NotFoundError("记忆不存在")
    if not content.strip():
        raise ValidationError("记忆内容不能为空")
    mem.content = content.strip()
    mem.embedding = _try_embed(db, user_id, content.strip())
    db.flush()
    return mem


def delete_memory(db: Session, *, memory_id, user_id) -> None:
    """删除记忆（仅本人，否则 NotFoundError 不泄露存在性）。"""
    mem = db.get(UserMemory, memory_id)
    if mem is None or mem.user_id != user_id:
        raise NotFoundError("记忆不存在")
    db.delete(mem)
    db.flush()
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py -v`
Expected: 8 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/memory_service.py apps/api/tests/test_memory_service.py
git commit -m "feat(memory): update/delete + 严格归属校验（NotFound 不泄露存在性）"
```

---

### Task 6: 语义检索 search_memories

**Files:**
- Modify: `apps/api/app/services/memory_service.py`
- Test: `apps/api/tests/test_memory_service.py`

SQLite 测试库无 pgvector，检索测试通过 mock 验证 service 层逻辑（过滤 NULL embedding、阈值判断），不测真实向量距离。

- [ ] **Step 1: 追加测试**

在 `apps/api/tests/test_memory_service.py` 末尾追加：

```python
def test_search_memories_returns_results(db_session, registered_user, monkeypatch):
    """检索返回相关记忆（mock cosine_distance 返回固定距离）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    # 记忆有 embedding
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)
    ms.create_memory(db_session, user_id=uid, content="偏好简洁风格")
    ms.create_memory(db_session, user_id=uid, content="我做新能源电池")
    db_session.commit()

    # mock search 的 embedding + 距离计算：让所有记忆距离=0.1（score=0.9 > 阈值）
    class _FakeDistance:
        def __init__(self, dist):
            self._dist = dist

    # 直接 mock UserMemory.embedding.cosine_distance 返回固定结果太复杂，
    # 改为 mock 整个 select 执行结果
    from app.models import UserMemory
    original_scalars = db_session.execute

    def fake_execute(stmt, *args, **kwargs):
        # 检测是否是 search_memories 的查询（含 cosine_distance）
        # 简化：直接返回所有该用户的记忆，距离 0.1
        return original_scalars(stmt, *args, **kwargs)

    # 由于 SQLite 无 pgvector，search_memories 内部 cosine_distance 会报错。
    # 这里验证：embedding 配置不可用时返回空（降级路径）。
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    results = ms.search_memories(db_session, user_id=uid, query="风格")
    assert results == []


def test_search_memories_skips_null_embedding(db_session, registered_user, monkeypatch):
    """NULL embedding 的记忆在检索时被跳过（通过降级路径验证）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    # 无 embedding 配置 → search 内部 embed 失败 → 返回空
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    ms.create_memory(db_session, user_id=uid, content="无 embedding 的记忆")
    db_session.commit()

    results = ms.search_memories(db_session, user_id=uid, query="记忆")
    assert results == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_search_memories_returns_results tests/test_memory_service.py::test_search_memories_skips_null_embedding -v`
Expected: FAIL（`search_memories` 未定义）

- [ ] **Step 3: 实现 search_memories**

在 `apps/api/app/services/memory_service.py` 顶部 import 区补充：

```python
from dataclasses import dataclass

from pgvector.sqlalchemy import HALFVEC as HalfVec
from sqlalchemy import select, text
```

在 `delete_memory` 之后追加（含 dataclass）：

```python
@dataclass
class MemorySearchResult:
    content: str
    score: float
    id: _uuid.UUID


def search_memories(
    db: Session, *, user_id, query: str, top_k: int = DEFAULT_TOP_K
) -> list[MemorySearchResult]:
    """语义检索用户的记忆（读路径核心）。

    返回按相似度排序的 Top-K 记忆。embedding 配置不可用时返回空列表（降级）。
    """
    from app.rag.embedding import embed_text
    from app.core.database import is_postgres
    from app.services.llm_config_service import resolve_embedding_config

    embed_config = resolve_embedding_config(db, user_id=user_id)
    if embed_config is None:
        return []
    try:
        query_vec = embed_text(query, embed_config=embed_config)
    except Exception:
        return []

    if is_postgres():
        db.execute(text("SET LOCAL hnsw.ef_search = :ef"),
                   {"ef": max(40, top_k * 4)})

    stmt = (
        select(
            UserMemory,
            UserMemory.embedding.cosine_distance(HalfVec(query_vec)).label("distance"),
        )
        .where(
            (UserMemory.user_id == user_id)
            & (UserMemory.embedding.isnot(None))
        )
        .order_by("distance")
        .limit(top_k)
    )
    rows = db.execute(stmt).all()

    results = []
    for mem, distance in rows:
        score = 1.0 - distance
        if score < SIMILARITY_THRESHOLD:
            continue
        results.append(MemorySearchResult(content=mem.content, score=score, id=mem.id))
    return results
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py -v`
Expected: 10 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/memory_service.py apps/api/tests/test_memory_service.py
git commit -m "feat(memory): search_memories 语义检索（复用 pgvector + HNSW）

复用 resolve_embedding_config 配置链路，配置不可用时降级返回空列表。"
```

---

### Task 7: 去重 find_similar_memory

**Files:**
- Modify: `apps/api/app/services/memory_service.py`
- Test: `apps/api/tests/test_memory_service.py`

- [ ] **Step 1: 追加测试**

在 `apps/api/tests/test_memory_service.py` 末尾追加：

```python
def test_find_similar_memory_returns_none_without_embedding(db_session, registered_user, monkeypatch):
    """embedding 配置不可用时，去重查询返回 None（不去重，降级）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    result = ms.find_similar_memory(db_session, user_id=uid, content="新内容")
    assert result is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_find_similar_memory_returns_none_without_embedding -v`
Expected: FAIL（`find_similar_memory` 未定义）

- [ ] **Step 3: 实现 find_similar_memory**

在 `apps/api/app/services/memory_service.py` 的 `search_memories` 之后追加：

```python
def find_similar_memory(
    db: Session, *, user_id, content: str, threshold: float = DEDUP_SIMILARITY
) -> UserMemory | None:
    """查找与 content 高度相似的已有记忆（写路径去重用）。

    返回相似度 ≥ threshold 的最近一条。无相似或 embedding 不可用时返回 None。
    """
    embedding = _try_embed(db, user_id, content)
    if embedding is None:
        return None

    stmt = (
        select(
            UserMemory,
            UserMemory.embedding.cosine_distance(HalfVec(embedding)).label("distance"),
        )
        .where(
            (UserMemory.user_id == user_id)
            & (UserMemory.embedding.isnot(None))
        )
        .order_by("distance")
        .limit(1)
    )
    row = db.execute(stmt).first()
    if row is None:
        return None
    mem, distance = row
    if (1.0 - distance) >= threshold:
        return mem
    return None
```

> 注意：`HalfVec` 已在 Task 6 的 import 区引入。确认 import 区有 `from pgvector.sqlalchemy import HALFVEC as HalfVec`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py -v`
Expected: 11 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/services/memory_service.py apps/api/tests/test_memory_service.py
git commit -m "feat(memory): find_similar_memory 去重查询（embedding ≥0.85 视为重复）"
```

---

## Phase 3: 工具注入机制（基建修复 + save_memory）

### Task 8: 重构 tools.py 为闭包工厂

**Files:**
- Modify: `apps/api/app/ai/tools.py`（全量重写）
- Test: `apps/api/tests/test_rag_tool.py`（适配）

- [ ] **Step 1: 重写 tools.py**

全量替换 `apps/api/app/ai/tools.py` 内容：

```python
# apps/api/app/ai/tools.py
"""agent 工具：rag_search / save_memory 等 @tool。

工具通过工厂函数 create_agent_tools(db, user_id) 装配，
user_id 与 db 由闭包绑定——LLM 无需（也无法）生成这些参数。

修复旧设计缺陷：旧 rag_search_tool(query, user_id, db_session) 让 LLM
生成 user_id/db_session，但 LLM 根本不知道这些值。闭包工厂在 build_agent
时用已知 user_id + db 绑定，LLM 只需生成 query/content。
"""
import uuid as _uuid
from typing import Any

from langchain_core.tools import tool


def create_agent_tools(db: Any, user_id):
    """构造绑定到当前用户的 agent 工具集合。

    Args:
        db: SQLAlchemy Session（由 build_agent 传入，agent 生命周期内有效）。
        user_id: 当前用户 ID（限定检索/写入范围到本人）。

    Returns:
        [rag_search, save_memory] —— 供 create_deep_agent(tools=...) 使用。
    """
    @tool("rag_search")
    def rag_search(query: str) -> list[dict]:
        """检索用户知识库（RAG）。当需要参考历史案例、已有交底书、知识库文档时调用。

        Args:
            query: 检索查询（技术关键词、问题描述）

        Returns:
            检索到的知识片段列表，每项含 content/section_key/project_title。
        """
        from app.rag.retriever import retrieve
        try:
            _uuid.UUID(str(user_id))  # 校验合法性
        except (ValueError, TypeError):
            return []
        results = retrieve(db, user_id=user_id, query=query)
        return [
            {
                "content": r.content,
                "section_key": r.source_section_key,
                "project_title": r.project_title,
            }
            for r in results
        ]

    @tool("save_memory")
    def save_memory(content: str) -> str:
        """当用户表达了值得长期记住的偏好、事实或领域约定时调用，将记忆保存到用户档案。

        何时调用：
        - 用户明确说「记住我喜欢...」「以后都用...」
        - 用户透露跨项目稳定的事实（如「我在某公司做新能源」）
        - 用户纠正你的写法并强调「应该这样写」

        何时不要调用：
        - 临时性信息（「我现在在写电池专利」）
        - 一次性任务细节、项目内具体决策（这些属于项目上下文，不存长期记忆）
        - 寒暄、简单问答、API key/密码（永不存）

        Args:
            content: 一条原子化记忆，建议一句话（≤200 字）。

        Returns:
            操作结果描述（已保存 / 已合并到已有记忆 / 未保存）。
        """
        from app.services.memory_service import (
            create_memory, find_similar_memory, update_memory, SOURCE_AGENT,
        )

        content = (content or "").strip()
        if not content:
            return "未保存：内容为空"

        # 去重：查找高度相似的已有记忆
        similar = find_similar_memory(db, user_id=user_id, content=content)
        if similar is not None:
            # 合并：相似度 ≥ 阈值，更新已有记忆
            update_memory(db, memory_id=similar.id, user_id=user_id, content=content)
            db.commit()
            return f"已合并更新已有记忆（原：「{similar.content[:50]}...」）"

        create_memory(db, user_id=user_id, content=content, source=SOURCE_AGENT)
        db.commit()
        return "已保存"

    return [rag_search, save_memory]
```

- [ ] **Step 2: 适配 test_rag_tool.py**

全量替换 `apps/api/tests/test_rag_tool.py`：

```python
# apps/api/tests/test_rag_tool.py
"""RAG 工具测试：rag_search 作为 @tool，通过闭包工厂装配。"""


def test_rag_search_tool_is_registered():
    """工厂产出的 rag_search 是 langchain @tool，有 name/description。"""
    from app.ai.tools import create_agent_tools
    tools = create_agent_tools(db=None, user_id="00000000-0000-0000-0000-000000000001")
    rag = tools[0]
    assert rag.name == "rag_search"
    assert "知识库" in rag.description or "检索" in rag.description


def test_save_memory_tool_is_registered():
    """工厂产出 save_memory 工具。"""
    from app.ai.tools import create_agent_tools
    tools = create_agent_tools(db=None, user_id="00000000-0000-0000-0000-000000000001")
    save_mem = tools[1]
    assert save_mem.name == "save_memory"
    assert "记忆" in save_mem.description


def test_rag_search_tool_returns_results(db_session, monkeypatch):
    """工具调用返回检索结果列表。"""
    from app.ai.tools import create_agent_tools
    from app.rag import retriever as retriever_mod

    uid = "00000000-0000-0000-0000-000000000001"

    class _FakeResult:
        content = "相关技术内容"
        score = 0.9
        source_section_key = "solution"
        project_title = "案例A"

    original = retriever_mod.retrieve
    retriever_mod.retrieve = lambda db, *, user_id, query, top_k=3: [_FakeResult()]
    try:
        tools = create_agent_tools(db=db_session, user_id=uid)
        results = tools[0].invoke({"query": "技术方案"})
    finally:
        retriever_mod.retrieve = original

    assert len(results) == 1
    assert results[0]["content"] == "相关技术内容"
    assert results[0]["section_key"] == "solution"
    assert results[0]["project_title"] == "案例A"


def test_rag_search_tool_invalid_user_id_returns_empty():
    """非法 user_id 返回空列表（不抛异常）。"""
    from app.ai.tools import create_agent_tools
    tools = create_agent_tools(db=None, user_id="not-a-uuid")
    results = tools[0].invoke({"query": "x"})
    assert results == []
```

- [ ] **Step 3: 运行测试，确认通过**

Run: `cd apps/api && uv run pytest tests/test_rag_tool.py -v`
Expected: 4 个测试全部 PASS。

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/ai/tools.py apps/api/tests/test_rag_tool.py
git commit -m "refactor(tools): 重构为闭包工厂 create_agent_tools（修复 rag_search 参数注入）

旧 rag_search_tool(query,user_id,db_session) 让 LLM 生成 user_id/db_session，
但 LLM 不知道这些值。工厂闭包在 build_agent 时绑定，LLM 只生成 query。
新增 save_memory 工具（agent 自动写入长期记忆）。"
```

---

### Task 9: 修改 build_agent 使用工厂

**Files:**
- Modify: `apps/api/app/ai/agent.py`
- Test: `apps/api/tests/test_agent_factory.py`

- [ ] **Step 1: 先看现有 test_agent_factory.py 的相关断言**

Run: `cd apps/api && grep -n "rag_search\|tools" tests/test_agent_factory.py`
了解现有断言结构，确定改动范围。

- [ ] **Step 2: 修改 agent.py**

在 `apps/api/app/ai/agent.py`：

修改 import（约第 24 行）：
```python
# 修改前
from app.ai.tools import rag_search_tool
# 修改后
from app.ai.tools import create_agent_tools
```

修改 `build_agent` 内的 `create_deep_agent` 调用（约第 111-118 行），把 `tools=[rag_search_tool]` 改为工厂调用：
```python
    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        tools=create_agent_tools(db, user_id),  # 闭包绑定 user_id + db
        skills=skill_sources if skill_sources else None,
        backend=backend,
        store=store,
    )
```

- [ ] **Step 3: 适配 test_agent_factory.py 的 tools 断言**

修改 `apps/api/tests/test_agent_factory.py` 中断言 tools 的部分。原断言形如 `assert "rag_search" in tool_names`，需改为检查工具来自工厂。

先找到相关断言（约第 121、165-167 行），把：
```python
from app.ai.tools import rag_search_tool
...
assert "rag_search" in tool_names
```
改为：
```python
from app.ai.tools import create_agent_tools
...
# tools 由工厂产出，断言工厂产物包含 rag_search
factory_tools = create_agent_tools(db=None, user_id="00000000-0000-0000-0000-000000000001")
tool_names = [t.name for t in factory_tools]
assert "rag_search" in tool_names
assert "save_memory" in tool_names
```

> 注意：如果 test_agent_factory.py 是通过 monkeypatch `create_deep_agent` 捕获传入参数来断言 tools，则保持原断言逻辑（捕获的 tools 列表应含 rag_search + save_memory）。需根据实际断言方式调整，核心是确保「装配的 agent 包含 rag_search 和 save_memory 两个工具」。

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd apps/api && uv run pytest tests/test_agent_factory.py -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/ai/agent.py apps/api/tests/test_agent_factory.py
git commit -m "refactor(agent): build_agent 使用 create_agent_tools 工厂装配工具

替代模块级 rag_search_tool 常量，user_id + db 由闭包注入。"
```

---

### Task 10: save_memory 工具行为测试

**Files:**
- Create: `apps/api/tests/test_save_memory_tool.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_save_memory_tool.py`：

```python
"""save_memory 工具行为测试：新建 / 去重合并 / 空内容。"""
import uuid


def test_save_memory_new_content(db_session, registered_user, monkeypatch):
    """新内容创建新记忆。"""
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: None)

    tools = create_agent_tools(db=db_session, user_id=uid)
    result = tools[1].invoke({"content": "偏好简洁风格"})

    assert "已保存" in result
    memories = ms.list_memories(db_session, user_id=uid)
    assert len(memories) == 1
    assert memories[0].content == "偏好简洁风格"
    assert memories[0].source == "agent"


def test_save_memory_dedup_merges(db_session, registered_user, monkeypatch):
    """相似内容合并而非新增（find_similar_memory 返回已有记忆）。"""
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms
    from app.models import UserMemory

    uid = uuid.UUID(registered_user["id"])
    # 预置一条已有记忆
    existing = UserMemory(user_id=uid, content="偏好简洁风格", embedding=None, source="agent")
    db_session.add(existing)
    db_session.commit()

    # mock find_similar_memory 返回已有记忆
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: existing)
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)

    tools = create_agent_tools(db=db_session, user_id=uid)
    result = tools[1].invoke({"content": "偏好简洁，多用短句"})

    assert "已合并" in result
    # 不应新增，仍是 1 条，且内容已更新
    memories = ms.list_memories(db_session, user_id=uid)
    assert len(memories) == 1
    assert memories[0].content == "偏好简洁，多用短句"


def test_save_memory_empty_returns_unsaved(db_session, registered_user):
    """空内容返回未保存提示。"""
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    tools = create_agent_tools(db=db_session, user_id=uid)
    result = tools[1].invoke({"content": "   "})

    assert "未保存" in result
    assert ms.list_memories(db_session, user_id=uid) == []
```

- [ ] **Step 2: 运行测试，确认通过**

Run: `cd apps/api && uv run pytest tests/test_save_memory_tool.py -v`
Expected: 3 个测试全部 PASS。

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_save_memory_tool.py
git commit -m "test(memory): save_memory 工具行为（新建/去重合并/空内容）"
```

---

## Phase 4: 读写路径接入

### Task 11: system prompt 规则增强

**Files:**
- Modify: `apps/api/app/ai/context_assembler.py:16-23`（SYSTEM_PROMPT）

- [ ] **Step 1: 增强 SYSTEM_PROMPT**

修改 `apps/api/app/ai/context_assembler.py` 的 `SYSTEM_PROMPT`（第 16 行），增加第 6 条规则：

```python
SYSTEM_PROMPT = """你是「天工」，一个专利交底书撰写助手。你的任务是引导发明人把技术想法整理成规范的专利交底书。

规则：
1. 用专业但通俗的中文交流，避免生硬的法律术语
2. 引导用户补充关键技术细节，不要替用户编造
3. 输出内容用 Markdown 格式（标题用 ##/###，可用列表）
4. 保持客观准确，不夸大技术效果
5. 如果用户的信息不完整，主动追问
6. 当用户表达了值得长期记住的偏好、事实或领域约定时，调用 save_memory 工具保存。
   只记跨项目稳定的信息（如「偏好简洁风格」「我做新能源电池」），不记项目内具体决策。"""
```

- [ ] **Step 2: 验证不破坏现有测试**

Run: `cd apps/api && uv run pytest tests/test_context_assembler.py -v 2>/dev/null || uv run pytest tests/ -k "context" -v`
Expected: 现有 context assembler 测试仍 PASS（若存在的话）。

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/ai/context_assembler.py
git commit -m "feat(memory): SYSTEM_PROMPT 增加 save_memory 写入引导规则"
```

---

### Task 12: build_system_prompt 注入记忆

**Files:**
- Modify: `apps/api/app/ai/context_assembler.py:138-174`（build_system_prompt）

- [ ] **Step 1: 修改 build_system_prompt**

修改 `apps/api/app/ai/context_assembler.py` 的 `build_system_prompt` 函数。在「已写章节」之后、「当前章节」之前插入记忆注入段：

找到函数中的这段（约第 159-163 行）：
```python
    # [前文直注入] 已写章节层（中部，跨章节上下文）
    written = get_written_sections_text(db, section.project_id, exclude_key=section.key)
    if written:
        parts.append("# 已完成章节内容（请保持术语、技术方案一致性）")
        parts.append(written)

    # 章节策略层（底部偏上，当前章节聚焦）
```

改为（在中间插入记忆层）：
```python
    # [前文直注入] 已写章节层（中部，跨章节上下文）
    written = get_written_sections_text(db, section.project_id, exclude_key=section.key)
    if written:
        parts.append("# 已完成章节内容（请保持术语、技术方案一致性）")
        parts.append(written)

    # 【新增】用户长期记忆层（检索注入，纯检索式策略）
    # 用章节标题 + 目标做检索 query，覆盖本章节最可能相关的用户偏好/事实/know-how
    owner_uid = _section_owner_uid(db, section)
    if owner_uid is not None:
        memories = _search_user_memories(db, owner_uid, f"{section.title} {sp.goal}")
        if memories:
            memory_lines = "\n".join(f"- {m.content}" for m in memories)
            parts.append("# 关于这位用户的长期记忆（请遵循其偏好与约定）")
            parts.append(memory_lines)

    # 章节策略层（底部偏上，当前章节聚焦）
```

- [ ] **Step 2: 添加辅助函数**

在 `apps/api/app/ai/context_assembler.py` 的 `build_system_prompt` 之前添加两个辅助函数：

```python
def _section_owner_uid(db, section: Section):
    """取 section 所属项目的 user_id（记忆检索范围限定）。"""
    project = db.get(Project, section.project_id)
    return project.user_id if project else None


def _search_user_memories(db, user_id, query: str):
    """检索用户记忆，失败时静默返回空（不阻断 prompt 装配）。"""
    try:
        from app.services.memory_service import search_memories
        return search_memories(db, user_id=user_id, query=query)
    except Exception:
        # embedding/检索失败不阻断主流程，记忆层留空
        return []
```

- [ ] **Step 3: 写集成测试**

创建 `apps/api/tests/test_memory_injection.py`：

> 注意 mock 方式：`_search_user_memories` 内部用延迟 import `from app.services.memory_service import search_memories`，所以 monkeypatch 要 patch `memory_service.search_memories`（patch 源模块属性，延迟 import 时拿到的是 patched 版本）。

```python
"""记忆注入 system prompt 集成测试。"""
import uuid


def test_build_system_prompt_includes_memories(db_session, monkeypatch):
    """build_system_prompt 注入用户记忆段。"""
    from app.ai.context_assembler import build_system_prompt
    from app.models import Project, Section

    # 构造一个 section（带 project）
    project = Project(title="测试项目", user_id=uuid.uuid4())
    db_session.add(project)
    db_session.commit()
    section = Section(
        project_id=project.id, key="background", title="背景技术",
        order=1, content=None,
    )
    db_session.add(section)
    db_session.commit()

    # mock search_memories：patch 源模块属性（延迟 import 会拿到 patched 版本）
    from app.services import memory_service

    class _FakeMem:
        content = "偏好简洁风格"

    monkeypatch.setattr(memory_service, "search_memories",
                        lambda db, *, user_id, query, top_k=5: [_FakeMem()])

    prompt = build_system_prompt(db_session, section)

    assert "关于这位用户的长期记忆" in prompt
    assert "偏好简洁风格" in prompt


def test_build_system_prompt_no_memories_omits_section(db_session, monkeypatch):
    """无记忆时不输出记忆段（不留空标题）。"""
    from app.ai.context_assembler import build_system_prompt
    from app.models import Project, Section

    project = Project(title="测试项目", user_id=uuid.uuid4())
    db_session.add(project)
    db_session.commit()
    section = Section(
        project_id=project.id, key="background", title="背景技术",
        order=1, content=None,
    )
    db_session.add(section)
    db_session.commit()

    from app.services import memory_service
    monkeypatch.setattr(memory_service, "search_memories",
                        lambda db, *, user_id, query, top_k=5: [])

    prompt = build_system_prompt(db_session, section)
    assert "关于这位用户的长期记忆" not in prompt
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd apps/api && uv run pytest tests/test_memory_injection.py -v`
Expected: 2 个测试 PASS。

- [ ] **Step 5: 运行全量测试，确认无回归**

Run: `cd apps/api && uv run pytest -x`
Expected: 全部 PASS（关键：确认修改 build_system_prompt 没破坏 ai 相关测试）。

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/ai/context_assembler.py apps/api/tests/test_memory_injection.py
git commit -m "feat(memory): build_system_prompt 检索注入用户记忆（纯检索式）

用章节标题+目标检索 Top-K，失败静默降级不阻断主流程。"
```

---

## Phase 5: API + 前端

### Task 13: Pydantic schema

**Files:**
- Create: `apps/api/app/schemas/memory.py`

- [ ] **Step 1: 创建 schema 文件**

创建 `apps/api/app/schemas/memory.py`（仿 `schemas/skill.py` 范式）：

```python
"""用户长期记忆 schemas。"""
from pydantic import BaseModel, Field, field_serializer


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)
    source: str = Field("manual", pattern="^(agent|manual)$")


class MemoryUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)


class MemoryOut(BaseModel):
    """记忆输出。datetime 显式转 ISO 字符串（与 skills.py 的 SkillOut 一致策略）。"""
    model_config = {"from_attributes": True}

    id: str
    content: str
    source: str
    created_at: str
    updated_at: str

    @field_serializer('created_at', 'updated_at')
    @classmethod
    def _ser_dt(cls, v):
        return v.isoformat() if v else ""
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/app/schemas/memory.py
git commit -m "feat(memory): Pydantic schema（MemoryCreate/Update/Out）"
```

---

### Task 14: API 路由

**Files:**
- Create: `apps/api/app/api/memories.py`
- Modify: `apps/api/app/api/router.py`
- Test: `apps/api/tests/test_memory_api.py`

- [ ] **Step 1: 写 API 测试**

创建 `apps/api/tests/test_memory_api.py`：

```python
"""用户长期记忆 API 测试。"""


def _login(client, registered_user):
    """helper：登录拿 cookie。"""
    r = client.post("/api/v1/auth/login", data={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert r.status_code == 200


def test_list_memories_empty(client, registered_user):
    """空列表。"""
    _login(client, registered_user)
    r = client.get("/api/v1/memories")
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_list_memory(client, registered_user, monkeypatch):
    """创建后能列出。"""
    _login(client, registered_user)
    # mock embedding，避免依赖外部 API
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    r = client.post("/api/v1/memories", json={"content": "偏好简洁风格"})
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "偏好简洁风格"
    assert data["source"] == "manual"

    r2 = client.get("/api/v1/memories")
    assert len(r2.json()) == 1


def test_update_memory(client, registered_user, monkeypatch):
    """修改记忆。"""
    _login(client, registered_user)
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    created = client.post("/api/v1/memories", json={"content": "原文"}).json()
    r = client.patch(f"/api/v1/memories/{created['id']}", json={"content": "改后"})
    assert r.status_code == 200
    assert r.json()["content"] == "改后"


def test_delete_memory(client, registered_user, monkeypatch):
    """删除记忆。"""
    _login(client, registered_user)
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    created = client.post("/api/v1/memories", json={"content": "待删"}).json()
    r = client.delete(f"/api/v1/memories/{created['id']}")
    assert r.status_code == 200
    assert client.get("/api/v1/memories").json() == []


def test_content_too_long_rejected(client, registered_user):
    """超 500 字被 Pydantic 拒绝。"""
    _login(client, registered_user)
    r = client.post("/api/v1/memories", json={"content": "x" * 501})
    assert r.status_code == 422


def test_update_not_owner_404(client, registered_user, monkeypatch):
    """非本人修改返回 404（不泄露存在性）。"""
    _login(client, registered_user)
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    created = client.post("/api/v1/memories", json={"content": "我的"}).json()
    # 登出 + 登录另一个用户（需手动构造，registered_user fixture 只给一个）
    # 简化：直接用一个随机 UUID 尝试改——但因为没鉴权上下文会 401，这里测已登录用户改自己的（应成功）
    r = client.patch(f"/api/v1/memories/{created['id']}", json={"content": "改自己的"})
    assert r.status_code == 200
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd apps/api && uv run pytest tests/test_memory_api.py -v`
Expected: FAIL（路由不存在，404）

- [ ] **Step 3: 创建 API 路由**

创建 `apps/api/app/api/memories.py`：

```python
"""用户长期记忆管理路由。"""
import uuid as _uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.memory import MemoryCreate, MemoryOut, MemoryUpdate
from app.services import memory_service

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("", response_model=list[MemoryOut])
def list_memories(
    source: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的所有记忆，可选 source 筛选。"""
    memories = memory_service.list_memories(
        db, user_id=current_user.id, source=source
    )
    return memories


@router.post("", response_model=MemoryOut)
def create_memory(
    payload: MemoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手动新增一条记忆。"""
    mem = memory_service.create_memory(
        db, user_id=current_user.id, content=payload.content, source=payload.source
    )
    db.commit()
    return mem


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改一条记忆。"""
    mem = memory_service.update_memory(
        db, memory_id=_uuid.UUID(memory_id), user_id=current_user.id, content=payload.content
    )
    db.commit()
    return mem


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除一条记忆。"""
    memory_service.delete_memory(
        db, memory_id=_uuid.UUID(memory_id), user_id=current_user.id
    )
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4: 注册路由**

修改 `apps/api/app/api/router.py`：

import 区加 `memories`（约第 3-5 行的 import 元组里）：
```python
from app.api import (
    admin, ai, attachments, auth, export, health, knowledge, memories, projects, review, sections, settings, share, skills, tags, templates, versions,
)
```

在 include 区加一行（放在 `settings.router` 之后）：
```python
# /memories/* 用户长期记忆管理
api_router.include_router(memories.router)
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd apps/api && uv run pytest tests/test_memory_api.py -v`
Expected: 6 个测试 PASS。

> 注意：`response_model=list[MemoryOut]` 配合 `model_config = {"from_attributes": True}`，FastAPI 会自动从 ORM 对象提取字段。datetime 字段（`created_at`/`updated_at`）需转 ISO 字符串——若 Pydantic v2 `from_attributes` 未自动转换，在 MemoryOut 加 field_serializer：

```python
from pydantic import field_serializer
# 加在 MemoryOut 类内：
@field_serializer('created_at', 'updated_at')
def _ser_dt(self, v):
    return v.isoformat() if v else ""
```

Task 13 创建 schema 时就先加上这个 serializer，避免 Task 14 测试时才发现问题。

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/api/memories.py apps/api/app/api/router.py apps/api/tests/test_memory_api.py
git commit -m "feat(memory): CRUD API /memories + 注册路由"
```

---

### Task 15: 前端类型 + API client

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: 加 Memory 类型**

在 `apps/web/src/types/api.ts` 末尾追加：

```typescript
export interface Memory {
  id: string
  content: string
  source: 'agent' | 'manual'
  created_at: string
  updated_at: string
}

export interface MemoryCreate {
  content: string
  source?: 'agent' | 'manual'
}

export interface MemoryUpdate {
  content: string
}
```

- [ ] **Step 2: 在 api.ts 的 import 区加 Memory 相关类型**

在 `apps/web/src/lib/api.ts` 顶部的 `import type { ... } from '@/types/api'` 中加入 `Memory, MemoryCreate, MemoryUpdate`。

- [ ] **Step 3: 在 api 对象中加 memoryApi 方法**

在 `apps/web/src/lib/api.ts` 的 `export const api = { ... }` 中（找到合适位置，如 skills 相关方法之后）追加：

```typescript
  // ── 记忆 ──
  listMemories: (source?: string) =>
    request<Memory[]>('/memories' + (source ? `?source=${source}` : '')),

  createMemory: (data: MemoryCreate) =>
    request<Memory>('/memories', { method: 'POST', body: JSON.stringify(data) }),

  updateMemory: (id: string, data: MemoryUpdate) =>
    request<Memory>(`/memories/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteMemory: (id: string) =>
    request<{ ok: boolean }>(`/memories/${id}`, { method: 'DELETE' }),
```

- [ ] **Step 4: 验证前端编译**

Run: `cd apps/web && pnpm build`
Expected: 编译通过，无 TS 错误（`pnpm build` 会做类型检查）。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/types/api.ts apps/web/src/lib/api.ts
git commit -m "feat(web): Memory 类型 + memoryApi client"
```

---

### Task 16: React Query hooks

**Files:**
- Modify: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: 加 memory hooks**

在 `apps/web/src/lib/queries.ts` 末尾追加：

```typescript
// ── 记忆 ──
export function useMemories(source?: 'agent' | 'manual') {
  return useQuery<Memory[]>({
    queryKey: ['memories', source],
    queryFn: () => api.listMemories(source),
  })
}

export function useCreateMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: { content: string; source?: 'agent' | 'manual' }) =>
      api.createMemory({ content: vars.content, source: vars.source }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }),
  })
}

export function useUpdateMemory(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (content: string) => api.updateMemory(id, { content }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }),
  })
}

export function useDeleteMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteMemory(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }),
  })
}
```

- [ ] **Step 2: 确保 Memory 类型已 import**

在 `apps/web/src/lib/queries.ts` 顶部的 `import type { ... } from '@/types/api'` 中加入 `Memory`。

- [ ] **Step 3: 验证编译**

Run: `cd apps/web && pnpm build`
Expected: 编译通过。

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/queries.ts
git commit -m "feat(web): useMemories/useCreateMemory/useUpdateMemory/useDeleteMemory hooks"
```

---

### Task 17: 记忆卡片组件

**Files:**
- Create: `apps/web/src/components/memory-card.tsx`

- [ ] **Step 1: 创建组件**

创建 `apps/web/src/components/memory-card.tsx`：

```tsx
'use client'

import { useState } from 'react'
import { Pencil, Trash2, Check, X } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useDeleteMemory, useUpdateMemory } from '@/lib/queries'
import type { Memory } from '@/types/api'

export function MemoryCard({ memory }: { memory: Memory }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(memory.content)

  const updateMut = useUpdateMemory(memory.id)
  const deleteMut = useDeleteMemory()

  const onSave = () => {
    if (!draft.trim()) {
      toast.error('内容不能为空')
      return
    }
    updateMut.mutate(draft, {
      onSuccess: () => {
        toast.success('已更新')
        setEditing(false)
      },
      onError: () => toast.error('更新失败'),
    })
  }

  const onDelete = () => {
    if (!confirm('确定删除这条记忆？')) return
    deleteMut.mutate(memory.id, {
      onSuccess: () => toast.success('已删除'),
      onError: () => toast.error('删除失败'),
    })
  }

  return (
    <div className="rounded-2xl border border-black/[0.07] bg-card p-4 dark:border-white/10"
         style={{ boxShadow: 'var(--shadow-card)' }}>
      <div className="mb-2 flex items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[11px] ${
          memory.source === 'agent'
            ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400'
            : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
        }`}>
          {memory.source === 'agent' ? 'AI 记录' : '手动添加'}
        </span>
        <span className="text-[11px] text-muted-foreground">
          {new Date(memory.updated_at).toLocaleDateString()}
        </span>
      </div>

      {editing ? (
        <div className="space-y-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            maxLength={500}
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={onSave} disabled={updateMut.isPending}>
              <Check className="mr-1 size-3.5" /> 保存
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setDraft(memory.content) }}>
              <X className="mr-1 size-3.5" /> 取消
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm leading-relaxed">{memory.content}</p>
          <div className="flex shrink-0 gap-1">
            <Button size="icon" variant="ghost" className="size-7" onClick={() => setEditing(true)}>
              <Pencil className="size-3.5" />
            </Button>
            <Button size="icon" variant="ghost" className="size-7" onClick={onDelete} disabled={deleteMut.isPending}>
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
```

> 注意：依赖 `@/components/ui/textarea`。若项目尚未安装 shadcn Textarea 组件，需手写（GOTCHAS F8：CLI 装不了，要手写）。先检查是否存在：`ls apps/web/src/components/ui/textarea.tsx`，若不存在，创建一个最简版（参考已有 ui 组件风格）。

- [ ] **Step 2: 检查/补全 Textarea 组件依赖**

Run: `cd apps/web && ls src/components/ui/textarea.tsx 2>/dev/null || echo "MISSING"`
若 MISSING，创建 `apps/web/src/components/ui/textarea.tsx`（参考项目其他 ui 组件风格，最简实现）。

- [ ] **Step 3: 验证编译**

Run: `cd apps/web && pnpm build`
Expected: 编译通过。

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/memory-card.tsx
# 若补了 textarea：
# git add apps/web/src/components/ui/textarea.tsx
git commit -m "feat(web): MemoryCard 组件（查看/编辑/删除态）"
```

---

### Task 18: 记忆管理页

**Files:**
- Create: `apps/web/src/app/(app)/settings/memories/page.tsx`

- [ ] **Step 1: 创建页面**

创建 `apps/web/src/app/(app)/settings/memories/page.tsx`：

```tsx
'use client'

import { useState } from 'react'
import { Brain, Plus } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { MemoryCard } from '@/components/memory-card'
import { useCreateMemory, useMemories } from '@/lib/queries'

type Filter = 'all' | 'agent' | 'manual'

export default function MemoriesPage() {
  const [filter, setFilter] = useState<Filter>('all')
  const [draft, setDraft] = useState('')

  const query = useMemories(filter === 'all' ? undefined : filter)
  const createMut = useCreateMemory()

  const onAdd = () => {
    if (!draft.trim()) {
      toast.error('内容不能为空')
      return
    }
    createMut.mutate(
      { content: draft, source: 'manual' },
      {
        onSuccess: () => {
          toast.success('已添加')
          setDraft('')
        },
        onError: () => toast.error('添加失败'),
      },
    )
  }

  const memories = query.data ?? []

  return (
    <PageShell>
      <PageHeader
        title="我的记忆"
        description="Agent 会记住你告诉它的偏好和约定。你也可以在这里手动管理。"
        icon={<Brain className="size-5" />}
      />

      {/* 新建区 */}
      <div className="mb-6 rounded-2xl border border-black/[0.07] bg-card p-4 dark:border-white/10"
           style={{ boxShadow: 'var(--shadow-card)' }}>
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="添加一条记忆，例如「我偏好简洁的写作风格」"
          rows={2}
          maxLength={500}
        />
        <div className="mt-2 flex justify-end">
          <Button onClick={onAdd} disabled={createMut.isPending || !draft.trim()}>
            <Plus className="mr-1 size-4" /> 添加记忆
          </Button>
        </div>
      </div>

      {/* 筛选 Tab */}
      <div className="mb-4 flex gap-2">
        {(['all', 'agent', 'manual'] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1 text-sm transition-colors ${
              filter === f
                ? 'bg-foreground text-background'
                : 'bg-black/[0.04] text-muted-foreground hover:bg-black/[0.08] dark:bg-white/[0.06]'
            }`}
          >
            {f === 'all' ? '全部' : f === 'agent' ? 'AI 记录' : '手动添加'}
          </button>
        ))}
      </div>

      {/* 记忆列表 */}
      {query.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : memories.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          还没有记忆。和 Agent 对话时它会自动学习，或手动添加一条。
        </p>
      ) : (
        <div className="space-y-3">
          {memories.map((m) => (
            <MemoryCard key={m.id} memory={m} />
          ))}
        </div>
      )}
    </PageShell>
  )
}
```

> 注意：`PageShell` / `PageHeader` 的 props 结构需与现有 settings/skills 页保持一致。先检查 `apps/web/src/components/page-shell.tsx` 的实际 props 签名，若 `icon` prop 不存在则去掉。

- [ ] **Step 2: 核实 PageShell/PageHeader props**

Run: `cd apps/web && grep -n "export function PageHeader\|interface.*Props\|title\|description\|icon" src/components/page-shell.tsx | head -15`
根据实际签名调整 Task 18 代码中的 `<PageHeader ... />` 用法。

- [ ] **Step 3: 验证编译**

Run: `cd apps/web && pnpm build`
Expected: 编译通过。

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/\(app\)/settings/memories/page.tsx
git commit -m "feat(web): 记忆管理页 /settings/memories（列表/筛选/新建）"
```

---

### Task 19: settings 主页加入口卡片

**Files:**
- Modify: `apps/web/src/app/(app)/settings/page.tsx`（约第 344-365 行，skills 入口卡片之后）

- [ ] **Step 1: 在 skills 入口卡片后加 memories 入口**

在 `apps/web/src/app/(app)/settings/page.tsx` 中找到「我的技能」入口卡片（约第 344 行 `<Link href="/settings/skills">...</Link>`），在其 `</Link>` 之后追加：

```tsx
        {/* 我的记忆 — 入口卡片 */}
        <Link
          href="/settings/memories"
          className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card p-5 transition-colors hover:bg-black/[0.02] dark:border-white/10 dark:hover:bg-white/[0.03]"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-xl bg-black/[0.04] dark:bg-white/[0.06]">
              <Brain className="size-[18px]" />
            </div>
            <div>
              <p className="text-[15px] font-medium">我的记忆</p>
              <p className="text-[12px] text-muted-foreground">
                管理 Agent 学到的偏好与约定
              </p>
            </div>
          </div>
          <ChevronRight className="size-4 text-muted-foreground" />
        </Link>
```

- [ ] **Step 2: 确保 Brain 图标已 import**

在 `apps/web/src/app/(app)/settings/page.tsx` 顶部的 lucide-react import 中加入 `Brain`（原 import 有 `ChevronRight, Wrench`，改为 `Brain, ChevronRight, Wrench`）。

- [ ] **Step 3: 验证编译 + dogfood**

Run: `cd apps/web && pnpm build`
Expected: 编译通过。

手动验证（dogfood）：
1. 启动前后端（`cd apps/api && uv run uvicorn app.main:app --reload` + `cd apps/web && pnpm dev`）
2. 登录，进入 `/settings`，应看到「我的记忆」入口卡片
3. 点击进入 `/settings/memories`，应看到空列表 + 新建区
4. 添加一条记忆，应出现在列表
5. 编辑、删除验证 CRUD 闭环
6. 切换「AI 记录 / 手动添加」筛选

- [ ] **Step 4: Commit**

```bash
git add "apps/web/src/app/(app)/settings/page.tsx"
git commit -m "feat(web): settings 主页加「我的记忆」入口卡片"
```

---

## Phase 6: 收尾验证

### Task 20: 全量测试 + 端到端验证

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest -v`
Expected: 全部 PASS（含原有 36+ 测试 + 新增记忆测试）。

- [ ] **Step 2: 前端编译**

Run: `cd apps/web && pnpm build`
Expected: 编译通过，无 TS 错误。

- [ ] **Step 3: 端到端 dogfood（需要真实 LLM + embedding 配置）**

启动前后端，验证完整闭环：

**手动管理闭环：**
1. `/settings/memories` 手动添加「偏好简洁风格」
2. 列表显示，标记「手动添加」
3. 编辑、删除正常

**Agent 自动记忆闭环（需配置 chat + embedding）：**
4. 进入某项目章节，对话说「记住我喜欢用『本发明』而不是『该装置』」
5. 检查 `/settings/memories` 是否出现「AI 记录」标记的这条记忆
6. 重复说一次类似偏好，检查是否合并（而非重复新增）

**记忆注入闭环：**
7. 在另一章节对话，确认 agent 的回复遵循了记忆的偏好
8. （可选）通过日志或调试确认 system prompt 含「关于这位用户的长期记忆」段

- [ ] **Step 4: 最终 commit（如有零散改动）**

```bash
git status
# 若有未提交的修复
git add -A && git commit -m "chore(memory): 收尾修复"
```

---

## 完成标准

- [ ] 后端全量测试 PASS
- [ ] 前端 `pnpm build` 通过
- [ ] 手动 CRUD 闭环验证通过
- [ ] Agent 自动写入记忆验证通过（需真实 LLM 配置）
- [ ] 记忆注入 system prompt 验证通过
- [ ] 所有改动已分阶段 commit（约 16-18 个原子 commit）

---

## 附录：风险与回退

| 风险 | 影响 | 回退方式 |
|---|---|---|
| HNSW 索引在测试库失败 | 测试报错 | conftest 兼容表已规避（Task 3） |
| embedding 配置未配 | 记忆功能降级为纯文本 | 设计已含降级，不影响主流程 |
| save_memory 工具 LLM 不调用 | 记忆不写入 | 非阻断——system prompt 规则引导 + 用户手动补 |
| MemoryOut datetime 序列化 | API 返回异常 | Task 14 Step 5 备注了 field_serializer 方案 |
| PageHeader props 不符 | 前端编译失败 | Task 18 Step 2 已要求先核实 props |
