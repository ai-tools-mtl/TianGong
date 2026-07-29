# 用户绑定的长期记忆（User Long-Term Memory）— 设计契约

> 版本：v1.0 · 日期：2026-07-28 · 状态：草案待评审
> 依赖：`d1h2n3s4w5i6`（HNSW 索引迁移）之后的迁移链
> 范围：仅在 `apps/api`（后端）+ `apps/web`（前端）实现，不引入新中间件依赖

---

## 0. 背景与决策摘要

天工 agent 当前只有「会话级短期记忆」（手搓：每次请求从 `messages` 表全量捞历史拼 prompt）和「项目级文档上下文」（`Section.summary` + 已写章节注入），**完全没有跨会话的长期记忆**。用户每次开新项目、新会话，之前表达过的偏好（如「偏好简洁风格」）、稳定事实（如「我在某公司做新能源电池」）、领域 know-how（如「权利要求从宽到窄」）都要重新交代一遍。

本设计为 agent 增加**用户绑定的长期记忆**，让 agent 跨项目、跨会话记住用户提供的稳定信息。

### 关键决策（已与用户确认）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 记忆范围 | **仅用户级**（跨项目稳定），不做项目级 | 项目内决策已有 `Section.summary` + 已写章节注入，避免职责重叠 |
| 记忆内容类型 | 用户偏好/习惯、稳定事实、领域 know-how | 三类都是「跨项目稳定」的用户特征 |
| 写入触发 | **Agent 自动判断**（LLM 在 loop 中自主决定是否调 `save_memory`） | 体验顺滑，用户无感 |
| 注入策略 | **纯检索式**（用当前 query 语义检索 Top-K 注入 system prompt） | token 可控，复用现有 pgvector + HNSW，不引入 `is_pinned` 复杂度 |
| 存储 | **PostgreSQL `user_memories` 表 + pgvector + HNSW** | 复用知识库成熟基础设施 |
| 可见性 | **用户可在前端管理**（查看/增/删/改） | 用户可控，记忆错误可纠正 |

### 顺带修复的基建问题

现有 `rag_search_tool(query, user_id, db_session)` 有个**设计缺陷**：`user_id` 和 `db_session` LLM 根本不会生成（LLM 不知道自己的 user_id），且当前没有任何注入机制（无 `RunnableConfig` 注入、无闭包绑定）。本设计引入「工具参数注入机制」（闭包工厂），同时让 `rag_search` 和新增的记忆工具受益。

---

## 1. 整体架构与数据流

```
┌─────────────────────────────────────────────────────────────┐
│  前端 /settings/memories (shadcn UI)                         │
│  列表 / 新增 / 编辑 / 删除 记忆                                │
└──────────────┬──────────────────────────────────────────────┘
               │ REST CRUD
┌──────────────▼──────────────────────────────────────────────┐
│  后端 API  GET/POST/PATCH/DELETE /api/memories               │
│  全部绑定 current_user.id（严格隔离）                          │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│  Service 层  memory_service.py                              │
│  - CRUD + 自动 embedding 生成（写入时同步生成）               │
│  - search(query, user_id, top_k) → pgvector 检索             │
└──────────────┬──────────────────────────────────────────────┘
               │                          ▲
   【读路径】   │                          │ 【写路径】
               │                          │
┌──────────────▼──────────────────┐  ┌─────┴────────────────────┐
│ build_system_prompt             │  │ save_memory @tool        │
│ (注入阶段)                      │  │ (agent loop 内,LLM 自主)  │
│ 用当前 query 检索 Top-K 记忆     │  │ 内部做去重 + 冲突合并     │
│ 注入 system prompt              │  │ (embedding 相似度阈值)    │
└─────────────────────────────────┘  └──────────────────────────┘
               ▲
               │
┌──────────────┴──────────────────────────────────────────────┐
│  user_memories 表  (PostgreSQL + pgvector + HNSW)           │
│  id | user_id | content | embedding | source | timestamps   │
└─────────────────────────────────────────────────────────────┘
```

### 两条路径对照

