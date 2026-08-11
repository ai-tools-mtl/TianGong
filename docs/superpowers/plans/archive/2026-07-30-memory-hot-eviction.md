# 记忆热度淘汰与自动纠错 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为用户长期记忆增加 200 条上限 + 热度淘汰 + NLI 自动矛盾纠错，全程全自动、零用户操作、纠错每次 0 token。

**Architecture:** 写入时即时淘汰（cap-on-write），热度 = `(hit_count+1) × 时间衰减`；读路径两阶段召回重排（向量召回 + Python 热度重排）+ 命中计数批量回写；矛盾纠错走本地 Infinity 容器跑 `cross-encoder/nli-deberta-v3-base`，故障一律降级合并不删。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + pgvector(HNSW) + Alembic + Infinity(NLI 小模型) + httpx + pytest(SQLite 内存库)

**Spec:** `docs/superpowers/specs/2026-07-30-memory-hot-eviction-design.md`

---

## 关键约束（执行前必读）

1. **测试库建表特殊**：`tests/conftest.py` 的 `engine()` fixture 手动建 `user_memories` 兼容表（绕过 pgvector），新增字段必须同步加进 `um_compat`（Task 1），否则后续所有热度测试列不存在。
2. **NLI 是软依赖**：故障一律降级 `neutral` 走合并，绝不误删。`judge_relation` 任何异常返回 `neutral`。
3. **降级语义统一**：所有 embed/NLI 调用失败不阻断主流程——检索失败返回空，回写失败 rollback。
4. **不 commit 留给路由层**：service 函数只 `flush`，`commit` 由 API 路由负责（与现有 create/update 一致）。
5. **httpx 已有依赖**：`app/rag/reranker.py` 已用 httpx，NLI 复用，零新依赖。
6. **GOTCHAS G2**：SQLite 测试库不支持 pgvector，向量检索 mock `embed_text` 返回固定向量，断言 service 层逻辑。
7. **git 提交规范**：每个 Task 末尾 commit，提交信息遵循项目惯例（中文，`feat(scope):` 前缀）。

---

## File Structure

| 文件 | 操作 | 责任 |
|---|---|---|
| `apps/api/app/models/user_memory.py` | 修改 | 加 `hit_count` / `last_hit_at` 字段 |
| `apps/api/app/core/config.py` | 修改 | 加 4 个 env 配置项 |
| `apps/api/tests/conftest.py` | 修改 | `um_compat` 兼容表加 2 列 |
| `apps/api/alembic/versions/g7h8i9j0k1l2_add_memory_hot_fields.py` | 新建 | 迁移加 2 列 |
| `apps/api/app/services/memory_service.py` | 修改 | 淘汰算法 + 热度公式 + 检索重排 + 命中回写 |
| `apps/api/app/rag/nli.py` | 新建 | NLI 矛盾判断（httpx 直连 Infinity） |
| `apps/api/app/ai/tools.py` | 修改 | `save_memory` 升级为去重+矛盾判别 |
| `docker-compose.yml` | 修改 | 加 NLI 服务块 + api 注入 env |
| `apps/api/tests/test_memory_service.py` | 修改 | 追加热度/淘汰/重排测试 |
| `apps/api/tests/test_nli.py` | 新建 | NLI 降级安全阀测试 |
| `apps/api/tests/test_save_memory_tool.py` | 修改 | 追加矛盾覆盖测试 |

---

## Task 1: 数据模型 + 配置 + 测试库兼容（数据层）

**Files:**
- Modify: `apps/api/app/models/user_memory.py`
- Modify: `apps/api/app/core/config.py`
- Modify: `apps/api/tests/conftest.py`
- Create: `apps/api/alembic/versions/g7h8i9j0k1l2_add_memory_hot_fields.py`
- Test: `apps/api/tests/test_memory_service.py`

- [ ] **Step 1: 给 UserMemory 模型加 2 个字段**

修改 `apps/api/app/models/user_memory.py`，在 `source` 字段后追加。先在文件顶部 import 区加 `DateTime`：

```python
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
```

然后在 class 体内 `source` 字段后追加（注意：`TimestampMixin` 已提供 `created_at`/`updated_at`，这里加的是热度字段）：

```python
    source: Mapped[str] = mapped_column(String(20), default=SOURCE_AGENT)

    # 【v1.1】热度字段：淘汰算法用
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_hit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

文件顶部需要 import `datetime`（typing 用法），检查是否已有 `from datetime import datetime`，没有则加：

```python
from datetime import datetime
```

- [ ] **Step 2: 加 4 个配置项**

修改 `apps/api/app/core/config.py` 的 `Settings` 类，在 `embedding_api_key` 字段后、`# Firecrawl` 注释前追加：

```python
    embedding_api_key: str = ""

    # 【v1.1】记忆热度/淘汰配置
    memory_limit: int = 200                 # 单用户记忆上限
    memory_half_life_days: int = 30         # 热度衰减半衰期（天）
    memory_grace_days: int = 7              # 新记忆豁免期（天）
    nli_base_url: str = "http://localhost:7998"  # NLI 矛盾判断服务地址

    # Firecrawl (web ingestion;全局 key 存 SystemSetting,env 仅兜底)
```

- [ ] **Step 3: conftest 兼容表加 2 列**

