# 用户长期记忆 — 热度淘汰与自动纠错设计

> 版本：v1.1 · 日期：2026-07-30 · 状态：草案待评审
> 前置依赖：[2026-07-28-user-memory-design.md](2026-07-28-user-memory-design.md) v1.0（记忆模块已落地）
> 范围：仅在 `apps/api`（后端）实现，新增 1 个 Infinity 容器（NLI 小模型），前端零改动
> 作者：tl.m + ZCode

---

## 0. 背景与目标

### 0.1 要解决的问题

前置 spec（v1.0）的 **§12 已知限制第 4 条**明确记录：

> 无记忆容量上限：v1 不限制单用户记忆条数。若膨胀可加软上限 + 老旧记忆淘汰。

v1.0 落地后，这个限制暴露出两个真实风险：
1. **无上限增长**：`save_memory` 工具若触发频繁（去重阈值 0.85 挡不住近似记忆），用户记忆库无限膨胀，HNSW 索引和 embedding 存储成本线性上升，且 `list_memories` 的 `limit=200` 会让超出部分的旧记忆「存而不可见」，用户无法管理。
2. **错误记忆无法自动纠正**：用户认知会变化（如「偏好简洁」→「偏好详尽」），但旧记忆不会自动失效。若旧记忆被反复检索命中，热度反而最高，永远被保留——错误信息持续污染 prompt。

### 0.2 设计目标（已与用户确认）

| 目标 | 衡量标准 |
|---|---|
| 记忆总量可控 | 单用户记忆数有硬上限，永不超限 |
| 保留高价值记忆 | 淘汰时优先保留高频使用、近期命中的记忆 |
| 全自动纠错 | 检测到用户认知更新（新旧矛盾）时，自动用新记忆覆盖旧记忆 |
| **零用户操作** | 不依赖用户反馈/点按，热度采集与纠错全程系统自动 |
| 省 token | 纠错判断走本地小模型，每次 0 token，不进 agent 主链路 |

### 0.3 关键决策摘要

| 决策点 | 选择 | 理由 |
|---|---|---|
| 上限 | **200 条/用户** | 对齐现有 `list_memories` 默认 limit，列表能展示全部不留黑洞 |
| 淘汰触发时机 | **写入时即时淘汰（cap-on-write）** | 复用 `save_memory` 既有事务边界，零额外调度成本 |
| 热度信号 | **纯自动：命中计数 + 时间衰减** | 全自动，无需用户反馈；衰减让老旧记忆自然让位 |
| 纠错机制 | **矛盾覆盖**（新旧语义相似但内容冲突 → 新覆盖旧） | 全自动纠错的唯一不引入后台任务的方案 |
| 矛盾判断 | **本地 NLI 小模型**（`cross-encoder/nli-deberta-v3-base`） | 每次 0 token，CPU 毫秒级，复用 Infinity 容器基础设施 |
| 用户反馈机制 | **不做**（砍掉） | 用户明确要求全自动；反馈表/复核表/状态机全部不引入 |
| 前端改动 | **零** | 全自动对用户透明，记忆页保持现状 |

---

## 1. 整体架构与数据流

```
┌──────────────────────────────────────────────────────────────────┐
│  写路径（save_memory 工具，agent loop 内）                        │
│                                                                  │
│  content ──► find_similar_memory(content)                        │
│                 │                                                │
│       ┌─────────┴──────────┐                                     │
│       ▼                    ▼                                     │
│   有相似记忆           无相似记忆                                 │
│       │                    │                                     │
│   judge_relation()      create_memory()                          │
│   (NLI 小模型)             │                                     │
│       │                    ▼                                     │
│   ┌───┴───┐            _enforce_capacity()  ◄── 写入后即时淘汰    │
│   ▼       ▼            count > 200 ?                             │
│ 矛盾    补充/相似        ├─ yes → 删最冷一条（按 hit_count+       │
│ 删旧     合并更新        │         last_hit_at 排序，豁免 7 天内） │
│ 写新                   └─ no  → 直接返回                          │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  读路径（search_memories，build_system_prompt 调用）              │
│                                                                  │
│  query ──► 阶段1: 向量召回 Top-(K×3)  (cosine_distance, HNSW)    │
│            阶段2: Python 重排 score=(hit_count+1)×decay(Δt)      │
│                   取 Top-K                                        │
│            阶段3: 批量 hit_count+=1, last_hit_at=now （尽力而为） │
└──────────────────────────────────────────────────────────────────┘
```