| | 读路径（回忆） | 写路径（记忆） |
|---|---|---|
| 触发 | 主动，每次 chat/generate 都执行 | 被动，LLM 在 loop 中自主决定 |
| 时机 | `build_system_prompt` 阶段 | agent 调用 `save_memory` 工具时 |
| 机制 | query 检索 Top-K → 注入 prompt | LLM 判断「该记」 → 工具内去重/合并 |
| token 成本 | 固定 Top-K（可控几百 token） | 仅触发时单次 LLM 调用 |
| 谁决策 | 系统（确定性） | LLM（概率性）+ 工具内规则兜底 |

### 为什么不接 deepagents 的 `MemoryMiddleware`

调研确认 `MemoryMiddleware` 存在但有以下限制，与需求不符：
- 记忆存为整份 markdown 文件（AGENTS.md），**无结构化、无去重、无语义检索**。
- 「该记/不该记」规则**写死在源码里**，不可配置。
- sources 是全局路径，**按用户隔离需改 StoreBackend 的 namespace factory**（侵入较深）。
- 用户**不可见、不可管理**（与「用户可管理」需求冲突）。

故选择自建 PG 表 + 工具方案，完全可控。

---

## 2. 数据模型

### 2.1 新模型 `UserMemory`

文件：`apps/api/app/models/user_memory.py`（新建，仿 `knowledge_chunk.py` 范式）