修改 `apps/api/tests/conftest.py` 的 `um_compat` 表定义（约 117-126 行），在 `source` 列后、`created_at` 列前追加 2 列：

```python
        sa.Column("source", sa.String(20), default="agent"),
        sa.Column("hit_count", sa.Integer, default=0),           # 【v1.1】
        sa.Column("last_hit_at", sa.DateTime(timezone=True)),     # 【v1.1】
        sa.Column("created_at", sa.DateTime(timezone=True)),
```

- [ ] **Step 4: 新建迁移文件**

创建 `apps/api/alembic/versions/g7h8i9j0k1l2_add_memory_hot_fields.py`：

```python
"""add hit_count/last_hit_at to user_memories for hot eviction

Revision ID: g7h8i9j0k1l2
Revises: 9a3f7c2e1b4d
Create Date: 2026-07-30

为 user_memories 加热度字段（v1.1 记忆淘汰）：
- hit_count: 被 search_memories 命中的累计次数
- last_hit_at: 最近一次命中时间（NULL = 从未命中/刚创建）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "9a3f7c2e1b4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_memories",
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "user_memories",
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_memories", "last_hit_at")
    op.drop_column("user_memories", "hit_count")
```

- [ ] **Step 5: 验证迁移链正确**

Run: `cd apps/api && uv run alembic history | head -5`
Expected: `g7h8i9j0k1l2 (head)` 显示在最上方，`9a3f7c2e1b4d` 在其下作为 revises。

- [ ] **Step 6: 写一个验证字段读写的测试**

在 `apps/api/tests/test_memory_service.py` 末尾追加：

```python
def test_create_memory_initializes_hot_fields(db_session, registered_user, monkeypatch):
    """新增记忆的 hit_count=0、last_hit_at=None（v1.1 热度字段初始值）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    mem = ms.create_memory(db_session, user_id=uid, content="测试热度字段")

    assert mem.hit_count == 0
    assert mem.last_hit_at is None
```

- [ ] **Step 7: 运行测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_create_memory_initializes_hot_fields -v`
Expected: PASS

- [ ] **Step 8: 运行全量记忆测试确认无回归**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py tests/test_memory_api.py tests/test_save_memory_tool.py tests/test_memory_injection.py -v`
Expected: 全部 PASS（现有测试不受影响）

- [ ] **Step 9: Commit**

```bash
cd apps/api
git add app/models/user_memory.py app/core/config.py tests/conftest.py alembic/versions/g7h8i9j0k1l2_add_memory_hot_fields.py tests/test_memory_service.py
git commit -m "feat(memory): 记忆表加热度字段 hit_count/last_hit_at + 配置项

- UserMemory 加 hit_count/last_hit_at（淘汰算法用）
- config 加 MEMORY_LIMIT/HALF_LIFE_DAYS/GRACE_DAYS/NLI_BASE_URL
- conftest um_compat 同步加 2 列（SQLite 兼容）
- 迁移 g7h8i9j0k1l2 接 9a3f7c2e1b4d"
```

---

## Task 2: 热度公式 + 淘汰算法（写路径核心）

**Files:**
- Modify: `apps/api/app/services/memory_service.py`
- Test: `apps/api/tests/test_memory_service.py`

- [ ] **Step 1: 写热度公式失败测试**

在 `tests/test_memory_service.py` 末尾追加：

```python
def test_compute_hot_score_new_memory_full_decay(db_session):
    """新记忆（hit_count=0, last_hit_at=None）得满分衰减 1.0。"""
    from app.services import memory_service as ms
    from datetime import datetime, timezone

    class FakeMem:
        hit_count = 0
        last_hit_at = None

    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    score = ms._compute_hot_score(FakeMem(), now)
    assert score == 1.0  # (0+1) * decay(0) = 1 * 1.0


def test_compute_hot_score_half_life_decay(db_session):
    """30 天未命中分数腰斩到 0.5。"""
    from app.services import memory_service as ms
    from datetime import datetime, timedelta, timezone

    class FakeMem:
        hit_count = 9  # 基础分 10，腰斩后 5.0
        last_hit_at = None

    last = datetime(2026, 6, 30, tzinfo=timezone.utc)  # 30 天前
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    FakeMem.last_hit_at = last

    score = ms._compute_hot_score(FakeMem(), now)
    assert abs(score - 5.0) < 0.01  # (9+1) * 0.5 = 5.0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_compute_hot_score_new_memory_full_decay tests/test_memory_service.py::test_compute_hot_score_half_life_decay -v`
Expected: FAIL（`_compute_hot_score` / `_decay` 未定义）

- [ ] **Step 3: 实现 _decay 与 _compute_hot_score**

修改 `apps/api/app/services/memory_service.py`，在文件顶部 import 区补全（检查现有 import，缺的补上）：

```python
from datetime import datetime, timedelta, timezone
```

在常量区（`DEDUP_SIMILARITY` 后）追加：

```python
# 【v1.1】热度/淘汰参数（从 settings 读，默认值见 config.py）
from app.core.config import get_settings

_settings = get_settings()
HALF_LIFE_DAYS = _settings.memory_half_life_days
MEMORY_LIMIT = _settings.memory_limit
GRACE_DAYS = _settings.memory_grace_days
```

在 `_try_embed` 函数前追加两个辅助函数：