### 两条路径对照（相对 v1.0 的增量）

| | v1.0 行为 | v1.1 增量 |
|---|---|---|
| 写路径 | 仅去重（相似→合并） | 去重 + **矛盾判别**（NLI）+ **写入后容量淘汰** |
| 读路径 | 纯向量检索 Top-K | 向量召回 + **热度重排** + **命中计数回写** |

---

## 2. 数据模型变更

### 2.1 `user_memories` 表新增 2 个字段

文件：`apps/api/app/models/user_memory.py`（修改，非新建）

```python
from sqlalchemy import DateTime, Integer
# ... 现有 import ...

class UserMemory(Base, IdMixin, TimestampMixin):
    # ... 现有字段（user_id / content / embedding / source）不变 ...

    # 【v1.1 新增】热度字段
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_hit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

| 字段 | 类型 | 默认 | 用途 |
|---|---|---|---|
| `hit_count` | `Integer NOT NULL` | `0` | 被 `search_memories` 命中的累计次数 |
| `last_hit_at` | `DateTime(timezone=True) NULLABLE` | `NULL` | 最近一次命中时间；`NULL` 表示从未被命中（即刚创建） |

**为什么不存缓存 `score` 列**：热度分数 = `(hit_count+1) × decay(now - last_hit_at)`，衰减依赖**当前时间**，缓存会随时间失效。检索时实时计算即可，避免维护一个会失效的缓存值。

**不新增表**：v1.0 计划过的 `memory_review_queue`、`status` 状态机、所有反馈字段——**全部不引入**（见 §0.3 决策，砍掉用户反馈机制）。

### 2.2 迁移

文件：`apps/api/alembic/versions/g7h8i9j0k1l2_add_memory_hot_fields.py`（新建，接在当前 head `9a3f7c2e1b4d` 之后）

```python
"""add hit_count/last_hit_at to user_memories for hot eviction

Revision ID: g7h8i9j0k1l2
Revises: <当前 head>  # writing-plans 时用 `alembic heads` 确认
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "9a3f7c2e1b4d"  # 当前 head（2026-07-30 确认）
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
    # 可选：为淘汰查询（按 hit_count+last_hit_at 排序）建轻量索引。
    # 200 条规模下顺序扫描足够，暂不加，待真实数据验证后再补。


def downgrade() -> None:
    op.drop_column("user_memories", "last_hit_at")
    op.drop_column("user_memories", "hit_count")
```

**SQLite 测试库兼容**：`Integer` / `DateTime` 都是标量类型，SQLite 原生支持，无 `JSONB().with_variant` 问题（参照 GOTCHAS G2，那仅针对 JSONB）。`server_default="0"` 在 SQLite 下也正常工作。

---

## 3. 热度与淘汰算法（核心）

文件：`apps/api/app/services/memory_service.py`（修改）

### 3.1 热度公式

```
score(memory, now) = (hit_count + 1) × decay(now - last_hit_at)
```

**`(hit_count + 1)` 加 1 的两个作用**：
- **冷启动公平**：新记忆 `hit_count=0`，加 1 后分数 > 0，不因「从未被命中」天生垫底被误杀。
- **避免零乘**：纯 `hit_count` 在新记忆上为 0，任何衰减乘 0 都归零，失去区分度。

**`decay(Δt)` 指数衰减，半衰期 30 天**：

```python
from datetime import datetime, timezone

HALF_LIFE_DAYS = settings.MEMORY_HALF_LIFE_DAYS  # 默认 30

def _decay(delta_seconds: float) -> float:
    """指数衰减。Δt=0 返回 1.0；半衰期后腰斩到 0.5。"""
    days = delta_seconds / 86400
    return 0.5 ** (days / HALF_LIFE_DAYS)
```

| 时间未命中 | decay | 直觉 |
|---|---|---|
| 0 天（刚命中 / 新建 NULL） | 1.0 | 满分 |
| 30 天 | 0.5 | 腰斩 |
| 60 天 | 0.25 | |
| 90 天 | 0.125 | 接近归零 |

**`last_hit_at IS NULL`（新记忆）处理**：`Δt = 0` → `decay = 1.0`，新记忆得满分（不被淘汰）。

### 3.2 淘汰算法（cap-on-write）

新增函数 `_enforce_capacity`，在 `create_memory` 写入后调用：

```python
from sqlalchemy import func, select

MEMORY_LIMIT = settings.MEMORY_LIMIT       # 默认 200
GRACE_DAYS = settings.MEMORY_GRACE_DAYS    # 默认 7


def create_memory(db, *, user_id, content, source=SOURCE_AGENT):
    # ... 现有写入逻辑（含 _try_embed、db.flush）不变 ...
    db.flush()
    _enforce_capacity(db, user_id)   # 【新增】写入后即时淘汰
    return memory


def _enforce_capacity(db, user_id):
    """写入后检查容量，超限则淘汰最冷的一条。

    豁免：7 天内新记忆（last_hit_at IS NULL 或距今 < 7 天）不参与淘汰，
    防止刚写入即被删。
    """
    count = db.scalar(
        select(func.count()).select_from(UserMemory)
        .where(UserMemory.user_id == user_id)
    )
    if count <= MEMORY_LIMIT:
        return

    grace_cutoff = datetime.now(timezone.utc) - timedelta(days=GRACE_DAYS)
    # 双列近似排序：hit_count 最少 + 最久未触达 = 最冷。
    # last_hit_at ASC NULLS FIRST 让 NULL（从未命中）排最前，
    # 但 NULL 已被 grace 豁免排除，故实际只排序有 last_hit_at 的旧记忆。
    coldest = db.scalars(
        select(UserMemory)
        .where(
            (UserMemory.user_id == user_id)
            & (
                (UserMemory.last_hit_at.isnot(None))
                & (UserMemory.last_hit_at < grace_cutoff)
            )
        )
        .order_by(UserMemory.hit_count.asc(), UserMemory.last_hit_at.asc())
        .limit(1)
    ).first()

    if coldest is not None:
        db.delete(coldest)
        db.flush()
    # 若无可淘汰的（全部在豁免期内），本次超限暂不处理，
    # 等豁免期过后自然进入淘汰候选。记录为已知限制（§7）。
```

**为什么用双列排序而非实时算衰减**：衰减依赖 `now`，HNSW 已占向量排序，无法在一条 ORDER BY 里混入时间标量表达式。双列排序 `hit_count ASC, last_hit_at ASC` 的单调性与 `(hit_count+1) × decay` 一致——热度最低的就是命中数最少 + 最久没碰的。语义等价，且不需要把 200 条全拉进内存算。

**只删一条**：每次写入最多 +1，删除 1 条即恢复上限，不做批量删除。

### 3.3 命中计数回写（读路径）

`search_memories` 返回 Top-K 后，批量更新这些记忆的热度：

```python
from sqlalchemy import update

def search_memories(db, *, user_id, query, top_k=DEFAULT_TOP_K):
    # ... 阶段1 向量召回 + 阶段2 Python 重排（见 §4）得到 results ...

    # 【新增】阶段3：命中计数回写（尽力而为）
    if results:
        _bump_hit_counts(db, [r.id for r in results])
    return results


def _bump_hit_counts(db, memory_ids):
    """批量更新命中计数。失败不阻断检索（结果已算出，回写失败只是热度不准）。"""
    try:
        now = datetime.now(timezone.utc)
        db.execute(
            update(UserMemory)
            .where(UserMemory.id.in_(memory_ids))
            .values(hit_count=UserMemory.hit_count + 1, last_hit_at=now)
        )
        db.flush()
    except Exception:
        db.rollback()  # 防 PG 事务中毒化后续查询（沿用 context_assembler 既有模式）
```

**关键点**：
- **单条 SQL 批量化**：一条 UPDATE 更新全部 Top-K，不是循环 N 次（避免写放大）。
- **尽力而为**：失败即 rollback，不影响检索结果（结果已算出，回写失败只是热度不准，可接受）。
- **不 commit**：在主请求事务内，commit 由路由层负责（与现有 create/update 一致）。

---

## 4. 检索路径：两阶段召回重排（修正 v1.0 实现契约）

文件：`apps/api/app/services/memory_service.py`（修改 `search_memories`）

### 4.1 为什么必须两阶段

pgvector 的 HNSW 索引按 `cosine_distance` 排序，**无法在一条 ORDER BY 里混入依赖当前时间的标量热度分数**。故检索分两阶段：向量召回放大候选集，Python 层用热度公式重排。

### 4.2 实现要点

```python
def search_memories(db, *, user_id, query, top_k=DEFAULT_TOP_K):
    # ... query 向量化（_try_embed，失败返回空，同 v1.0）...
    # ... HNSW ef_search 设置（同 v1.0）...

    # 阶段1：向量召回，放大候选集到 top_k × 3（保重排前不被向量距离截断高热度冷向量记忆）
    recall_k = max(top_k * 3, 15)
    stmt = (
        select(UserMemory, UserMemory.embedding.cosine_distance(query_vec).label("distance"))
        .where((UserMemory.user_id == user_id) & (UserMemory.embedding.isnot(None)))
        .order_by("distance")
        .limit(recall_k)
    )
    rows = db.execute(stmt).all()

    # v1.0 的相似度阈值过滤 + NaN/范围防御（保留不变）
    candidates = []
    for mem, distance in rows:
        score = 1.0 - distance
        if distance != distance:  # NaN 防御
            continue
        if distance < 0 or distance > 2:
            continue
        if score < SIMILARITY_THRESHOLD:
            continue
        candidates.append((mem, score))

    # 阶段2：Python 热度重排（用元组携带热度分，不污染 ORM 实例）
    now = datetime.now(timezone.utc)
    ranked = [(mem, vec_score, _compute_hot_score(mem, now)) for mem, vec_score in candidates]
    ranked.sort(key=lambda x: x[2], reverse=True)  # 按热度分降序

    results = [
        MemorySearchResult(content=mem.content, score=vec_score, id=mem.id)
        for mem, vec_score, _hot in ranked[:top_k]
    ]

    # 阶段3：命中计数回写（§3.3）
    if results:
        _bump_hit_counts(db, [r.id for r in results])
    return results


def _compute_hot_score(mem, now):
    """实时计算热度分。last_hit_at IS NULL（新记忆）→ Δt=0 → decay=1.0。"""
    hit = mem.hit_count or 0
    last = mem.last_hit_at or now  # NULL 视为「刚命中」，得满分衰减
    delta = (now - last).total_seconds()
    return (hit + 1) * _decay(delta)
```

---

## 5. 全自动矛盾纠错（NLI 小模型）

文件：`apps/api/app/rag/nli.py`（新建）+ `apps/api/app/ai/tools.py`（修改 `save_memory`）

### 5.1 触发时机：升级写入路径的去重逻辑

v1.0 的 `save_memory` 仅有「去重→合并」。v1.1 升级为「去重→矛盾判别→覆盖/合并」：

```python
# apps/api/app/ai/tools.py（save_memory 工具内部）
from app.services.memory_service import (
    create_memory, find_similar_memory, update_memory, delete_memory,
)
from app.rag.nli import judge_relation

content = (content or "").strip()
if not content:
    return "未保存：内容为空"

source = SOURCE_PROFILE if memory_type == "profile" else SOURCE_AGENT

try:
    similar = find_similar_memory(db, user_id=user_id, content=content)
    if similar is not None:
        relation = judge_relation(content, similar.content)  # 【新增】NLI 判定
        if relation == "contradiction":
            # 矛盾：用户认知更新，新覆盖旧（全自动纠错）
            delete_memory(db, memory_id=similar.id, user_id=user_id)
            create_memory(db, user_id=user_id, content=content, source=source)
            db.commit()
            return "已更新（检测到与旧记忆冲突，已替换）"
        else:  # entailment / neutral / 服务降级
            # 补充/相似：原 v1.0 合并逻辑
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

### 5.2 NLI 调用模块

文件：`apps/api/app/rag/nli.py`（新建，结构镜像 `reranker.py`）

```python
"""NLI 矛盾判断模块：调本地 Infinity 容器跑 cross-encoder NLI 小模型。