```python
import uuid

from pgvector.sqlalchemy import HALFVEC as HalfVec
from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

# 与 knowledge_chunk 对齐：智谱 embedding-3 输出 2048 维
EMBEDDING_DIM = 2048

# 记忆来源（写路径区分）
SOURCE_AGENT = "agent"      # agent 在 loop 中自动写入
SOURCE_MANUAL = "manual"    # 用户在前端手动添加


class UserMemory(Base, IdMixin, TimestampMixin):
    """用户绑定的长期记忆（跨项目、跨会话稳定）。

    - user_id：严格隔离，仅本人可见、本人可检索（不做三域，纯个人）。
    - content：一条记忆 = 一句话/一段话（建议 ≤200 字，前端校验）。
    - embedding：写入时同步生成，用于读路径检索。允许 NULL（embedding 配置
      不可用时降级为纯文本记忆，读路径检索跳过 NULL 记忆）。
    - source：区分 agent 自动写入 vs 用户手动添加（前端可筛选）。
    - 无 scope 字段：与 KnowledgeChunk 不同，记忆纯属个人，无 global/personal 之分。
    """
    __tablename__ = "user_memories"
    __table_args__ = (
        # 前端列表查询用:按用户 + 更新时间倒序。
        # user_id 单列另由 mapped_column(index=True) 自动建索引,
        # 此复合索引优化「列出某人全部记忆」的 ORDER BY 场景。
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

### 2.2 字段决策说明

| 字段 | 类型 | 决策理由 |
|---|---|---|
| `content` | `Text` | 一条记忆一句话，符合 deepagents「原子化记忆」原则，便于去重和检索命中 |
| `embedding` | `HalfVec(2048) nullable` | 与 `knowledge_chunk` 对齐（halfvec 绕过 2000 维上限）；nullable 是关键降级设计——embedding 配置不可用时记忆仍可存（纯文本），检索时跳过 |
| `source` | `String(20)` | `agent` / `manual`，前端可筛选展示「AI 自动记录的」vs「我手动添加的」，增强可解释性 |
| 无 `scope` | — | 记忆纯属个人，无三域隔离需求，简化模型 |
| 无 `is_pinned` | — | 纯检索式注入，不需要常驻标记（避免额外复杂度） |
| 无 `category` | — | 初期不分偏好/事实/know-how 类别，避免 LLM 分类负担；若后续需要再加 |

### 2.3 迁移

文件：`apps/api/alembic/versions/e1m2e3m4o5r6_add_user_memories.py`（新建）

```python
"""add user_memories table for long-term memory

Revision ID: e1m2e3m4o5r6
Revises: d1h2n3s4w5i6
Create Date: 2026-07-28

列类型严格对齐 IdMixin/TimestampMixin(base.py) + c3d4e5f6a7b8 范式,
保证后续 autogenerate 不报伪 diff:
- id = sa.Uuid()
- timestamps = sa.DateTime(timezone=True) server_default now() NOT NULL
- embedding = HalfVec(2048),与 knowledge_chunks 同维(智谱 embedding-3)
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
    # 对应模型中 user_id 的 index=True
    op.create_index("ix_user_memories_user_id", "user_memories", ["user_id"])
    # 前端列表查询:按用户 + 更新时间倒序
    op.create_index(
        "ix_user_memories_user_updated", "user_memories", ["user_id", "updated_at"]
    )
    # HNSW 索引(cosine 距离,与 knowledge_chunks 同款参数 m=16/ef_construction=64)
    # d1h2n3s4w5i6 的同款 halfvec_cosine_ops
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

⚠️ **HNSW 索引只在 PostgreSQL 生效**。`op.execute(...)` 在 SQLite 测试库会失败——
测试用 SQLite 内存库时,需在 conftest 跳过此迁移或用 `is_postgres()` 守卫。
实际测试不依赖真实向量索引(见 §10.2,mock embedding + 断言 service 逻辑)。
**生产迁移必须能在 PG 上跑通**——halfvec 扩展已在 `d1h2n3s4w5i6` 之前就绪。

**SQLite 兼容（测试用）**：`halfvec` 在 SQLite 不存在，测试沿用 `KnowledgeChunk` 的既定处理方式（`HalfVec` 在 SQLite 下 SQLAlchemy 会降级处理，测试库不建向量索引，检索测试走 PG 或 mock）。详见 GOTCHAS G2。

### 2.4 注册模型

修改 `apps/api/app/models/__init__.py`：新增 import 与 `__all__` 条目。

```python
from app.models.user_memory import UserMemory
# __all__ 中加入 "UserMemory"
```

---

## 3. Service 层

文件：`apps/api/app/services/memory_service.py`（新建）

```python
"""用户长期记忆服务：CRUD + embedding 生成 + 语义检索。"""
import uuid as _uuid
from dataclasses import dataclass

from pgvector.sqlalchemy import HALFVEC as HalfVec
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import is_postgres
from app.core.exceptions import NotFoundError, ValidationError
from app.models import UserMemory
from app.rag.embedding import embed_text
from app.services.llm_config_service import resolve_embedding_config

# 检索默认参数
DEFAULT_TOP_K = 5
SIMILARITY_THRESHOLD = 0.5  # 与 retriever.py 一致

# 去重阈值：embedding 余弦相似度 ≥ 此值视为重复，触发合并而非新增
DEDUP_SIMILARITY = 0.85


@dataclass
class MemorySearchResult:
    content: str
    score: float
    id: _uuid.UUID


def _try_embed(db: Session, user_id, text: str) -> list[float] | None:
    """尝试生成 embedding。配置不可用或失败时返回 None（降级为纯文本记忆）。

    与 retriever.retrieve 的 resolve_embedding_config 同源——记忆复用用户的
    embedding 配置链路（自定义/全局/env），与知识库检索一致。
    """
    embed_config = resolve_embedding_config(db, user_id=user_id)
    if embed_config is None:
        return None
    try:
        return embed_text(text, embed_config=embed_config)
    except Exception:
        # embedding 失败不阻断记忆写入——降级为纯文本，检索时跳过
        return None


def create_memory(
    db: Session, *, user_id, content: str, source: str = "agent"
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


def search_memories(
    db: Session, *, user_id, query: str, top_k: int = DEFAULT_TOP_K
) -> list[MemorySearchResult]:
    """语义检索用户的记忆（读路径核心）。

    返回按相似度排序的 Top-K 记忆。embedding 配置不可用时返回空列表（降级）。
    """
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


def find_similar_memory(
    db: Session, *, user_id, content: str, threshold: float = DEDUP_SIMILARITY
) -> UserMemory | None:
    """查找与 content 高度相似的已有记忆（写路径去重用）。

    返回相似度 ≥ threshold 的最近一条，用于「合并而非重复新增」。
    无相似记忆返回 None。
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
    """删除记忆（仅本人）。"""
    mem = db.get(UserMemory, memory_id)
    if mem is None or mem.user_id != user_id:
        raise NotFoundError("记忆不存在")
    db.delete(mem)
    db.flush()


def list_memories(
    db: Session, *, user_id, source: str | None = None, limit: int = 200
) -> list[UserMemory]:
    """列出用户所有记忆（前端管理页用），按更新时间倒序。"""
    stmt = select(UserMemory).where(UserMemory.user_id == user_id)
    if source:
        stmt = stmt.where(UserMemory.source == source)
    stmt = stmt.order_by(UserMemory.updated_at.desc()).limit(limit)
    return list(db.scalars(stmt))