```python
def _decay(delta_seconds: float) -> float:
    """指数衰减。Δt=0 返回 1.0；半衰期(HALF_LIFE_DAYS 天)后腰斩到 0.5。"""
    days = delta_seconds / 86400
    return 0.5 ** (days / HALF_LIFE_DAYS)


def _compute_hot_score(mem, now: datetime) -> float:
    """实时计算热度分。

    score = (hit_count + 1) × decay(now - last_hit_at)
    - hit_count+1：避免零乘 + 冷启动公平（新记忆不天生垫底）
    - last_hit_at IS NULL（新记忆）：Δt=0 → decay=1.0（满分，不被淘汰）
    """
    hit = mem.hit_count or 0
    last = mem.last_hit_at or now  # NULL 视为「刚命中」，得满分衰减
    delta = (now - last).total_seconds()
    return (hit + 1) * _decay(delta)
```

- [ ] **Step 4: 运行热度公式测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_compute_hot_score_new_memory_full_decay tests/test_memory_service.py::test_compute_hot_score_half_life_decay -v`
Expected: PASS

- [ ] **Step 5: 写淘汰算法失败测试**

在 `tests/test_memory_service.py` 末尾追加：

```python
def test_enforce_capacity_under_limit_noop(db_session, registered_user, monkeypatch):
    """未超限时 _enforce_capacity 不删任何记忆。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    monkeypatch.setattr(ms, "MEMORY_LIMIT", 200)

    for i in range(10):  # 远低于 200
        ms.create_memory(db_session, user_id=uid, content=f"记忆{i}")
    db_session.commit()

    ms._enforce_capacity(db_session, user_id=uid)
    db_session.commit()

    from app.models import UserMemory
    count = db_session.query(UserMemory).filter_by(user_id=uid).count()
    assert count == 10  # 无删除


def test_enforce_capacity_evicts_coldest(db_session, registered_user, monkeypatch):
    """超限时淘汰 hit_count 最低 + 最久未命中的记忆。"""
    from app.services import memory_service as ms
    from app.models import UserMemory
    from datetime import datetime, timedelta, timezone

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    monkeypatch.setattr(ms, "MEMORY_LIMIT", 3)  # 小上限便于测试
    monkeypatch.setattr(ms, "GRACE_DAYS", 0)    # 关闭豁免，让旧记忆可被淘汰

    # 建一条「最冷」：hit_count=0，30 天前命中
    cold = ms.create_memory(db_session, user_id=uid, content="最冷记忆")
    cold.hit_count = 0
    cold.last_hit_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # 建两条「较热」：hit_count 高、近期命中
    hot1 = ms.create_memory(db_session, user_id=uid, content="热记忆1")
    hot1.hit_count = 10
    hot1.last_hit_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    hot2 = ms.create_memory(db_session, user_id=uid, content="热记忆2")
    hot2.hit_count = 5
    hot2.last_hit_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
    db_session.commit()

    # 写第 4 条触发淘汰（超 3 上限）
    ms.create_memory(db_session, user_id=uid, content="新记忆触发淘汰")
    db_session.commit()

    contents = [m.content for m in db_session.query(UserMemory).filter_by(user_id=uid).all()]
    assert "最冷记忆" not in contents  # 最冷被淘汰
    assert "热记忆1" in contents
    assert "热记忆2" in contents


def test_enforce_capacity_grace_period_protects_new(db_session, registered_user, monkeypatch):
    """7 天豁免期内的新记忆即便最冷也不被淘汰。"""
    from app.services import memory_service as ms
    from app.models import UserMemory

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    monkeypatch.setattr(ms, "MEMORY_LIMIT", 2)
    monkeypatch.setattr(ms, "GRACE_DAYS", 7)  # 默认豁免

    # 两条豁免期内的新记忆（last_hit_at=None）
    ms.create_memory(db_session, user_id=uid, content="新记忆1")
    ms.create_memory(db_session, user_id=uid, content="新记忆2")
    db_session.commit()

    # 写第 3 条触发淘汰，但前两条都在豁免期 → 无可淘汰
    ms.create_memory(db_session, user_id=uid, content="新记忆3")
    db_session.commit()

    count = db_session.query(UserMemory).filter_by(user_id=uid).count()
    assert count == 3  # 全部豁免，未删任何
```

- [ ] **Step 6: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_enforce_capacity_under_limit_noop tests/test_memory_service.py::test_enforce_capacity_evicts_coldest tests/test_memory_service.py::test_enforce_capacity_grace_period_protects_new -v`
Expected: FAIL（`_enforce_capacity` 未定义）

- [ ] **Step 7: 实现 _enforce_capacity 并接入 create_memory**

修改 `apps/api/app/services/memory_service.py` 的 `create_memory`，在 `db.flush()` 后、`return memory` 前插入淘汰调用：

```python
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
    _enforce_capacity(db, user_id)   # 【v1.1】写入后即时淘汰
    return memory
```

在 `create_memory` 后追加 `_enforce_capacity` 函数（注意顶部 import 区需有 `from sqlalchemy import func, select`，`func` 可能是新加的）：

```python
def _enforce_capacity(db: Session, *, user_id) -> None:
    """写入后检查容量，超限则淘汰最冷的一条。

    豁免：GRACE_DAYS 天内的新记忆（last_hit_at IS NULL 或距今 < GRACE_DAYS）不参与淘汰，
    防止刚写入即被删。

    双列近似排序（hit_count ASC, last_hit_at ASC）的单调性与
    (hit_count+1)×decay(Δt) 一致——热度最低 = 命中数最少 + 最久未触达。
    只删一条（每次写入最多 +1，删 1 即恢复上限）。
    全部在豁免期时暂不处理（MVP 200 条规模下概率极低）。
    """
    count = db.scalar(
        select(func.count()).select_from(UserMemory)
        .where(UserMemory.user_id == user_id)
    )
    if count <= MEMORY_LIMIT:
        return

    grace_cutoff = datetime.now(timezone.utc) - timedelta(days=GRACE_DAYS)
    coldest = db.scalars(
        select(UserMemory)
        .where(
            (UserMemory.user_id == user_id)
            & (UserMemory.last_hit_at.isnot(None))
            & (UserMemory.last_hit_at < grace_cutoff)
        )
        .order_by(UserMemory.hit_count.asc(), UserMemory.last_hit_at.asc())
        .limit(1)
    ).first()

    if coldest is not None:
        db.delete(coldest)
        db.flush()
```

补全顶部 import（检查 `func` 是否已 import）：

```python
from sqlalchemy import func, select, text
```

- [ ] **Step 8: 运行淘汰测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_enforce_capacity_under_limit_noop tests/test_memory_service.py::test_enforce_capacity_evicts_coldest tests/test_memory_service.py::test_enforce_capacity_grace_period_protects_new -v`
Expected: PASS

- [ ] **Step 9: 运行全量记忆测试确认无回归**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py tests/test_memory_api.py tests/test_save_memory_tool.py tests/test_memory_injection.py -v`
Expected: 全部 PASS

- [ ] **Step 10: Commit**

```bash
cd apps/api
git add app/services/memory_service.py tests/test_memory_service.py
git commit -m "feat(memory): 热度公式 + 写入时即时淘汰(cap-on-write)

- _decay: 指数衰减,半衰期 30 天
- _compute_hot_score: (hit_count+1)×decay, 新记忆满分不被误杀
- _enforce_capacity: 超限删最冷一条, 7 天豁免期保护新记忆
- create_memory 写入后接入淘汰"
```

---

## Task 3: 读路径两阶段召回重排 + 命中回写

**Files:**
- Modify: `apps/api/app/services/memory_service.py`
- Test: `apps/api/tests/test_memory_service.py`

- [ ] **Step 1: 写命中回写失败测试**

在 `tests/test_memory_service.py` 末尾追加：

```python
def test_bump_hit_counts_increments(db_session, registered_user, monkeypatch):
    """_bump_hit_counts 批量累加 hit_count 并更新 last_hit_at。"""
    from app.services import memory_service as ms
    from app.models import UserMemory

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    m1 = ms.create_memory(db_session, user_id=uid, content="m1")
    m2 = ms.create_memory(db_session, user_id=uid, content="m2")
    db_session.commit()
    assert m1.hit_count == 0

    ms._bump_hit_counts(db_session, [m1.id, m2.id])
    db_session.commit()

    db_session.refresh(m1)
    db_session.refresh(m2)
    assert m1.hit_count == 1
    assert m2.hit_count == 1
    assert m1.last_hit_at is not None


def test_bump_hit_counts_failure_returns_silently(db_session, registered_user, monkeypatch):
    """_bump_hit_counts 失败时静默 rollback，不抛异常（尽力而为）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])

    # 让 execute 抛异常模拟失败
    def boom(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(db_session, "execute", boom)

    # 不应抛异常
    ms._bump_hit_counts(db_session, [uuid.uuid4()])
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_bump_hit_counts_increments tests/test_memory_service.py::test_bump_hit_counts_failure_returns_silently -v`
Expected: FAIL（`_bump_hit_counts` 未定义）

- [ ] **Step 3: 实现 _bump_hit_counts**

修改 `apps/api/app/services/memory_service.py`，顶部 import 区补 `update`（检查是否已有）：

```python
from sqlalchemy import func, select, text, update
```

在 `_enforce_capacity` 后追加：

```python
def _bump_hit_counts(db: Session, memory_ids: list) -> None:
    """批量更新命中计数（单条 SQL）。失败静默 rollback，不阻断检索。

    检索结果已算出，回写失败只是热度不准，可接受——尽力而为。
    """
    if not memory_ids:
        return
    try:
        now = datetime.now(timezone.utc)
        db.execute(
            update(UserMemory)
            .where(UserMemory.id.in_(memory_ids))
            .values(hit_count=UserMemory.hit_count + 1, last_hit_at=now)
        )
        db.flush()
    except Exception:
        db.rollback()  # 防 PG 事务中毒化后续查询
```

- [ ] **Step 4: 运行回写测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_bump_hit_counts_increments tests/test_memory_service.py::test_bump_hit_counts_failure_returns_silently -v`
Expected: PASS

- [ ] **Step 5: 写重排失败测试**

在 `tests/test_memory_service.py` 末尾追加：

```python
def test_search_memories_reranks_by_hotness(db_session, registered_user, monkeypatch):
    """热度高的记忆排在向量距离更近但热度低的之前（两阶段重排）。"""
    from app.services import memory_service as ms
    from datetime import datetime, timedelta, timezone

    uid = uuid.UUID(registered_user["id"])
    # 固定向量，让两条记忆向量距离相同（都返回）→ 纯靠热度重排
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [1.0] * 1024)
    monkeypatch.setattr(ms, "SIMILARITY_THRESHOLD", 0.0)  # 放宽，确保都过阈值

    # 向量距离相同的两条（embedding 相同 → cosine_distance=0）
    cold = ms.create_memory(db_session, user_id=uid, content="冷")
    cold.hit_count = 0
    cold.last_hit_at = datetime(2026, 1, 1, tzinfo=timezone.utc)  # 很久以前
    hot = ms.create_memory(db_session, user_id=uid, content="热")
    hot.hit_count = 100
    hot.last_hit_at = datetime(2026, 7, 29, tzinfo=timezone.utc)  # 近期
    db_session.commit()

    results = ms.search_memories(db_session, user_id=uid, query="任意")
    assert len(results) == 2
    assert results[0].content == "热"  # 高热度排前
    assert results[1].content == "冷"
```

- [ ] **Step 6: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_search_memories_reranks_by_hotness -v`
Expected: FAIL（当前 search_memories 纯向量排序，未按热度重排，"热"可能不在首位）

- [ ] **Step 7: 重写 search_memories 为两阶段重排**

修改 `apps/api/app/services/memory_service.py` 的 `search_memories`，整体替换（保留现有的 HNSW ef_search 与 NaN 防御）：

```python
def search_memories(
    db: Session, *, user_id, query: str, top_k: int = DEFAULT_TOP_K
) -> list[MemorySearchResult]:
    """语义检索用户的记忆（读路径核心）+ 热度重排。

    两阶段（v1.1）：
    1. 向量召回 Top-(top_k×3)：cosine_distance + HNSW，放大候选集保高热度记忆不被截断
    2. Python 热度重排：(hit_count+1)×decay(Δt)，取最终 Top-K
    3. 命中计数回写：批量 _bump_hit_counts（尽力而为）

    embedding 配置不可用或 query 向量化失败时返回空列表（降级）。
    pgvector 仅 PostgreSQL 生效，SQLite 无法执行向量查询。
    """
    from app.core.database import is_postgres

    query_vec = _try_embed(db, user_id, query)
    if query_vec is None:
        return []

    # G1：HNSW ef_search 随 top_k 放大（召回阶段取 top_k×3，ef 也相应放大）
    if is_postgres():
        ef = max(40, top_k * 4 * 3)
        db.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef)}"))

    # 阶段1：向量召回，放大候选集
    recall_k = max(top_k * 3, 15)
    stmt = (
        select(
            UserMemory,
            UserMemory.embedding.cosine_distance(query_vec).label("distance"),
        )
        .where(
            (UserMemory.user_id == user_id)
            & (UserMemory.embedding.isnot(None))
        )
        .order_by("distance")
        .limit(recall_k)
    )
    rows = db.execute(stmt).all()

    # 阈值过滤 + NaN/范围防御（沿用 v1.0）
    candidates: list[tuple] = []
    for mem, distance in rows:
        vec_score = 1.0 - distance
        if distance != distance:  # NaN 检测
            continue
        if distance < 0 or distance > 2:
            continue
        if vec_score < SIMILARITY_THRESHOLD:
            continue
        candidates.append((mem, vec_score))

    # 阶段2：Python 热度重排（元组携带热度，不污染 ORM）
    now = datetime.now(timezone.utc)
    ranked = [(mem, vec_score, _compute_hot_score(mem, now)) for mem, vec_score in candidates]
    ranked.sort(key=lambda x: x[2], reverse=True)

    results = [
        MemorySearchResult(content=mem.content, score=vec_score, id=mem.id)
        for mem, vec_score, _hot in ranked[:top_k]
    ]

    # 阶段3：命中计数回写（尽力而为，不阻断）
    if results:
        _bump_hit_counts(db, [r.id for r in results])
    return results