复用 embedding 服务的部署范式（Infinity 镜像 + 本地模型目录 + 只读挂载），
区别在于 NLI 是 sequence-classification 任务，走 /classify 端点（非 /embeddings）。
"""
import httpx

from app.core.config import get_settings

_settings = get_settings()


def judge_relation(premise: str, hypothesis: str) -> str:
    """判定两段文本关系：contradiction / entailment / neutral。

    语义层判断（两句话能否同时为真），用于矛盾覆盖决策。

    服务不可用/超时/异常时返回 "neutral"（降级为相似补充，走原合并逻辑，绝不误删）。
    这是核心安全阀——失败必须向安全方向倾斜。
    """
    try:
        resp = httpx.post(
            f"{_settings.NLI_BASE_URL}/classify",
            json={"inputs": [[premise, hypothesis]]},
            timeout=2.0,
        )
        resp.raise_for_status()
        # Infinity 返回 [[{"label":"contradiction","score":0.9}, ...]]
        scores = resp.json()[0]
        top = max(scores, key=lambda x: x["score"])
        return top["label"]   # contradiction / entailment / neutral
    except Exception:
        return "neutral"      # 降级：绝不误判矛盾导致误删
```

**关键安全约束**：
- 只在 NLI **明确返回 contradiction** 时删旧。
- 只删 `find_similar_memory` 命中的那一条（阈值 0.85 的近邻），不做范围删除。
- NLI 任何异常一律 `neutral`，绝不误删。

### 5.3 NLI 语义边界（NLI 能识别什么）

| 关系 | 示例 | 处理 |
|---|---|---|
| **contradiction（矛盾）** | 「偏好简洁风格」vs「偏好详尽风格」 | 删旧写新 |
| **contradiction（矛盾）** | 「我做新能源电池」vs「我做半导体芯片」 | 删旧写新 |
| **neutral（中性补充）** | 「我做新能源」vs「我用 Python」 | 各自保留（不进相似分支） |
| **entailment（蕴含/重述）** | 「偏好简洁」vs「我喜欢简短」 | 合并更新 |

⚠️ **中文 NLI 精度风险**：`cross-encoder/nli-deberta-v3-base` 主要英文/多语言泛化，中文判断可能不准。**v1 策略**：跑通流程优先，中文判断不准时**回退纯合并不删**（即返回 neutral）。中文 NLI 模型升级列为 v2 优化项（§7）。先保正确性（不误删），再追精度。

---

## 6. 配置与部署变更

### 6.1 新增配置项（4 个 env）

文件：`apps/api/app/core/config.py`（修改 Settings）

```python
class Settings(BaseSettings):
    # ... 现有字段 ...

    # 【v1.1 新增】记忆热度/淘汰配置
    MEMORY_LIMIT: int = 200                 # 单用户记忆上限
    MEMORY_HALF_LIFE_DAYS: int = 30         # 热度衰减半衰期
    MEMORY_GRACE_DAYS: int = 7              # 新记忆豁免期
    NLI_BASE_URL: str = "http://localhost:7998"  # NLI 服务地址
```

默认值即 §0.3 决策值，全部可配。

### 6.2 docker-compose.yml 新增 NLI 服务

文件：`docker-compose.yml`（修改，复刻 embedding 服务块）

```yaml
  # NLI 矛盾判断小模型（复用 Infinity 镜像，换模型目录与端口）
  # 模型从本地目录加载（避免联网下载）：./models/nli-deberta-v3-base
  # 模型需自行下载：huggingface-cli download cross-encoder/nli-deberta-v3-base
  # 国内有网速问题可用镜像：HF_ENDPOINT=https://hf-mirror.com huggingface-cli download ...
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

volumes:
  # ... 现有 ...
  nlidata:
```

**模型下载**：`cross-encoder/nli-deberta-v3-base`（约 700MB），落位 `models/nli-deberta-v3-base/`（已 gitignore）。核心文件：`pytorch_model.bin`/`model.safetensors`、`config.json`、`tokenizer.json`、`special_tokens_map.json`。

**端口规划**：7997（embedding，现有）/ **7998（NLI，新增）**。未来 reranker 本地化用 7999。

**NLI 服务对 api 的影响**：NLI 是**软依赖**——服务挂掉时 `judge_relation` 降级为 neutral，走合并不删，记忆功能正常运行。故 api 服务**不**加 `depends_on: nli: condition: service_healthy`（与 embedding 不同，embedding 是硬依赖）。

**Python 侧零新依赖**：httpx 已有（reranker 在用），不引入 torch/sentence-transformers。

### 6.3 api 服务注入 env

在 `docker-compose.yml` 的 `api` 服务环境变量区（参照现有 `EMBEDDING_BASE_URL`，compose 行 135-137 附近）追加：

```yaml
  api:
    environment:
      # ... 现有 ...
      NLI_BASE_URL: http://nli:7998
      # MEMORY_LIMIT / MEMORY_HALF_LIFE_DAYS / MEMORY_GRACE_DAYS 用默认值即可，不必显式注入
```

---

## 7. 已知限制与边界 case

| # | 限制/边界 | 处理 |
|---|---|---|
| 1 | **全部记忆在豁免期内时超限** | `_enforce_capacity` 找不到可淘汰候选，本次超限暂不处理，等豁免期过后自然进入候选。MVP 规模（200 条）下概率极低，可接受。 |
| 2 | **NLI 服务故障** | `judge_relation` 一律降级 neutral → 走合并，**绝不误删**（§5.2 安全阀） |
| 3 | **中文 NLI 精度** | v1 用 `nli-deberta-v3-base` 跑通；中文不准时回退纯合并不删；升级留 v2（§5.3） |
| 4 | **命中计数写放大** | Top-K 批量 UPDATE（一条 SQL），尽力而为，失败 rollback 不阻断检索（§3.3） |
| 5 | **SQLite 测试库** | 标量列（Integer/DateTime）SQLite 原生支持；`_enforce_capacity` 双列排序在 SQLite 正常；NLI 调用用 mock |
| 6 | **两个 Infinity 容器内存** | embedding（2.27GB 模型）+ nli（0.4GB 模型）常驻，nli 远小于 bge-m3，可接受；部署时评估内存 |
| 7 | **衰减不区分 source** | profile 记忆（画像）与 agent 记忆走同一套热度/淘汰。profile 通常量少（≤几条），不会触发淘汰，故无需特殊豁免。若后续 profile 膨胀再加豁免。 |

---

## 8. 测试策略

遵循项目 TDD 约定（参考 v1.0 的 `test_memory_service.py` 范式）。

### 8.1 后端单元测试

文件：`apps/api/tests/test_memory_service.py`（修改，追加热度/淘汰用例）

- `test_create_memory_enforces_capacity` — 写入使总数超 200 时触发淘汰
- `test_enforce_capacity_keeps_hot_memory` — 高 hit_count 记忆不被淘汰
- `test_enforce_capacity_evicts_coldest` — hit_count 最低 + 最久未命中的被淘汰
- `test_enforce_capacity_grace_period` — 7 天内新记忆豁免，即便最冷也不删
- `test_enforce_capacity_under_limit_noop` — 未超限时不删任何记忆
- `test_compute_hot_score_new_memory` — 新记忆（hit_count=0, last_hit_at=NULL）得满分衰减
- `test_compute_hot_score_decay` — 30 天未命中分数腰斩
- `test_search_memories_reranks_by_hotness` — 热度高的排在向量距离更近但热度低的之前
- `test_bump_hit_counts_failure_does_not_block_search` — 回写失败不阻断检索结果返回

文件：`apps/api/tests/test_nli.py`（新建）
- `test_judge_relation_contradiction` — mock NLI 返回 contradiction，正确透传
- `test_judge_relation_service_down_returns_neutral` — 服务挂掉时降级 neutral（核心安全阀）
- `test_judge_relation_timeout_returns_neutral` — 超时降级 neutral

文件：`apps/api/tests/test_save_memory_tool.py`（修改，追加矛盾覆盖用例）
- `test_save_memory_contradiction_replaces_old` — NLI 判矛盾 → 删旧写新
- `test_save_memory_entailment_merges` — NLI 判蕴含 → 合并（v1.0 行为）
- `test_save_memory_nli_down_falls_back_to_merge` — NLI 故障 → 走合并不删

### 8.2 数据库测试约定（GOTCHAS G2）

- SQLite 内存库，标量列原生支持（无 JSONB variant 问题）。
- HNSW 索引 SQLite 不生效，向量检索 mock `embed_text` 返回固定向量，断言 service 层逻辑。
- NLI 调用全部 mock `judge_relation`，不依赖真实容器。
- 真实 PG + pgvector + Infinity NLI 行为靠手动验证。

### 8.3 前端测试

**无**。前端零改动（§0.3 决策），记忆页保持现状，无需新增测试。

---

## 9. 实施顺序（供 writing-plans 参考）

建议分 4 个 Phase，每个 Phase 可独立验证：

1. **Phase 1 数据层**：`UserMemory` 加 2 字段 + 迁移 + 配置项。验收：`alembic upgrade head` 成功，模型可 import，新字段可读写。
2. **Phase 2 淘汰算法**：`memory_service.py` 加 `_enforce_capacity` + `_compute_hot_score` + `_decay` + `create_memory` 接入淘汰。验收：单测全绿（容量/豁免/保留高热）。
3. **Phase 3 读路径重排**：`search_memories` 两阶段召回重排 + `_bump_hit_counts`。验收：单测全绿（重排/回写降级）。
4. **Phase 4 NLI 纠错 + 部署**：`app/rag/nli.py` + `save_memory` 升级 + docker-compose NLI 服务块 + 模型下载。验收：NLI 单测全绿（降级安全阀）+ 矛盾覆盖集成测试 + 手动验证容器健康。

---

## 附录 A：关键文件清单

| 类型 | 路径 | 操作 |
|---|---|---|
| 修改模型 | `apps/api/app/models/user_memory.py` | 加 hit_count / last_hit_at |
| 新建迁移 | `apps/api/alembic/versions/g7h8i9j0k1l2_add_memory_hot_fields.py` | 加 2 列 |
| 修改 service | `apps/api/app/services/memory_service.py` | 淘汰算法 + 热度公式 + 检索重排 + 命中回写 |
| 新建 NLI 模块 | `apps/api/app/rag/nli.py` | 矛盾判断（httpx 直连 Infinity） |
| 修改工具 | `apps/api/app/ai/tools.py` | save_memory 升级为去重+矛盾判别 |
| 修改配置 | `apps/api/app/core/config.py` | 加 4 个 env |
| 修改部署 | `docker-compose.yml` | 加 NLI 服务块 + api 注入 NLI_BASE_URL |
| 测试 | `tests/test_memory_service.py`（追加）, `test_nli.py`（新）, `test_save_memory_tool.py`（追加） | TDD |
| 前端 | — | 零改动 |

---

## 附录 B：决策记录

**Q1: 为什么砍掉用户反馈机制？**
用户明确要求「全自动」，不希望用户点按。用户反馈原承担的「纠错」职责由「矛盾覆盖 + NLI」接替——系统自动检测新旧矛盾并覆盖，无需人工。砍掉反馈后，`feedback_score` / `feedback_count` / `status` / `memory_review_queue` 全部不引入，设计大幅简化。

**Q2: 为什么用本地 NLI 小模型而非在线 API？**
矛盾判断是轻量 NLI 任务，不需通用对话能力。本地 `cross-encoder/nli-deberta-v3-base`（0.4B）CPU 毫秒级，**每次 0 token**，复用项目既有 Infinity 容器基础设施（embedding 已验证可行）。在线 API（GLM-4-Flash 等）虽便宜但走网络、占配额，与「省」的初衷相悖。

**Q3: 为什么矛盾判断不进 agent 主链路？**
矛盾判断是写入路径（save_memory）的旁路调用，对 agent loop 无感。agent 只管调 save_memory，内部去重/矛盾/淘汰全自动。这避免给主链路增加上下文和 token 开销。

**Q4: 为什么热度用双列排序而非实时算衰减排序？**
衰减依赖当前时间，HNSW 已占向量排序，无法在一条 SQL ORDER BY 混入时间标量。双列 `hit_count ASC, last_hit_at ASC` 的单调性与 `(hit_count+1)×decay` 一致，语义等价且不需全量拉取内存。

**Q5: 为什么召回集放大到 top_k×3？**
两阶段检索中，若阶段1只召回 top_k，阶段2 热度重排可能把高热度但向量距离稍远的记忆在阶段1就截断掉。放大候选集保证高热度记忆进入重排，再由热度公式筛出最终 Top-K。