```

### 3.1 设计要点

- **`_try_embed` 降级策略**：embedding 失败时返回 `None`，记忆仍可写入（纯文本）。读路径 `search_memories` 自动跳过 `embedding IS NULL` 的记忆。这保证「embedding 配置不可用时记忆功能不报错」，与现有「embedding 没配就报错」的 RAG 检索保持一致的容错哲学。
- **复用 `resolve_embedding_config`**：记忆 embedding 用与知识库相同的配置链路（用户的自定义/全局/env embedding 配置），不单独维护。
- **去重逻辑在 service 层**：`find_similar_memory` 供写路径工具调用，避免 service 与工具耦合。

---

## 4. 工具参数注入机制（基建修复）

这是必须先做的基建修复——既支撑新的 `save_memory` 工具，也修复现有 `rag_search` 的参数注入缺陷。

### 4.1 问题

现有 `rag_search_tool(query, user_id, db_session)`：
- LLM 只会生成 `query`（它不知道 user_id，更不知道 db_session）。
- agent loop 调用时，`user_id` 和 `db_session` **没有任何注入路径**。
- 结果：agent 即使决定调 `rag_search`，也会因缺参数失败（或传 None 导致空结果）。

### 4.2 方案：闭包工厂

文件：`apps/api/app/ai/tools.py`（重构）

将工具从「模块级常量」改为「工厂函数」，在 `build_agent` 时用已知 user_id + db 闭包绑定：

```python
# apps/api/app/ai/tools.py（重构后）
"""agent 工具：rag_search / save_memory 等 @tool。

工具通过工厂函数 create_agent_tools(db, user_id) 装配，
user_id 与 db 由闭包绑定——LLM 无需（也无法）生成这些参数。
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
        [rag_search_tool, save_memory_tool] —— 供 create_deep_agent(tools=...) 使用。
    """
    @tool("rag_search")
    def rag_search(query: str) -> list[dict]:
        """检索用户知识库（RAG）。当需要参考历史案例、已有交底书、知识库文档时调用。"""
        from app.rag.retriever import retrieve
        try:
            _uuid.UUID(str(user_id))  # 校验合法性
        except (ValueError, TypeError):
            return []
        results = retrieve(db, user_id=user_id, query=query)
        return [
            {"content": r.content, "section_key": r.source_section_key,
             "project_title": r.project_title}
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
            # 合并：相似度 ≥ 阈值，更新已有记忆（取并集语义）
            update_memory(db, memory_id=similar.id, user_id=user_id, content=content)
            db.commit()
            return f"已合并更新已有记忆（原：「{similar.content[:50]}...」）"

        create_memory(db, user_id=user_id, content=content, source=SOURCE_AGENT)
        db.commit()
        return "已保存"

    return [rag_search, save_memory]
```

### 4.3 修改 `build_agent`

文件：`apps/api/app/ai/agent.py`

```python
# 修改前
from app.ai.tools import rag_search_tool
...
tools=[rag_search_tool],

# 修改后
from app.ai.tools import create_agent_tools
...
tools=create_agent_tools(db, user_id),
```

### 4.4 兼容性

- `test_rag_tool.py` 的 `rag_search_tool.invoke({"query":..., "user_id":..., "db_session":...})` 测试需改为用工厂函数构造的实例。这属于缺陷修复的合理测试调整。
- 向后兼容：移除模块级 `rag_search_tool` 常量，所有引用改为 `create_agent_tools`。

---

## 5. 读路径：记忆注入

文件：`apps/api/app/ai/context_assembler.py`（修改 `build_system_prompt`）

### 5.1 修改 `build_system_prompt`

```python
def build_system_prompt(db, section: Section) -> str:
    """装配动态 system prompt（agent loop 路线用，spec §3.1.1）。

    拼接顺序：
    项目元信息 → 已写章节 → 用户记忆（检索注入）→ 当前章节策略 → 角色定义。
    """
    from app.services.memory_service import search_memories

    project = db.get(Project, section.project_id)
    sp = get_section_prompt(section.key)

    parts: list[str] = []

    # [L4] 项目元信息层
    parts.append("# 当前交底书项目")
    parts.append(f"项目标题：{project.title}")
    if project.metadata_:
        meta_text = _format_metadata(project.metadata_)
        if meta_text:
            parts.append(f"项目背景信息：\n{meta_text}")

    # [前文直注入] 已写章节层
    written = get_written_sections_text(db, section.project_id, exclude_key=section.key)
    if written:
        parts.append("# 已完成章节内容（请保持术语、技术方案一致性）")
        parts.append(written)

    # 【新增】用户长期记忆层（检索注入，纯检索式策略）
    # 检索 query：章节标题 + 目标，覆盖本章节最可能相关的用户偏好/事实/know-how
    memory_query = f"{section.title} {sp.goal}"
    owner_uid = _section_owner_uid(db, section)
    if owner_uid is not None:
        memories = search_memories(db, user_id=owner_uid, query=memory_query, top_k=5)
        if memories:
            memory_lines = "\n".join(f"- {m.content}" for m in memories)
            parts.append("# 关于这位用户的长期记忆（请遵循其偏好与约定）")
            parts.append(memory_lines)

    # 章节策略层
    parts.append("# 当前正在撰写章节")
    parts.append(f"章节标题：【{section.title}】")
    parts.append(f"本章目标：{sp.goal}")
    parts.append(f"输出格式要求：{sp.output_format}")

    # 角色定义层
    parts.append(SYSTEM_PROMPT)

    return "\n\n".join(parts)
```

### 5.2 辅助函数

```python
def _section_owner_uid(db, section: Section):
    """取 section 所属项目的 user_id（用于记忆检索范围限定）。

    复用 orchestrator._section_owner 的逻辑，独立为本模块函数避免循环依赖。
    """
    project = db.get(Project, section.project_id)
    return project.user_id if project else None
```

### 5.3 chat 场景的检索 query 优化

当前 `build_system_prompt` 在 chat/generate 都用「章节标题 + 目标」做检索 query。但 chat 场景用户当前输入往往是更好的检索信号（用户刚说「我要突出对比实验」，记忆里恰好有「我们领域重视对比数据」）。

**决策**：MVP 阶段先用统一的「章节标题 + 目标」query（简单、确定性）。chat 场景按用户当前输入检索作为 v2 优化（需要把 `user_input` 透传到 `build_system_prompt`，改动稍大）。本设计文档记录此为已知限制。

---

## 6. 写路径：工具调用与去重

### 6.1 工具行为（见 §4.2 `save_memory`）

LLM 在 agent loop 中自主调用 `save_memory(content)`。工具内部：

1. **空内容校验**：直接返回「未保存」。
2. **去重**：调 `find_similar_memory` 查找 embedding 相似度 ≥ 0.85 的已有记忆。
3. **合并**：若存在相似记忆，更新该记忆内容（用新内容覆盖，取并集语义）。
4. **新增**：无相似记忆则 `create_memory`。

### 6.2 去重阈值决策

- `DEDUP_SIMILARITY = 0.85`：高于检索阈值 0.5，保证只合并「语义高度重合」的记忆。
- 例：「偏好简洁风格」(0.92) → 合并；「偏好简洁风格」+「多用短句」(0.95) → 合并为后者。
- 低于 0.85 的新偏好（如「偏好简洁」vs「权利要求从宽到窄」，相似度 0.3）正常新增，不误合并。

### 6.3 合并策略

当前为「新内容覆盖旧内容」——简单可靠，避免 LLM 二次介入合并（成本高）。缺点是旧记忆中独有的部分可能丢失。

**v2 优化**（本设计不实现）：合并时调 LLM 生成「旧 ∧ 新」的并集描述。MVP 先用覆盖策略，待真实数据验证是否需要。

### 6.4 为什么不用 LLM 判断是否记忆

调研显示 deepagents `MemoryMiddleware` 的做法是「system prompt 写死规则 + LLM 自觉调 edit_file」。本设计的 `save_memory` 工具 description 也写死了一套「何时该/不该记忆」规则（见 §4.2 工具 docstring）。两者本质相同——都靠 LLM 概率性判断。区别在于：

- **本设计在工具层加去重兜底**：即使 LLM 重复调用，也不会产生重复记忆。
- **MemoryMiddleware 无去重**：LLM 反复 edit_file 会让 AGENTS.md 膨胀。

---

## 7. 后端 API

文件：`apps/api/app/api/memories.py`（新建，仿 `knowledge.py` 范式）

```python
"""用户长期记忆管理路由。"""
import uuid as _uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.deps import get_current_user
from app.models import User
from app.services import memory_service

router = APIRouter(prefix="/memories", tags=["memories"])


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)
    source: str = Field("manual", pattern="^(agent|manual)$")


class MemoryUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)


class MemoryOut(BaseModel):
    id: str
    content: str
    source: str
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, m) -> "MemoryOut":
        return cls(
            id=str(m.id), content=m.content, source=m.source,
            created_at=m.created_at.isoformat(), updated_at=m.updated_at.isoformat(),
        )


@router.get("")
def list_memories(
    source: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MemoryOut]:
    """列出当前用户的所有记忆。可选 source 筛选（agent/manual）。"""
    memories = memory_service.list_memories(
        db, user_id=current_user.id, source=source
    )
    return [MemoryOut.from_model(m) for m in memories]


@router.post("")
def create_memory(
    payload: MemoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MemoryOut:
    """手动新增一条记忆。"""
    mem = memory_service.create_memory(
        db, user_id=current_user.id, content=payload.content, source=payload.source
    )
    db.commit()
    return MemoryOut.from_model(mem)


@router.patch("/{memory_id}")
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MemoryOut:
    """修改一条记忆。"""
    mem = memory_service.update_memory(
        db, memory_id=_uuid.UUID(memory_id), user_id=current_user.id, content=payload.content
    )
    db.commit()
    return MemoryOut.from_model(mem)


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

注册到 `apps/api/app/api/router.py`（仿现有路由注册方式）。

---

## 8. 前端 UI

### 8.1 页面结构

新增页面：`apps/web/src/app/settings/memories/page.tsx`

布局（参考现有 settings 子页风格，Liquid Glass 设计）：
- **页头**：标题「我的记忆」+ 说明「Agent 会记住你告诉它的偏好和约定。你也可以在这里手动管理。」
- **新建区**：一个文本框（textarea，max 500 字）+「添加记忆」按钮。
- **筛选 Tab**：「全部 / AI 自动记录 / 我手动添加的」。
- **记忆列表**：每条卡片含 content（可编辑，点击进入编辑态）、source 徽章、更新时间、删除按钮（带确认）。

### 8.2 组件清单

```
apps/web/src/app/settings/memories/page.tsx          # 页面主体
apps/web/src/components/memory-card.tsx              # 单条记忆卡片（查看/编辑/删除态）
apps/web/src/components/memory-form.tsx              # 新建记忆表单
```

### 8.3 API client

扩展 `apps/web/src/lib/api.ts`：
```typescript
export const memoryApi = {
  list: (source?: string) => http.get('/memories', { params: { source } }),
  create: (content: string, source: 'agent' | 'manual' = 'manual') =>
    http.post('/memories', { content, source }),
  update: (id: string, content: string) =>
    http.patch(`/memories/${id}`, { content }),
  remove: (id: string) => http.delete(`/memories/${id}`),
}
```

### 8.4 React Query hooks

扩展 `apps/web/src/lib/queries.ts`：
```typescript
export function useMemories(source?: string) {
  return useQuery({
    queryKey: ['memories', source],
    queryFn: () => memoryApi.list(source),
  })
}

export function useCreateMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: { content: string; source?: 'agent' | 'manual' }) =>
      memoryApi.create(vars.content, vars.source),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }),
  })
}
// useUpdateMemory / useDeleteMemory 同理
```

### 8.5 导航入口

在 `apps/web/src/app/settings/layout.tsx`（或现有 settings 侧栏）增加「我的记忆」入口。

---

## 9. system prompt 提示词增强

修改 `apps/api/app/ai/context_assembler.py` 的 `SYSTEM_PROMPT`，增加一段记忆写入引导：

```python
SYSTEM_PROMPT = """你是「天工」，一个专利交底书撰写助手。你的任务是引导发明人把技术想法整理成规范的专利交底书。

规则：
1. 用专业但通俗的中文交流，避免生硬的法律术语
2. 引导用户补充关键技术细节，不要替用户编造
3. 输出内容用 Markdown 格式（标题用 ##/###，可用列表）
4. 保持客观准确，不夸大技术效果
5. 如果用户的信息不完整，主动追问
6. 当用户表达了值得长期记住的偏好、事实或领域约定时，调用 save_memory 工具保存。
   只记跨项目稳定的信息（如「偏好简洁风格」「我做新能源电池」），不记项目内具体决策。
"""
```

注意：详细的「该记/不该记」规则放在 `save_memory` 工具的 docstring 里（§4.2），system prompt 只做一句话引导，避免 prompt 膨胀。

---

## 10. 测试策略

遵循项目 TDD 约定（参考 `test_rag_tool.py`、`test_agent_factory.py` 范式）。

### 10.1 后端单元测试（pytest）

文件：`apps/api/tests/test_memory_service.py`（新建）
- `test_create_memory_generates_embedding` — 写入时 embedding 非 None
- `test_create_memory_without_embedding_config_falls_back_to_null` — 配置不可用时 embedding 为 NULL，记忆仍写入
- `test_search_memories_returns_relevant` — 检索返回相关记忆（mock embedding）
- `test_search_memories_skips_null_embedding` — NULL embedding 的记忆被跳过
- `test_find_similar_memory_detects_duplicate` — 相似度 ≥ 0.85 返回已有记忆
- `test_find_similar_memory_no_match_returns_none` — 相似度低返回 None
- `test_update_memory_regenerates_embedding` — 更新内容后 embedding 重建
- `test_delete_memory_only_owner` — 非本人删除抛 NotFoundError
- `test_list_memories_orders_by_updated_desc` — 倒序排列

文件：`apps/api/tests/test_memory_api.py`（新建）
- `test_list_memories_returns_only_own` — 用户隔离
- `test_create_memory_manual_source` — 默认 source=manual
- `test_update_memory_not_owner_404` — 非本人修改 404
- `test_delete_memory_not_owner_404` — 非本人删除 404
- `test_content_too_long_rejected` — 超 500 字被 Pydantic 拒绝

文件：`apps/api/tests/test_save_memory_tool.py`（新建）
- `test_save_memory_new_content` — 新内容创建新记忆
- `test_save_memory_dedup_merges` — 相似内容合并而非新增
- `test_save_memory_empty_returns_unsaved` — 空内容返回提示

文件：`apps/api/tests/test_agent_factory.py`（修改现有）
- 适配 `create_agent_tools` 工厂，断言 tools 包含 `rag_search` 和 `save_memory`

文件：`apps/api/tests/test_rag_tool.py`（修改现有）
- 适配工厂模式，`rag_search.invoke({"query": ...})` 只传 query

### 10.2 数据库测试约定（GOTCHAS G2）

- 用 SQLite 内存库 + `JSONB().with_variant(JSON, "sqlite")`。
- `HalfVec` 在 SQLite 降级，向量检索测试 mock `embed_text` 返回固定向量，断言 service 层逻辑而非真实 PG 检索。
- 真实 PG + pgvector 检索行为靠手动验证（与现有 RAG 检索测试一致）。

### 10.3 前端测试

前端按现有 dogfood 方式（参考 retrieval-test 页），不强制单测。重点验证：
- 列表加载、新增、编辑、删除的 CRUD 闭环。
- source 筛选切换。
- 空 content 校验。

---

## 11. 错误处理与降级

| 场景 | 处理 |
|---|---|
| embedding 配置未配 | `_try_embed` 返回 None，记忆写入降级为纯文本；检索时跳过 NULL embedding，返回空（用户无感） |
| embedding API 调用失败 | 同上，降级不报错 |
| 用户删除时记忆不存在 | `NotFoundError` → API 返回 404 |
| 内容超长 | Pydantic 在 API 层拒绝；工具层 strip 后写入（工具信任 LLM 输出） |
| 去重查询失败 | 不阻断写入，直接新增（降级为不去重） |

---

## 12. 已知限制（v1 范围外，记录待 v2）

1. ~~**chat 场景检索 query 未用用户当前输入**~~：✅ 已修复（2026-07-29）。chat 路径改用 `user_input` 检索，generate 路径用 history 最后一条 user message。
2. **合并策略为覆盖**：旧记忆独有部分可能丢失。v2 可加 LLM 合并。
3. **无记忆类别（偏好/事实/know-how）**：v1 不分类，前端不展示分类。若记忆膨胀可加。
4. **无记忆容量上限**：v1 不限制单用户记忆条数。若膨胀可加软上限 + 老旧记忆淘汰。
5. **去重依赖 embedding**：embedding 配置不可用时不去重（`find_similar_memory` 返回 None），可能产生重复——但记忆本身可降级写入，可接受。
6. **rewrite / caption_figures 路径不带记忆**：这两个走裸 LangChain（非 agent loop），不注入记忆。后续若需要再改造。
7. **去重阈值 0.85 对中文短句可能过激进**（2026-07-29 深度审查发现）：两条语义相近但独立的偏好（如「偏好简洁风格」vs「偏好简洁的写作」）可能被误合并。v2 可调高到 0.90-0.92，或改用「语义相似 + 内容包含」双重判断。
8. **agent loop 共享 session 的事务隔离隐患**（2026-07-29 深度审查发现）：
   - **C1**（未修，技术债）：`SessionLocal` 默认 `expire_on_commit=True`，工具内 commit 后所有 ORM 对象 expire。当前靠调用顺序侥幸未触发（system prompt 在首次工具调用前算好）。全局改 `expire_on_commit=False` 影响所有 service 的 commit 行为，风险高于收益，列为技术债。
   - ~~**C2**~~：✅ 已修复（2026-07-29）。`log_embed_call` / `log_firecrawl_call` 改用独立 session 写日志（`llm_log_helper._write_log_with_isolated_session`），与主请求 session 完全隔离。复用项目 standalone session 模式。意外修复了 archiver 的潜伏提前提交 bug。chat/generate 的 `_log_llm_call` 仍用主 session，但 finally 块已加 rollback 预清理，不再毒化后续流程。
9. **工具返回串对 LLM 行为的影响**（2026-07-29 深度审查发现）：`save_memory` 失败返回「请稍后重试」可能诱导 LLM 重试；合并分支回显原记忆内容可能被复述进对话。v2 可优化返回措辞。
10. **written sections 注入 + history 重复导致 token 翻倍**（2026-07-29 深度审查发现）：system prompt 注入已写章节（≤8KB），history 又含讨论这些章节的对话，长项目可能撞 context window。v2 评估 history 截断/摘要。

---

## 13. 实施顺序（供 writing-plans 参考）

建议分 5 个 Phase，每个 Phase 可独立验证：

1. **Phase 1 数据层**：UserMemory 模型 + 迁移 + 注册。验收：`alembic upgrade head` 成功，模型可 import。
2. **Phase 2 Service 层**：`memory_service.py` 全套 + 单测。验收：单测全绿。
3. **Phase 3 工具注入机制**：重构 `tools.py` 为工厂 + 修改 `build_agent` + 修复 rag_search + 适配现有测试。验收：现有测试通过 + save_memory 工具单测绿。
4. **Phase 4 读写路径接入**：`build_system_prompt` 注入记忆 + system prompt 规则增强。验收：集成测试（mock embedding，断言 prompt 含记忆段）。
5. **Phase 5 API + 前端**：后端 CRUD 路由 + 前端管理页。验收：API 单测绿 + 前端 CRUD 闭环 dogfood。

---

## 附录 A：关键文件清单

| 类型 | 路径 | 操作 |
|---|---|---|
| 新建模型 | `apps/api/app/models/user_memory.py` | 新建 |
| 新建 service | `apps/api/app/services/memory_service.py` | 新建 |
| 新建迁移 | `apps/api/alembic/versions/e1m2e3m4o5r6_add_user_memories.py` | 新建 |
| 重构工具 | `apps/api/app/ai/tools.py` | 重构为工厂 |
| 修改装配 | `apps/api/app/ai/agent.py` | 用 create_agent_tools |
| 修改 prompt | `apps/api/app/ai/context_assembler.py` | build_system_prompt 注入记忆 + SYSTEM_PROMPT 规则 |
| 新建 API | `apps/api/app/api/memories.py` | 新建 |
| 注册路由 | `apps/api/app/api/router.py` | 注册 memories router |
| 注册模型 | `apps/api/app/models/__init__.py` | 加 UserMemory |
| 新建前端页 | `apps/web/src/app/settings/memories/page.tsx` | 新建 |
| 新建前端组件 | `apps/web/src/components/memory-card.tsx`, `memory-form.tsx` | 新建 |
| 扩展 client | `apps/web/src/lib/api.ts`, `queries.ts` | 加 memoryApi / hooks |
| 测试 | `tests/test_memory_service.py`, `test_memory_api.py`, `test_save_memory_tool.py` | 新建 |
| 修改测试 | `tests/test_agent_factory.py`, `test_rag_tool.py` | 适配工厂模式 |