```

- [ ] **Step 8: 运行重排测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py::test_search_memories_reranks_by_hotness -v`
Expected: PASS

- [ ] **Step 9: 运行全量记忆测试确认无回归**

Run: `cd apps/api && uv run pytest tests/test_memory_service.py tests/test_memory_api.py tests/test_memory_injection.py -v`
Expected: 全部 PASS

- [ ] **Step 10: Commit**

```bash
cd apps/api
git add app/services/memory_service.py tests/test_memory_service.py
git commit -m "feat(memory): 读路径两阶段召回重排 + 命中计数回写

- search_memories: 向量召回 top_k×3 → Python 热度重排 → Top-K
- _bump_hit_counts: 批量回写 hit_count/last_hit_at, 失败静默不阻断
- HNSW ef_search 随召回量放大"
```

---

## Task 4: NLI 矛盾判断模块（降级安全阀）

**Files:**
- Create: `apps/api/app/rag/nli.py`
- Test: `apps/api/tests/test_nli.py`

- [ ] **Step 1: 写 NLI 降级安全阀失败测试**

创建 `apps/api/tests/test_nli.py`：

```python
"""NLI 矛盾判断模块测试。

核心验证降级安全阀：服务故障/超时/异常时一律返回 neutral（走合并不删，绝不误判矛盾）。
"""
from unittest.mock import patch, MagicMock


def test_judge_relation_contradiction(monkeypatch):
    """NLI 明确返回 contradiction 时透传。"""
    from app.rag import nli

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    # Infinity /classify 返回 [[{"label":"contradiction","score":0.9}, ...]]
    fake_resp.json.return_value = [[
        {"label": "contradiction", "score": 0.9},
        {"label": "entailment", "score": 0.05},
        {"label": "neutral", "score": 0.05},
    ]]

    with patch("app.rag.nli.httpx.post", return_value=fake_resp):
        result = nli.judge_relation("偏好简洁", "偏好详尽")

    assert result == "contradiction"


def test_judge_relation_service_down_returns_neutral():
    """服务挂掉时降级 neutral（核心安全阀）。"""
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", side_effect=Exception("connection refused")):
        result = nli.judge_relation("偏好简洁", "偏好详尽")

    assert result == "neutral"  # 绝不误判矛盾


def test_judge_relation_timeout_returns_neutral():
    """超时降级 neutral。"""
    import httpx
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", side_effect=httpx.TimeoutException("timeout")):
        result = nli.judge_relation("a", "b")

    assert result == "neutral"


def test_judge_relation_http_error_returns_neutral():
    """HTTP 4xx/5xx 降级 neutral。"""
    from app.rag import nli

    fake_resp = MagicMock()
    fake_resp.raise_for_status.side_effect = Exception("500 server error")

    with patch("app.rag.nli.httpx.post", return_value=fake_resp):
        result = nli.judge_relation("a", "b")

    assert result == "neutral"


def test_judge_relation_entailment():
    """返回 entailment 时透传。"""
    from app.rag import nli

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = [[
        {"label": "entailment", "score": 0.95},
        {"label": "contradiction", "score": 0.03},
        {"label": "neutral", "score": 0.02},
    ]]

    with patch("app.rag.nli.httpx.post", return_value=fake_resp):
        result = nli.judge_relation("偏好简洁", "我喜欢简短")

    assert result == "entailment"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_nli.py -v`
Expected: FAIL（`app.rag.nli` 模块不存在）

- [ ] **Step 3: 实现 nli.py**

创建 `apps/api/app/rag/nli.py`（结构镜像 `reranker.py`）：

```python
"""NLI 矛盾判断模块（spec §5）：调本地 Infinity 容器跑 cross-encoder NLI 小模型。

复用 embedding 服务的部署范式（Infinity 镜像 + 本地模型 + 只读挂载），
区别：NLI 是 sequence-classification 任务，走 /classify 端点（非 /embeddings）。

核心安全阀：服务不可用/超时/异常一律返回 "neutral"（降级为相似补充，走原合并逻辑），
绝不误判矛盾导致误删。失败必须向安全方向倾斜。
"""
import httpx

from app.core.config import get_settings


def judge_relation(premise: str, hypothesis: str) -> str:
    """判定两段文本关系：contradiction / entailment / neutral。

    语义层判断（两句话能否同时为真），用于矛盾覆盖决策。
    服务不可用/超时/异常时返回 "neutral"（降级，绝不误删）。
    """
    try:
        base_url = get_settings().nli_base_url
        resp = httpx.post(
            f"{base_url}/classify",
            json={"inputs": [[premise, hypothesis]]},
            timeout=2.0,
        )
        resp.raise_for_status()
        # Infinity 返回 [[{"label":"contradiction","score":0.9}, ...]]
        scores = resp.json()[0]
        top = max(scores, key=lambda x: x["score"])
        return top["label"]   # contradiction / entailment / neutral
    except Exception:
        return "neutral"      # 降级：绝不误判矛盾
```

- [ ] **Step 4: 运行 NLI 测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_nli.py -v`
Expected: 5 个测试全 PASS

- [ ] **Step 5: Commit**

```bash
cd apps/api
git add app/rag/nli.py tests/test_nli.py
git commit -m "feat(memory): NLI 矛盾判断模块 + 降级安全阀

- judge_relation: httpx 直连 Infinity /classify, 0 token
- 故障/超时/异常一律降级 neutral（走合并不删, 绝不误判矛盾）
- 结构镜像 reranker.py"
```

---

## Task 5: save_memory 升级为去重+矛盾判别

**Files:**
- Modify: `apps/api/app/ai/tools.py`
- Test: `apps/api/tests/test_save_memory_tool.py`

- [ ] **Step 1: 看现有 save_memory 工具完整逻辑**

Run: `cd apps/api && sed -n '57,113p' app/ai/tools.py`
理解：当前逻辑是 `find_similar_memory` → 有则 `update_memory` 合并，无则 `create_memory`。本次在「有相似」分支插入 NLI 判别。

- [ ] **Step 2: 写矛盾覆盖失败测试**

先看现有测试范式：

Run: `cd apps/api && head -60 tests/test_save_memory_tool.py`

在 `tests/test_save_memory_tool.py` 末尾追加：

```python
def test_save_memory_contradiction_replaces_old(db_session, registered_user, monkeypatch):
    """NLI 判矛盾 → 删旧写新（矛盾覆盖纠错）。"""
    from app.ai.tools import create_agent_tools
    from app.models import UserMemory
    import uuid as _uuid

    uid = _uuid.UUID(registered_user["id"])

    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [1.0] * 1024)
    monkeypatch.setattr(ms, "DEDUP_SIMILARITY", 0.0)  # 让 find_similar 命中

    # 预置一条旧记忆
    ms.create_memory(db_session, user_id=uid, content="偏好简洁风格")
    db_session.commit()

    # NLI 判矛盾
    monkeypatch.setattr("app.ai.tools.judge_relation", lambda p, h: "contradiction")

    tools = create_agent_tools(db_session, user_id=uid)
    save_mem = next(t for t in tools if t.name == "save_memory")
    result = save_mem.invoke({"content": "偏好详尽风格"})

    assert "替换" in result or "更新" in result
    contents = [m.content for m in db_session.query(UserMemory).filter_by(user_id=uid).all()]
    assert "偏好详尽风格" in contents
    assert "偏好简洁风格" not in contents  # 旧记忆被删


def test_save_memory_entailment_merges(db_session, registered_user, monkeypatch):
    """NLI 判蕴含 → 走原合并逻辑（v1.0 行为）。"""
    from app.ai.tools import create_agent_tools
    from app.models import UserMemory
    import uuid as _uuid

    uid = _uuid.UUID(registered_user["id"])
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [1.0] * 1024)
    monkeypatch.setattr(ms, "DEDUP_SIMILARITY", 0.0)

    ms.create_memory(db_session, user_id=uid, content="偏好简洁")
    db_session.commit()

    monkeypatch.setattr("app.ai.tools.judge_relation", lambda p, h: "entailment")

    tools = create_agent_tools(db_session, user_id=uid)
    save_mem = next(t for t in tools if t.name == "save_memory")
    save_mem.invoke({"content": "我喜欢简短"})

    contents = [m.content for m in db_session.query(UserMemory).filter_by(user_id=uid).all()]
    assert contents == ["我喜欢简短"]  # 合并更新，条数不变


def test_save_memory_nli_down_falls_back_to_merge(db_session, registered_user, monkeypatch):
    """NLI 故障 → 走合并不删（降级安全阀）。"""
    from app.ai.tools import create_agent_tools
    from app.models import UserMemory
    import uuid as _uuid

    uid = _uuid.UUID(registered_user["id"])
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [1.0] * 1024)
    monkeypatch.setattr(ms, "DEDUP_SIMILARITY", 0.0)

    ms.create_memory(db_session, user_id=uid, content="偏好简洁")
    db_session.commit()

    # NLI 抛异常 → judge_relation 内部降级 neutral
    monkeypatch.setattr("app.rag.nli.httpx.post", side_effect=Exception("down"))

    tools = create_agent_tools(db_session, user_id=uid)
    save_mem = next(t for t in tools if t.name == "save_memory")
    save_mem.invoke({"content": "偏好详尽"})

    contents = [m.content for m in db_session.query(UserMemory).filter_by(user_id=uid).all()]
    assert len(contents) == 1  # 合并未删
```

- [ ] **Step 3: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_save_memory_tool.py::test_save_memory_contradiction_replaces_old tests/test_save_memory_tool.py::test_save_memory_entailment_merges tests/test_save_memory_tool.py::test_save_memory_nli_down_falls_back_to_merge -v`
Expected: FAIL（当前无矛盾判别，"偏好简洁风格"还在）

- [ ] **Step 4: 升级 save_memory 工具**

修改 `apps/api/app/ai/tools.py` 的 `save_memory` 函数。先在文件顶部加 import（在现有 import 之后）：

```python
from app.rag.nli import judge_relation
```

然后修改 `save_memory` 内部的 `try` 块。**定位**现有的这段（约 96-108 行）：

```python
        try:
            # 去重：查找高度相似的已有记忆
            similar = find_similar_memory(db, user_id=user_id, content=content)
            if similar is not None:
                # 合并：相似度 ≥ 阈值，更新已有记忆
                update_memory(db, memory_id=similar.id, user_id=user_id, content=content)
                db.commit()
                return f"已合并更新已有记忆（原：「{similar.content[:50]}...」）"

            create_memory(db, user_id=user_id, content=content, source=source)
            db.commit()
            return "已保存"
        except Exception:
            db.rollback()
            return "未保存：写入失败，请稍后重试"
```

替换为（注意 import 区也需补 `delete_memory`）：

```python
        try:
            # 去重：查找高度相似的已有记忆
            similar = find_similar_memory(db, user_id=user_id, content=content)
            if similar is not None:
                # 【v1.1】矛盾判别：NLI 判断新旧是否冲突
                relation = judge_relation(content, similar.content)
                if relation == "contradiction":
                    # 矛盾：用户认知更新，新覆盖旧（全自动纠错）
                    delete_memory(db, memory_id=similar.id, user_id=user_id)
                    create_memory(db, user_id=user_id, content=content, source=source)
                    db.commit()
                    return "已更新（检测到与旧记忆冲突，已替换）"
                # entailment / neutral / 服务降级：走原合并逻辑
                update_memory(db, memory_id=similar.id, user_id=user_id, content=content)
                db.commit()
                return f"已合并更新已有记忆（原：「{similar.content[:50]}...」）"

            create_memory(db, user_id=user_id, content=content, source=source)
            db.commit()
            return "已保存"
        except Exception:
            db.rollback()
            return "未保存：写入失败，请稍后重试"
```

同时修改 `save_memory` 函数内的 import 语句（约 82-85 行），把 `delete_memory` 加进去：

```python
        from app.models.user_memory import SOURCE_AGENT, SOURCE_PROFILE
        from app.services.memory_service import (
            create_memory, delete_memory, find_similar_memory, update_memory,
        )
```

- [ ] **Step 5: 运行矛盾覆盖测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_save_memory_tool.py::test_save_memory_contradiction_replaces_old tests/test_save_memory_tool.py::test_save_memory_entailment_merges tests/test_save_memory_tool.py::test_save_memory_nli_down_falls_back_to_merge -v`
Expected: PASS

- [ ] **Step 6: 运行全量 save_memory + agent 测试确认无回归**

Run: `cd apps/api && uv run pytest tests/test_save_memory_tool.py tests/test_agent_factory.py tests/test_rag_tool.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
cd apps/api
git add app/ai/tools.py tests/test_save_memory_tool.py
git commit -m "feat(memory): save_memory 升级为去重+矛盾判别

- 有相似记忆时调 judge_relation(NLI):
  contradiction → 删旧写新(矛盾覆盖纠错)
  entailment/neutral/降级 → 原合并逻辑
- NLI 故障经 judge_relation 降级 neutral, 绝不误删"
```

---

## Task 6: docker-compose NLI 服务块 + 收尾

**Files:**
- Modify: `docker-compose.yml`
- Modify: `G:\03-Personal-Projects\TianGong\AGENTS.md`

- [ ] **Step 1: 在 docker-compose.yml 加 NLI 服务**

定位 `docker-compose.yml` 的 embedding 服务块（约 55-102 行），在其后追加 NLI 服务块：

```yaml
  # NLI 矛盾判断小模型（复用 Infinity 镜像，换模型目录与端口）。
  # 判断新旧记忆是否矛盾，供 save_memory 矛盾覆盖用（spec §5）。
  # 模型从本地目录加载（避免联网下载 ~700MB）：./models/nli-deberta-v3-base
  # 模型需自行下载：huggingface-cli download cross-encoder/nli-deberta-v3-base
  # 国内有网速问题可用镜像：HF_ENDPOINT=https://hf-mirror.com huggingface-cli download ...
  # NLI 是软依赖：服务挂掉时 judge_relation 降级 neutral 走合并不删，api 不 depends_on 它。
  nli:
    image: michaelf34/infinity:latest-cpu
    container_name: tiangong-nli
    command: >
      v2 --engine torch --model-id /data/models/nli-deberta-v3-base --port 7998
    ports:
      - "7998:7998"
    volumes:
      - ${NLI_MODEL_DIR:-./models/nli-deberta-v3-base}:/data/models/nli-deberta-v3-base:ro
      - nlidata:/data/.cache
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7998/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    restart: unless-stopped
```

- [ ] **Step 2: 在 volumes 区注册 nlidata**

定位 `docker-compose.yml` 末尾的 `volumes:` 区（约 183 行），追加 `nlidata:`：

```yaml
volumes:
  # ... 现有 ...
  nlidata:
```

- [ ] **Step 3: 在 api 服务注入 NLI_BASE_URL**

定位 `docker-compose.yml` 的 `api` 服务 `environment:` 区（参照现有 `EMBEDDING_BASE_URL`，约 135-137 行），追加：

```yaml
      EMBEDDING_BASE_URL: http://embedding:7997
      EMBEDDING_MODEL: BAAI/bge-m3
      EMBEDDING_API_KEY: ${EMBEDDING_API_KEY:-}
      NLI_BASE_URL: http://nli:7998    # 【v1.1】NLI 矛盾判断服务
```

- [ ] **Step 4: AGENTS.md 补一条记忆模块约定**

修改 `AGENTS.md` 的「关键约定」区，在最后追加：

```markdown
- **记忆热度/纠错全自动（v1.1）**：`user_memories` 表的 `hit_count`/`last_hit_at` 由系统自动维护——检索命中自动累加、超 200 条自动淘汰（30 天半衰期热度排序）、新旧矛盾自动 NLI 覆盖。无用户反馈机制，不暴露热度/复核端点。NLI 走本地 Infinity 容器（端口 7998，`cross-encoder/nli-deberta-v3-base`），是软依赖——故障时降级合并不删。
```

- [ ] **Step 5: 运行全量后端测试做最终回归**

Run: `cd apps/api && uv run pytest -x -q`
Expected: 全部 PASS（-x 首个失败即停，便于定位）

- [ ] **Step 6: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add docker-compose.yml AGENTS.md
git commit -m "feat(memory): docker-compose NLI 服务块 + AGENTS.md 约定

- 新增 nli 服务(Infinity 跑 cross-encoder/nli-deberta-v3-base, 端口7998)
- api 注入 NLI_BASE_URL, nli 为软依赖不 depends_on
- AGENTS.md 记录记忆热度/纠错全自动约定"
```

---

## 完成验证清单（所有 Task 完成后）

- [ ] `cd apps/api && uv run pytest -q` 全绿
- [ ] `cd apps/api && uv run alembic upgrade head` 在 PG 上成功（手验）
- [ ] `docker compose up -d nli` 启动，`curl http://localhost:7998/health` 返回 OK（需先下载模型到 `models/nli-deberta-v3-base/`）
- [ ] 手验矛盾覆盖：存「偏好简洁」→ 存「偏好详尽」→ 前者被删
- [ ] 手验淘汰：存满 201 条 → 最冷一条被删
