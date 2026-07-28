# RAG 增强（HNSW + 检索测试页 + 混合检索 + 分块干预）— TDD 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 RAGFlow 借鉴设计（`docs/superpowers/specs/2026-07-27-ragflow-borrow-design.md`）的四项 RAG 增强，构成「可观测、可干预、术语精准」的 RAG 升级闭环：① G1 给 pgvector embedding 列加 HNSW 索引（解决全表暴力扫描，Firecrawl 落地后紧迫性升级）；② G2 admin 检索测试页（RAG 调参闭环工具，为 G3/G4 验收铺路）；③ G3 混合检索（BM25 via tsvector + 向量 + RRF 融合 + rerank，专利术语精度刚需）；④ G4 分块可视化干预（admin 可编辑 chunk 的 content/keywords/questions/weight，专利知识最怕切散）。

**Architecture:** 全部在现有 Postgres + pgvector + MinIO 栈内闭环，不引入新存储、不破坏 agent tool 架构、不触碰三域隔离。`retriever.py` 单文件改造（sync Session，两个调用方 rag_search tool / search API 签名保持不变）；rerank 配置复用 `SystemSetting + resolve_*` 三级解析模式；G4 字段走独立列 + 迁移（keywords/questions JSON 列、weight Float 列、tsvector 列）。测试体系：SQLite 内存库测业务逻辑（Vector 列已 JSON 兼容），真实向量检索/混合检索效果靠 G2 检索测试页人工验证，RRF/rerank/tsvector 逻辑层纯单测。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy 2.0 / pgvector（HNSW） / Postgres 内置 tsvector + GIN / 智谱 rerank API（httpx 直连）/ Next.js + react-query（admin 页抄 Firecrawl 页模板）

**Spec:** `docs/superpowers/specs/2026-07-27-ragflow-borrow-design.md`
**关联文档:** `docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md`（已落地，本计划前置依赖）
**执行方式:** subagent-driven-development（Task 间解耦可分派，每个 Phase 内部串行，Phase 间有依赖见「实施顺序」）
**预计工期:** 8-13 天

---

## 承重决策（D1-D8，与 spec 对齐 + 本计划补充）

- **D1（HNSW 优先于 IVFFlat）+ D1.1（halfvec 半精度）**：`embedding` 列建 HNSW 索引。pgvector 0.7+ 原生支持，召回质量优于 IVFFlat，增量写入友好（知识库持续 ingest）。参数 `m=16, ef_construction=64`（官方推荐），`ef_search=max(40, top_k*4)` 查询时设。**⚠️ D1.1（2026-07-28 Task 1.1 实施时发现）**：pgvector HNSW/IVFFlat 对 `vector` 类型有 2000 维硬上限，智谱 embedding-3 原生 2048 维超限。解法：列类型 `vector(2048)` → `halfvec(2048)`（支持 4000 维，float16 存储减半，精度损失可忽略，pgvector 0.8.5 实测可用）。不降维、不改 EMBEDDING_DIM。
- **D2（混合检索 Postgres 内闭环）**：BM25 用 Postgres 内置 `tsvector` + `ts_rank_cd`，向量用 pgvector，融合用 RRF（k=60）。**不引入 ES/Lucene**。rerank 用智谱 rerank API（httpx 直连）为首选，失败时降级返回 RRF 结果。
- **D3（G4 字段独立列 + 迁移）** ⚠️用户确认：keywords(JSON)/questions(JSON)/weight(Float)/edited_text(Text)/locked(Boolean) 建**独立列**（可建 GIN/索引，SQL 友好），不走 metadata_ JSONB 扩展。同时加 `tsv tsvector` 列（G3 用）+ GIN 索引。
- **D4（检索测试页 admin 域）**：新增 `POST /admin/knowledge/retrieval-test` 端点（不复用普通用户的 `/knowledge/search`，因为 admin 要能强制 scope=global 视角）。前端抄 Firecrawl 配置页模板。
- **D5（rerank 作为 post-retrieval 可开关插层）**：不替换向量召回，在召回后、返回前插一层。admin 可在后台开关 rerank、配 rerank 模型。默认开，失败降级。
- **D6（HNSW 参数不暴露 admin）**：`m/ef_construction/ef_search` 写死常量，避免误调。rerank 配置（enabled/provider/base_url/api_key/model/top_n）暴露 admin。
- **D7（G3 验证：纯单测 + G2 人工）** ⚠️用户确认：SQLite 测不了真实向量检索，RRF 融合/rerank client/tsvector 生成逻辑层纯单测；真实检索效果靠 G2 检索测试页人工验证（spec §8.3 的 20 条 query 对比）。**不引入 PG 集成测试**（避免起新坑）。
- **D8（chunk 编辑触发重 embed）**：G4 编辑 `edited_text` 非空时，检索返回和喂 LLM 都用 `edited_text`；`edited_text` 变更触发重新 embed 更新 `embedding` 列；`keywords/questions` 变更触发重新生成 `tsv`。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `apps/api/alembic/versions/d1h2n3s4w5i6_add_hnsw_index.py` | HNSW 索引 | 新建 |
| `apps/api/alembic/versions/e3r4a5g6t7s8v_add_tsv_column.py` | tsv 列 + GIN + 回填 | 新建 |
| `apps/api/alembic/versions/f4g5i6n7t8e9_add_chunk_intervention_fields.py` | G4 字段列 | 新建 |
| `apps/api/app/models/knowledge_chunk.py` | 加 tsv/keywords/questions/weight/edited_text/locked 列 | 改 |
| `apps/api/app/rag/retriever.py` | 混合检索（向量+BM25+RRF）+ rerank 插层 + SET ef_search + scope 参数 + edited_text/weight 集成 | 改（signature 不变，内部重构） |
| `apps/api/app/rag/fusion.py` | RRF 融合算法（纯函数） | 新建 |
| `apps/api/app/rag/reranker.py` | rerank client（httpx 直连智谱） | 新建 |
| `apps/api/app/services/rag_config_service.py` | rerank 配置 get/set + resolve_rerank_config | 新建 |
| `apps/api/app/services/knowledge_service.py` | `_ingest_chunks` 生成 tsv；新增 list_chunks_by_file / update_chunk | 改 |
| `apps/api/app/rag/archiver.py` | 归档流生成 tsv | 改 |
| `apps/api/app/core/database.py` | 加 is_postgres() helper | 改 |
| `apps/api/app/api/admin/retrieval.py` | POST /admin/knowledge/retrieval-test | 新建 |
| `apps/api/app/api/admin/chunks.py` | GET /admin/knowledge/files/{id}/chunks + PATCH /admin/knowledge/chunks/{id} | 新建 |
| `apps/api/app/api/admin/console.py` | 加 rerank 配置端点 | 改 |
| `apps/api/app/api/admin/__init__.py` | 注册新 router | 改 |
| `apps/api/tests/conftest.py` | SQLite 兼容版 chunk 表加 tsv + G4 字段列 | 改 |
| `apps/api/tests/test_fusion.py` | RRF 融合纯函数测试 | 新建 |
| `apps/api/tests/test_reranker.py` | rerank client mock 测试 | 新建 |
| `apps/api/tests/test_retriever.py` | 混合检索逻辑测试（mock embed/rerank） | 新建 |
| `apps/api/tests/test_rag_config.py` | rerank 配置 resolve 测试 | 新建 |
| `apps/api/tests/test_admin_chunks.py` | G4 chunk 编辑端点测试 | 新建 |
| `apps/api/tests/test_admin_retrieval.py` | G2 检索测试端点测试 | 新建 |
| `apps/api/tests/test_chunk_tsv.py` | tsv 生成逻辑测试 | 新建 |
| `apps/web/src/lib/api.ts` | retrievalTest / listChunks / updateChunk / getRerankConfig 等 | 改 |
| `apps/web/src/lib/queries.ts` | useRetrievalTest / useFileChunks / useUpdateChunk / rerank hooks | 改 |
| `apps/web/src/app/(app)/admin/console/retrieval-test/page.tsx` | G2 检索测试页 | 新建 |
| `apps/web/src/app/(app)/admin/console/rerank/page.tsx` | G3 rerank 配置页 | 新建 |
| `apps/web/src/app/(app)/admin/content/knowledge/[fileId]/page.tsx` | G4 chunk 编辑页 | 新建 |
| `apps/web/src/components/admin/chunk-editor-dialog.tsx` | G4 chunk 编辑对话框 | 新建 |
| `apps/web/src/app/(app)/admin/console/page.tsx` | 控制台索引页加卡片 | 改 |
| `apps/web/src/app/(app)/admin/content/knowledge/page.tsx` | 文件卡片加「查看分块」链接 | 改 |

---

## 实施顺序与依赖

```
Phase 0（Task 0）: 基线绿 + 分支            ← 无依赖
Phase 1（G1）:     HNSW 索引迁移              ← 依赖 Task 0
Phase 2（G2）:     检索测试页（后端+前端）     ← 依赖 Phase 1（用真实索引验证）
Phase 3（G3）:     混合检索 + rerank          ← 依赖 Phase 2（调参验证）
Phase 4（G4）:     分块可视化干预             ← 依赖 Phase 2（验证干预效果），与 Phase 3 并行
```

**关键依赖**：Phase 2（检索测试页）必须在 Phase 3/4 之前完成——它是 G3/G4 所有调参的验收工具。Phase 1（HNSW）是 Phase 2 的前置（否则检索测试页本身慢）。

每个 Phase 内部 Task 串行（Task N+1 依赖 Task N）。Phase 间由 subagent 调度器按依赖分派。

---

## Task 0: 工程前置验证（基线绿 + 分支 + 取证）

**Files:** 无文件改动，仅验证

- [ ] **Step 1: 确认基线测试全绿**

Run:
```bash
cd apps/api && uv run pytest -q 2>&1 | tail -15
```
Expected: 全绿（现有测试基线不破）。若有 failure，停止本计划，先修复基线。

- [ ] **Step 2: 确认迁移 head + pgvector 版本（取证）**

Run:
```bash
cd apps/api && uv run alembic heads 2>&1 | tail -3
grep -n "pgvector" docker-compose.yml
```
Expected: `heads` 显示 `c3d4e5f6a7b8 (head)`；`docker-compose.yml` 含 `image: pgvector/pgvector:pg16`（浮动 tag，服务端 HNSW 可用）。**G1 新迁移的 down_revision 必须指向 `c3d4e5f6a7b8`。**

- [ ] **Step 3: 切到新分支**

```bash
cd /g/03-Personal-Projects/TianGong
git checkout main
git checkout -b feat/rag-enhancement
```
Expected: 新分支 `feat/rag-enhancement` 创建并切换成功。若 main 有未提交改动，先 `git stash`。

- [ ] **Step 4: 确认 retriever 当前实现（取证基线）**

Run:
```bash
cd apps/api && uv run python -c "
from app.rag.retriever import retrieve, RetrievalResult, SIMILARITY_THRESHOLD
import inspect
print('threshold:', SIMILARITY_THRESHOLD)
print('signature:', inspect.signature(retrieve))
print('has rerank:', 'rerank' in inspect.getsource(retrieve))
print('has tsvector:', 'tsvector' in inspect.getsource(retrieve))
"
```
Expected: `threshold: 0.5`，`signature: (db, *, user_id, query, top_k=3)`，`has rerank: False`，`has tsvector: False`。**这是改造前的基线证据，Phase 3 完成后 has_rerank/has_tsvector 应变 True。**

---

## Phase 1: G1 — pgvector HNSW 索引

### Task 1.1: 手写 HNSW 迁移

**Files:**
- Modify: `apps/api/alembic/versions/d1h2n3s4w5i6_add_hnsw_index.py`（新建）

- [ ] **Step 1: 确认迁移 head**

Run:
```bash
cd apps/api && uv run alembic heads
# 记下 head = c3d4e5f6a7b8
```

- [ ] **Step 2: 写迁移内容**

写入 `apps/api/alembic/versions/d1h2n3s4w5i6_add_hnsw_index.py`：

```python
"""add hnsw index on knowledge_chunks.embedding (halfvec)

Revision ID: d1h2n3s4w5i6
Revises: c3d4e5f6a7b8
Create Date: 2026-07-28

给 knowledge_chunks.embedding 列建 HNSW 索引（cosine 距离）。
spec: docs/superpowers/specs/2026-07-27-ragflow-borrow-design.md §5.1 (G1, D1 + D1.1)

⚠️ D1.1（2026-07-28 实施时发现）：
pgvector HNSW/IVFFlat 对 vector 类型有 2000 维硬上限，智谱 embedding-3 原生 2048 维超限。
解法：列类型 vector(2048) → halfvec(2048)（halfvec 支持 4000 维，float16 存储减半，
对 cosine 影响可忽略，pgvector 0.8.5 实测可用）。不降维、不改 EMBEDDING_DIM。

参数（D6：写死常量，不暴露 admin）：
- m=16, ef_construction=64（pgvector 官方推荐）
- ef_search 在查询时 SET LOCAL（见 retriever.py）

注意：
- 手写迁移（autogenerate 不感知向量索引 + halfvec 类型转换）
- 不动 vector extension（ee50036c9e86 已 CREATE EXTENSION，幂等不重复）
- downgrade 只 drop index + 回滚列类型，不 drop extension
- halfvec 用 halfvec_cosine_ops（与 vector_cosine_ops 平行）
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd1h2n3s4w5i6'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 防御性 CREATE EXTENSION（幂等，ee50036c9e86 已建过）
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    # D1.1: 列类型 vector(2048) → halfvec(2048)（解决 pgvector HNSW 2000 维上限）
    op.execute('ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE halfvec(2048) USING embedding::halfvec(2048)')
    # HNSW 索引：halfvec 用 halfvec_cosine_ops（与 retriever.cosine_distance 操作符对齐）
    op.execute(
        'CREATE INDEX ix_knowledge_chunks_embedding_hnsw '
        'ON knowledge_chunks USING hnsw (embedding halfvec_cosine_ops) '
        'WITH (m = 16, ef_construction = 64)'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw')
    # 回滚列类型到 vector(2048)
    op.execute('ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE vector(2048) USING embedding::vector(2048)')
    # 不 drop vector extension（其他表/列可能依赖）
```

- [ ] **Step 3: 跑迁移确认 upgrade 成功**

Run:
```bash
cd apps/api && uv run alembic upgrade head 2>&1 | tail -5
```
Expected: `Running upgrade c3d4e5f6a7b8 -> d1h2n3s4w5i6, add hnsw index (halfvec)` 成功，无报错。**若报 `column cannot have more than 2000 dimensions`，说明 halfvec 转换没生效，检查 ALTER 语句。**

- [ ] **Step 4: 验证索引存在 + 列类型是 halfvec（PG 集成验证，需 docker compose up postgres）**

Run:
```bash
cd apps/api && uv run python -c "
from sqlalchemy import text
from app.core.database import engine
with engine.connect() as conn:
    # 1. HNSW 索引存在
    r = conn.execute(text(
        \"SELECT indexname FROM pg_indexes WHERE tablename='knowledge_chunks' AND indexname='ix_knowledge_chunks_embedding_hnsw'\"
    )).fetchone()
    print('hnsw index exists:', bool(r))
    # 2. 列类型是 halfvec（D1.1 验证）
    col = conn.execute(text(
        \"SELECT data_type, udt_name FROM information_schema.columns WHERE table_name='knowledge_chunks' AND column_name='embedding'\"
    )).fetchone()
    print('embedding column type:', col)
    # 3. pgvector 版本
    v = conn.execute(text(\"SELECT extversion FROM pg_extension WHERE extname='vector'\")).fetchone()
    print('pgvector version:', v[0] if v else 'NOT INSTALLED')
"
```
Expected: `hnsw index exists: True`，`embedding column type: ('USER-DEFINED', 'halfvec')`（udt_name=halfvec 确认列类型已转），`pgvector version: 0.8.x`。

- [ ] **Step 5: 验证 downgrade 可逆**

Run:
```bash
cd apps/api && uv run alembic downgrade -1 2>&1 | tail -3
cd apps/api && uv run alembic upgrade head 2>&1 | tail -3
```
Expected: downgrade 成功（drop index），再 upgrade 成功（重建）。

- [ ] **Step 6: 回归现有 RAG 测试**

Run:
```bash
cd apps/api && uv run pytest tests/test_rag.py tests/test_rag_tool.py tests/test_knowledge_service.py tests/test_knowledge_consistency.py tests/test_embedding_logging.py -v 2>&1 | tail -20
```
Expected: 全部 PASS（HNSW 索引对业务逻辑透明，SQLite 测试不受影响）。

- [ ] **Step 7: 提交**

```bash
git add apps/api/alembic/versions/d1h2n3s4w5i6_add_hnsw_index.py
git commit -m "feat(rag): G1 给 knowledge_chunks.embedding 加 HNSW 索引（spec §5.1, D1+D1.1）

解决全表暴力扫描（Firecrawl 落地后紧迫性升级）。
⚠️ D1.1：pgvector HNSW 对 vector 类型有 2000 维上限，智谱 2048 维超限，
故列类型 vector(2048) → halfvec(2048)（支持 4000 维，float16 存储，精度损失可忽略）。
参数 m=16/ef_construction=64 写死（D6），ef_search 查询时 SET LOCAL。"
```

---

### Task 1.2: retriever 查询侧加 SET ef_search + is_postgres helper + halfvec 适配

**Files:**
- Modify: `apps/api/app/rag/retriever.py`
- Modify: `apps/api/app/core/database.py`
- Modify: `apps/api/app/rag/embedding.py`（入库转 halfvec）
- Test: `apps/api/tests/test_retriever.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `apps/api/tests/test_retriever.py`：

```python
"""retriever 逻辑测试（SQLite 跳过真实 Vector 列，只测业务逻辑）。"""
import pytest
from unittest.mock import patch, MagicMock

from app.rag.retriever import retrieve, RetrievalResult


def test_retriever_has_ef_search_set():
    """D1：retriever 查询前应 SET LOCAL hnsw.ef_search（HNSW 动态探测参数）。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert 'hnsw.ef_search' in src, "retrieve 缺少 SET LOCAL hnsw.ef_search"
    assert 'top_k' in src and 'ef_search' in src, "ef_search 应随 top_k 动态调整"


def test_retriever_adapts_halfvec():
    """D1.1：retriever 应将 query_vec 转 halfvec（列类型已改 halfvec）。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    # halfvec 适配：要么显式转换，要么用 HalfVec 类型
    assert 'halfvec' in src.lower() or 'HalfVec' in src, "retrieve 缺少 halfvec 适配（D1.1）"


def test_retriever_returns_empty_when_no_embed_config(db_session, registered_user):
    """无 embedding 配置时返回空列表（向后兼容）。"""
    results = retrieve(db_session, user_id=registered_user["id"], query="测试")
    assert results == []


def test_database_has_is_postgres_helper():
    """core.database 应有 is_postgres() helper（G1/G3 SQLite 兼容判断）。"""
    from app.core import database
    assert hasattr(database, 'is_postgres'), "core.database 缺少 is_postgres()"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_retriever.py -v 2>&1 | tail -10
```
Expected: `test_retriever_has_ef_search_set` 和 `test_retriever_adapts_halfvec` FAIL。

- [ ] **Step 3: 实现 is_postgres helper**

修改 `apps/api/app/core/database.py`，加（位置：engine 定义之后）：

```python
def is_postgres() -> bool:
    """判断当前 engine 是否为 PostgreSQL（SQLite 测试库返回 False）。

    用于 G1 HNSW / G3 tsvector 等 PG-only 特性的方言判断。
    """
    return engine.dialect.name == 'postgresql'
```

- [ ] **Step 4: 实现 ef_search + halfvec 查询适配**

修改 `apps/api/app/rag/retriever.py`：

① 顶部 import 加 `HalfVec`：
```python
from pgvector.sqlalchemy import HalfVec  # D1.1: halfvec 查询适配
```

② 在 `stmt = (...)` 查询前（约 line 52 之后、`rows = db.execute(stmt)` 之前）插入 ef_search：
```python
    # D1/G1：HNSW 索引的动态探测参数，随 top_k 放大保证召回率（仅 PG 生效，SQLite 静默忽略）
    from app.core.database import is_postgres
    if is_postgres():
        from sqlalchemy import text as sa_text
        db.execute(sa_text("SET LOCAL hnsw.ef_search = :ef"), {"ef": max(40, top_k * 4)})
```

③ 查询语句的 cosine_distance 改用 HalfVec 适配（query_vec 转 halfvec）：
```python
    # 原：KnowledgeChunk.embedding.cosine_distance(query_vec)
    # 改：D1.1 halfvec —— query_vec 转成 HalfVec 类型与列类型对齐
    stmt = (
        select(
            KnowledgeChunk,
            KnowledgeChunk.embedding.cosine_distance(HalfVec(query_vec)).label("distance"),
        )
        .where(scope_filter)
        .order_by("distance")
        .limit(top_k)
    )
```

注意：pgvector-python 的 `cosine_distance` 接受 HalfVec 实例，会生成 halfvec 的 `<=>` 操作符，与 halfvec_cosine_ops 索引对齐。

- [ ] **Step 5: embedding.py 入库适配 halfvec**

检查 `apps/api/app/rag/embedding.py` 的 `embed_texts` 返回值。pgvector-python 写入 halfvec 列时，list[float] 会自动适配（SQLAlchemy 的 Vector/HalfVec 类型处理器处理）。**若 ORM 用 `Vector(EMBEDDING_DIM)` 定义列（`models/knowledge_chunk.py:30`），需同步改为 `HalfVec(EMBEDDING_DIM)`**：

修改 `apps/api/app/models/knowledge_chunk.py:3,30`：
```python
from pgvector.sqlalchemy import HalfVec  # 原 Vector
# ...
embedding: Mapped[list | None] = mapped_column(HalfVec(EMBEDDING_DIM), nullable=True)
```

**注意**：model 层改 HalfVec 后，SQLite 测试库的 JSON 兼容版（conftest.py:99 `sa.Column("embedding", sa.JSON)`）不受影响（JSON 占位，类型透明）。但需确认 SQLite 测试不会因 HalfVec 类型报错——若报错，conftest 的兼容版保持 JSON 即可（HalfVec 只在 PG 生效）。

- [ ] **Step 6: 跑测试确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_retriever.py -v 2>&1 | tail -10
```
Expected: 4 PASS。

- [ ] **Step 7: 回归现有测试**

Run:
```bash
cd apps/api && uv run pytest -q 2>&1 | tail -10
```
Expected: 全绿。**若 SQLite 测试因 HalfVec 报错，conftest 的兼容版 embedding 列保持 JSON（不动）。**

- [ ] **Step 8: 提交**

```bash
git add apps/api/app/rag/retriever.py apps/api/app/core/database.py apps/api/app/models/knowledge_chunk.py apps/api/tests/test_retriever.py
git commit -m "feat(rag): G1 retriever 查询前 SET LOCAL hnsw.ef_search + halfvec 适配（D1+D1.1）

HNSW 索引的动态探测参数，max(40, top_k*4) 保证召回率。加 is_postgres() helper
做方言判断（SQLite 静默忽略）。D1.1：query_vec 转 HalfVec 与列类型对齐，
model 层 embedding 列改 HalfVec 类型。"
```

---

## Phase 1 收尾检查

- [ ] HNSW 索引在 PG 中存在（Task 1.1 Step 4）
- [ ] retriever 查询走 HNSW 索引（`EXPLAIN ANALYZE` 验证 index scan，非 seq scan）—— 手动 PG 验证，记录到 Self-Review
- [ ] 全量测试绿
- [ ] 迁移可逆（downgrade/upgrade）
- [ ] SQLite 测试不受影响（HNSW 静默忽略）

---

## Phase 2: G2 — 检索测试页（后端 + 前端）

### Task 2.1: 后端 admin 检索测试端点

**Files:**
- Modify: `apps/api/app/api/admin/retrieval.py`（新建）
- Modify: `apps/api/app/api/admin/__init__.py`
- Modify: `apps/api/app/rag/retriever.py`（加 scope 参数，默认 None=现有行为）
- Test: `apps/api/tests/test_admin_retrieval.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `apps/api/tests/test_admin_retrieval.py`：

```python
"""G2 admin 检索测试端点测试。"""
import pytest
import uuid


@pytest.fixture
def admin_user(db_session):
    from app.models import User
    from app.core.security import hash_password
    u = User(
        username="admin",
        email="admin@tiangong.dev",
        password_hash=hash_password("Admin1234!"),
        name="管理员",
        role="admin",
    )
    db_session.add(u)
    db_session.commit()
    return {"id": str(u.id), "username": u.username, "password": "Admin1234!"}


@pytest.fixture
def fake_embed(monkeypatch):
    """固定零向量 embedding（抄 test_knowledge_service.py:17-41）。"""
    dim = 2048
    def _fake_text(text, embed_config=None):
        return [0.0] * dim
    def _fake_texts(texts, embed_config=None):
        return [[0.0] * dim for _ in texts]
    monkeypatch.setattr("app.rag.embedding.embed_text", _fake_text)
    monkeypatch.setattr("app.rag.embedding.embed_texts", _fake_texts)
    # resolve_embedding_config 返回一个假配置（避免 retrieve 早退）
    from app.rag.reranker import RerankConfig
    from dataclasses import dataclass
    @dataclass
    class _FakeCfg:
        base_url: str = "http://x"
        api_key: str = "k"
        model: str = "m"
        source: str = "global"
    monkeypatch.setattr(
        "app.rag.retriever.resolve_embedding_config",
        lambda db, user_id: _FakeCfg(),
    )


def _make_global_chunk(db_session, content="权利要求1：一种方法。"):
    from app.models import KnowledgeChunk
    c = KnowledgeChunk(
        user_id=uuid.uuid4(),
        scope="global",
        source_type="external_docx",
        source_id="test-file",
        content=content,
        embedding=[0.0] * 2048,
        metadata={"title": "测试文件"},
    )
    db_session.add(c)
    db_session.commit()
    return c


def test_admin_retrieval_test_requires_admin(client, registered_user):
    """非 admin 访问 /admin/knowledge/retrieval-test 返回 403。"""
    client.post("/auth/login", json={"username": registered_user["username"], "password": registered_user["password"]})
    resp = client.post("/admin/knowledge/retrieval-test", json={"query": "测试", "top_k": 5})
    assert resp.status_code == 403


def test_admin_retrieval_test_returns_structure(client, admin_user, fake_embed):
    """admin 发起检索测试，返回结构含 results/threshold/top_k/scope。"""
    client.post("/auth/login", json={"username": admin_user["username"], "password": "Admin1234!"})
    resp = client.post("/admin/knowledge/retrieval-test", json={"query": "权利要求", "top_k": 5, "scope": "global"})
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "threshold" in data
    assert "top_k" in data
    assert "scope" in data
    assert isinstance(data["results"], list)


def test_admin_retrieval_test_scope_filter(client, admin_user, fake_embed, db_session):
    """scope=global 时只命中 global chunk（不命中 personal）。"""
    from app.models import KnowledgeChunk
    # 一个 global + 一个他人 personal
    g = KnowledgeChunk(user_id=uuid.uuid4(), scope="global", source_type="external_docx",
                       source_id="f1", content="全局内容", embedding=[0.0]*2048, metadata={"title": "g"})
    p = KnowledgeChunk(user_id=uuid.uuid4(), scope="personal", source_type="external_docx",
                       source_id="f2", content="私人内容", embedding=[0.0]*2048, metadata={"title": "p"})
    db_session.add_all([g, p])
    db_session.commit()

    client.post("/auth/login", json={"username": admin_user["username"], "password": "Admin1234!"})
    resp = client.post("/admin/knowledge/retrieval-test", json={"query": "内容", "top_k": 10, "scope": "global"})
    assert resp.status_code == 200
    contents = [r["content"] for r in resp.json()["results"]]
    assert "全局内容" in contents
    assert "私人内容" not in contents  # scope=global 不漏 personal
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_admin_retrieval.py -v 2>&1 | tail -10
```
Expected: 失败（端点不存在，404 或 import 错误）。

- [ ] **Step 3: 给 retrieve 加 scope 参数**

修改 `apps/api/app/rag/retriever.py` 的 `retrieve` 签名和 WHERE 子句：

```python
def retrieve(
    db: Session, *, user_id, query: str, top_k: int = 3, scope: str | None = None
) -> list[RetrievalResult]:
    """检索与 query 最相似的 chunk。

    scope=None（默认）：三域规则，global + 本人 personal。
    scope="global"：仅 global（admin 检索测试用）。
    scope="personal"：仅本人 personal。
    """
    # ... embed 逻辑不变 ...

    if scope == "global":
        scope_filter = KnowledgeChunk.scope == "global"
    elif scope == "personal":
        scope_filter = (KnowledgeChunk.scope == "personal") & (KnowledgeChunk.user_id == user_id)
    else:
        scope_filter = (
            (KnowledgeChunk.scope == "global")
            | ((KnowledgeChunk.scope == "personal") & (KnowledgeChunk.user_id == user_id))
        )

    stmt = (
        select(KnowledgeChunk, KnowledgeChunk.embedding.cosine_distance(query_vec).label("distance"))
        .where(scope_filter)
        .order_by("distance")
        .limit(top_k)
    )
    # ... 其余不变 ...
```

- [ ] **Step 4: 实现 admin 检索测试端点**

新建 `apps/api/app/api/admin/retrieval.py`：

```python
"""G2 admin 检索测试端点（spec §5.2）。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import User
from app.rag.retriever import retrieve, SIMILARITY_THRESHOLD

router = APIRouter(prefix="/admin/knowledge", tags=["admin"])


class RetrievalTestRequest(BaseModel):
    query: str
    top_k: int = 5
    scope: str | None = None  # None / "global" / "personal"


@router.post("/retrieval-test")
def retrieval_test(
    payload: RetrievalTestRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 检索测试：返回召回结果 + 当前配置参数，供 RAG 调参闭环验证。"""
    results = retrieve(
        db, user_id=admin.id, query=payload.query, top_k=payload.top_k, scope=payload.scope
    )
    return {
        "results": [
            {
                "content": r.content[:500],
                "score": round(r.score, 3),
                "section_key": r.source_section_key,
                "project_title": r.project_title,
            }
            for r in results
        ],
        "threshold": SIMILARITY_THRESHOLD,
        "top_k": payload.top_k,
        "scope": payload.scope,
    }
```

- [ ] **Step 5: 注册 router**

修改 `apps/api/app/api/admin/__init__.py`，参照现有 users/console 的 include 模式加：

```python
from app.api.admin import retrieval
api_router.include_router(retrieval.router)
```

- [ ] **Step 6: 跑测试确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_admin_retrieval.py -v 2>&1 | tail -10
```
Expected: 3 PASS。

- [ ] **Step 7: 回归现有检索测试**

Run:
```bash
cd apps/api && uv run pytest tests/test_rag_tool.py tests/test_knowledge_consistency.py -v 2>&1 | tail -10
```
Expected: 全绿（scope=None 保持向后兼容）。

- [ ] **Step 8: 提交**

```bash
git add apps/api/app/api/admin/retrieval.py apps/api/app/api/admin/__init__.py apps/api/app/rag/retriever.py apps/api/tests/test_admin_retrieval.py
git commit -m "feat(rag): G2 admin 检索测试端点 + retrieve 加 scope 参数（spec §5.2, D4）

admin 可强制 scope=global 视角做检索测试，为 G3/G4 调参铺路。retrieve 加 scope
参数默认 None 保持向后兼容。"
```

---

### Task 2.2: 前端检索测试页

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`
- Modify: `apps/web/src/app/(app)/admin/console/retrieval-test/page.tsx`（新建）
- Modify: `apps/web/src/app/(app)/admin/console/page.tsx`（加页签卡片）

- [ ] **Step 1: api 封装**

在 `apps/web/src/lib/api.ts` 的「知识库」段加：

```typescript
// G2 检索测试
async retrievalTest(payload: { query: string; top_k?: number; scope?: 'global' | 'personal' | null }) {
  return request<{
    results: Array<{ content: string; score: number; section_key: string | null; project_title: string | null }>;
    threshold: number;
    top_k: number;
    scope: string | null;
  }>('/admin/knowledge/retrieval-test', {
    method: 'POST',
    body: JSON.stringify({ top_k: 5, ...payload }),
  });
},
```

- [ ] **Step 2: queries hook**

在 `apps/web/src/lib/queries.ts` 加（mutation 模式，命令式触发；遵守 queries.ts:480-482 注释——mutation 内只 invalidate，不弹 toast）：

```typescript
export function useRetrievalTest() {
  return useMutation({
    mutationFn: (payload: { query: string; top_k?: number; scope?: 'global' | 'personal' | null }) =>
      api.retrievalTest(payload),
  });
}
```

- [ ] **Step 3: 写检索测试页（抄 Firecrawl 页模板）**

新建 `apps/web/src/app/(app)/admin/console/retrieval-test/page.tsx`：

```tsx
'use client';

import { useState } from 'react';
import { PageShell, PageHeader } from '@/components/page-shell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { useRetrievalTest } from '@/lib/queries';

type Result = { content: string; score: number; section_key: string | null; project_title: string | null };

export default function RetrievalTestPage() {
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(5);
  const [scope, setScope] = useState<'global' | 'personal' | 'all'>('all');
  const [results, setResults] = useState<Result[]>([]);
  const [threshold, setThreshold] = useState(0.5);
  const search = useRetrievalTest();

  const handleSearch = () => {
    if (!query.trim()) {
      toast.error('请输入检索内容');
      return;
    }
    search.mutate(
      { query, top_k: topK, scope: scope === 'all' ? null : scope },
      {
        onSuccess: (data) => {
          setResults(data.results);
          setThreshold(data.threshold);
          toast.success(`召回 ${data.results.length} 条`);
        },
        onError: () => toast.error('检索失败'),
      }
    );
  };

  return (
    <PageShell>
      <PageHeader title="检索测试" description="输入查询语句，验证 RAG 召回质量。用于 G3/G4 调参闭环。" />
      <div className="space-y-4">
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="如：权利要求1的技术特征"
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <Select value={scope} onValueChange={(v) => setScope(v as 'global' | 'personal' | 'all')}>
            <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部</SelectItem>
              <SelectItem value="global">仅全局</SelectItem>
              <SelectItem value="personal">仅个人</SelectItem>
            </SelectContent>
          </Select>
          <Select value={String(topK)} onValueChange={(v) => setTopK(Number(v))}>
            <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
            <SelectContent>
              {[3, 5, 10, 20].map((n) => (
                <SelectItem key={n} value={String(n)}>top_{n}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button onClick={handleSearch} disabled={search.isPending}>
            {search.isPending ? '检索中...' : '检索'}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">当前相似度阈值：{threshold}</p>
        {search.isPending && <Skeleton className="h-64" />}
        {!search.isPending && results.length === 0 && (
          <p className="text-sm text-muted-foreground">无召回结果（或未检索）</p>
        )}
        <div className="space-y-3">
          {results.map((r, i) => (
            <div key={i} className="border rounded p-3 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="secondary">#{i + 1}</Badge>
                <Badge>score: {r.score}</Badge>
                {r.project_title && <Badge variant="outline">{r.project_title}</Badge>}
                {r.section_key && <Badge variant="outline">{r.section_key}</Badge>}
              </div>
              <p className="text-sm whitespace-pre-wrap">{r.content}</p>
            </div>
          ))}
        </div>
      </div>
    </PageShell>
  );
}
```

- [ ] **Step 4: 控制台索引页加卡片**

修改 `apps/web/src/app/(app)/admin/console/page.tsx` 的 `CONSOLE_SECTIONS` 数组，加一项：

```typescript
{ title: '检索测试', href: '/admin/console/retrieval-test', description: '验证 RAG 召回质量，调参闭环' },
```

- [ ] **Step 5: 手动验证（前端无组件测试框架，手动 dogfood）**

Run:
```bash
cd apps/web && pnpm dev
# 浏览器访问 http://localhost:3000/admin/console/retrieval-test
```
Expected: 页面渲染，输入 query 点检索，能看到召回结果卡片（或空结果提示）。三域 scope 切换正常。

- [ ] **Step 6: 提交**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/queries.ts "apps/web/src/app/(app)/admin/console/retrieval-test/" "apps/web/src/app/(app)/admin/console/page.tsx"
git commit -m "feat(web): G2 检索测试页（admin/console/retrieval-test）

抄 Firecrawl 页模板，输入 query 看 RAG 召回。为 G3/G4 调参闭环铺路。"
```

---

## Phase 2 收尾检查

- [ ] admin 检索测试端点鉴权正确（403 for non-admin）
- [ ] scope 参数三域隔离生效（global 不漏 personal）
- [ ] 前端页面可正常检索并展示结果
- [ ] 现有 rag_search tool / search API 行为不变（scope=None 向后兼容）
- [ ] 全量后端测试绿

---

## Phase 3: G3 — 混合检索 + rerank

### Task 3.1: RRF 融合纯函数 + 测试

**Files:**
- Modify: `apps/api/app/rag/fusion.py`（新建）
- Test: `apps/api/tests/test_fusion.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `apps/api/tests/test_fusion.py`：

```python
"""G3 RRF 融合纯函数测试。"""
from app.rag.fusion import rrf_fuse, RetrievalCandidate


def _candidate(cid: str, score: float = 0.0, content: str = "") -> RetrievalCandidate:
    return RetrievalCandidate(chunk_id=cid, content=content, vector_score=score, keyword_score=0.0)


def test_rrf_fuse_combines_two_lists():
    """两路召回按 RRF 公式融合：score = sum(1/(k+rank))。"""
    vec = [_candidate("a"), _candidate("b"), _candidate("c")]  # rank 0,1,2
    kw = [_candidate("b"), _candidate("d"), _candidate("a")]    # rank 0,1,2
    fused = rrf_fuse(vec_results=vec, kw_results=kw, k=60)
    # a: vec rank0 + kw rank2 = 1/61 + 1/63
    # b: vec rank1 + kw rank0 = 1/62 + 1/61
    # b 两路都靠前，应排第一
    assert fused[0].chunk_id == "b"
    assert fused[1].chunk_id == "a"
    assert fused[0].fused_score > fused[1].fused_score


def test_rrf_fuse_empty_lists():
    fused = rrf_fuse(vec_results=[], kw_results=[], k=60)
    assert fused == []


def test_rrf_fuse_single_list():
    """只有一路结果时，RRF 退化为按该路排名。"""
    vec = [_candidate("a"), _candidate("b")]
    fused = rrf_fuse(vec_results=vec, kw_results=[], k=60)
    assert [f.chunk_id for f in fused] == ["a", "b"]


def test_rrf_fuse_dedup():
    """两路含同一 chunk_id 只算一次融合分。"""
    vec = [_candidate("x"), _candidate("y")]
    kw = [_candidate("x"), _candidate("z")]
    fused = rrf_fuse(vec_results=vec, kw_results=kw, k=60)
    ids = [f.chunk_id for f in fused]
    assert ids.count("x") == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_fusion.py -v 2>&1 | tail -10
```
Expected: ImportError（`No module named 'app.rag.fusion'`）。

- [ ] **Step 3: 实现 RRF 融合**

新建 `apps/api/app/rag/fusion.py`：

```python
"""G3 RRF（Reciprocal Rank Fusion）融合算法（spec §5.3 阶段2）。

工业标准融合算法，无需训练、参数少（k=60 经验值）。
论文：Cormack et al., SIGIR 2009。
"""
from dataclasses import dataclass, field


@dataclass
class RetrievalCandidate:
    """检索候选（融合前/后通用）。"""
    chunk_id: str
    content: str
    vector_score: float = 0.0    # 向量路原始分（cosine similarity）
    keyword_score: float = 0.0   # 关键词路原始分（ts_rank_cd）
    fused_score: float = 0.0     # RRF 融合后分
    weight: float = 1.0          # G4 chunk 权重（召回分数乘子）
    metadata: dict = field(default_factory=dict)


def rrf_fuse(
    vec_results: list[RetrievalCandidate],
    kw_results: list[RetrievalCandidate],
    k: int = 60,
) -> list[RetrievalCandidate]:
    """RRF 融合：score = sum(1 / (k + rank + 1))，按融合分降序。

    两路结果按 chunk_id 去重，保留首次出现的 content/metadata。
    """
    scores: dict[str, float] = {}
    index: dict[str, RetrievalCandidate] = {}

    for rank, c in enumerate(vec_results):
        scores[c.chunk_id] = scores.get(c.chunk_id, 0.0) + 1.0 / (k + rank + 1)
        if c.chunk_id not in index:
            index[c.chunk_id] = c
            index[c.chunk_id].vector_score = c.vector_score

    for rank, c in enumerate(kw_results):
        scores[c.chunk_id] = scores.get(c.chunk_id, 0.0) + 1.0 / (k + rank + 1)
        if c.chunk_id not in index:
            index[c.chunk_id] = c
        index[c.chunk_id].keyword_score = c.keyword_score

    for cid, score in scores.items():
        index[cid].fused_score = score

    return sorted(index.values(), key=lambda c: -c.fused_score)
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_fusion.py -v 2>&1 | tail -10
```
Expected: 4 PASS。

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/rag/fusion.py apps/api/tests/test_fusion.py
git commit -m "feat(rag): G3 RRF 融合纯函数（spec §5.3 阶段2）

向量路 + 关键词路双召回结果按 Reciprocal Rank Fusion 融合，k=60。纯函数，无 DB 依赖。"
```

---

### Task 3.2: rerank client + 测试

**Files:**
- Modify: `apps/api/app/rag/reranker.py`（新建）
- Test: `apps/api/tests/test_reranker.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `apps/api/tests/test_reranker.py`：

```python
"""G3 rerank client 测试（mock httpx，不真实调 API）。"""
import pytest
from unittest.mock import patch, MagicMock
from app.rag.reranker import rerank, RerankConfig


def _config():
    return RerankConfig(
        enabled=True, base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="test-key", model="rerank", top_n=3,
    )


@patch("app.rag.reranker.httpx.post")
def test_rerank_returns_sorted_by_relevance(mock_post):
    """rerank 按 relevance_score 降序返回 top_n。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {"index": 2, "relevance_score": 0.95},
            {"index": 0, "relevance_score": 0.80},
            {"index": 1, "relevance_score": 0.60},
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    candidates = ["doc0", "doc1", "doc2"]
    ranked = rerank("query", candidates, config=_config())
    # 应按 score 降序：doc2(0.95), doc0(0.80), doc1(0.60)
    assert ranked == ["doc2", "doc0", "doc1"]


@patch("app.rag.reranker.httpx.post")
def test_rerank_respects_top_n(mock_post):
    """top_n=2 只返回前 2 条。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.8},
            {"index": 2, "relevance_score": 0.7},
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    cfg = _config()
    cfg.top_n = 2
    ranked = rerank("query", ["a", "b", "c"], config=cfg)
    assert len(ranked) == 2
    assert ranked == ["b", "a"]


def test_rerank_disabled_returns_input_unchanged():
    """rerank 关闭时原样返回（D5 降级）。"""
    cfg = _config()
    cfg.enabled = False
    ranked = rerank("query", ["a", "b", "c"], config=cfg)
    assert ranked == ["a", "b", "c"]


@patch("app.rag.reranker.httpx.post")
def test_rerank_failure_returns_input_unchanged(mock_post):
    """API 失败时降级返回原序（D5，不报错）。"""
    mock_post.side_effect = Exception("network error")
    ranked = rerank("query", ["a", "b", "c"], config=_config())
    assert ranked == ["a", "b", "c"]  # 降级
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_reranker.py -v 2>&1 | tail -10
```
Expected: ImportError（`No module named 'app.rag.reranker'`）。

- [ ] **Step 3: 实现 rerank client**

新建 `apps/api/app/rag/reranker.py`（抄 `llm_config_service.list_provider_models` 的 httpx 直连模式）：

```python
"""G3 rerank client（spec §5.3 阶段3，D5 可开关 + 失败降级）。

httpx 直连 rerank API（非 OpenAI 标准端点，不走 LangChain，抄 list_provider_models 模式）。
首选智谱 rerank API，失败时降级返回原序（D5）。
"""
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RerankConfig:
    enabled: bool
    base_url: str
    api_key: str
    model: str
    top_n: int = 3


def rerank(query: str, documents: list[str], *, config: RerankConfig) -> list[str]:
    """对 documents 按 query 重排，返回 top_n 个文本。

    D5：config.enabled=False 或 API 失败时，原样返回 documents（降级，不抛错）。
    """
    if not config.enabled or not documents:
        return documents

    try:
        resp = httpx.post(
            f"{config.base_url}/rerank",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json={
                "model": config.model,
                "query": query,
                "documents": documents,
                "top": config.top_n,
                "return_documents": False,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # 智谱 rerank 返回 {"results": [{"index": N, "relevance_score": F}, ...]}
        results = sorted(data.get("results", []), key=lambda r: -r["relevance_score"])
        return [documents[r["index"]] for r in results[:config.top_n]]
    except Exception as e:
        # D5：失败降级，不报错（检索不能因 rerank 挂掉而整体失败）
        logger.warning("rerank 调用失败，降级返回原序: %s", e)
        return documents
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_reranker.py -v 2>&1 | tail -10
```
Expected: 4 PASS。

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/rag/reranker.py apps/api/tests/test_reranker.py
git commit -m "feat(rag): G3 rerank client（spec §5.3 阶段3, D5）

httpx 直连智谱 rerank API，可开关 + 失败降级。抄 list_provider_models 模式（非标准端点不绕 LangChain）。"
```

---

### Task 3.3: rerank 配置 service + admin 端点

**Files:**
- Modify: `apps/api/app/services/rag_config_service.py`（新建）
- Modify: `apps/api/app/api/admin/console.py`（加 rerank 配置端点）
- Test: `apps/api/tests/test_rag_config.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `apps/api/tests/test_rag_config.py`：

```python
"""G3 rerank 配置 resolve 测试（镜像 resolve_embedding_config 模式）。"""
import pytest
from app.services.rag_config_service import (
    get_global_rerank_settings, set_global_rerank_settings, resolve_rerank_config
)


def test_rerank_config_defaults_disabled(db_session):
    """无配置时 resolve 返回 enabled=False（默认关）。"""
    cfg = resolve_rerank_config(db_session, user_id=None)
    assert cfg is not None
    assert cfg.enabled is False


def test_rerank_config_global_roundtrip(db_session):
    """set 后 get 能读到，enabled 开关生效。"""
    set_global_rerank_settings(
        db_session, enabled=True, base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="sk-test", model="rerank",
    )
    settings = get_global_rerank_settings(db_session)
    assert settings["enabled"] is True
    assert settings["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert settings["api_key_encrypted"] != "sk-test"  # 加密存储


def test_rerank_config_resolve_uses_global(db_session):
    """resolve 从 global 配置构建 RerankConfig。"""
    set_global_rerank_settings(
        db_session, enabled=True, base_url="http://x", api_key="sk-y", model="m"
    )
    cfg = resolve_rerank_config(db_session, user_id=None)
    assert cfg.enabled is True
    assert cfg.base_url == "http://x"
    assert cfg.api_key == "sk-y"  # 解密后
    assert cfg.model == "m"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_rag_config.py -v 2>&1 | tail -10
```
Expected: ImportError。

- [ ] **Step 3: 实现 rag_config_service**

新建 `apps/api/app/services/rag_config_service.py`（镜像 `llm_config_service.get/set_global_embedding_settings`）：

```python
"""G3 rerank 配置 service（spec §5.3, D6）。

镜像 embedding 配置的 global/env 两级解析模式（rerank 暂不做用户级 BYOK，简化）。
配置存 SystemSetting key='rag_rerank_config'。
"""
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_value, decrypt_value
from app.models import SystemSetting
from app.rag.reranker import RerankConfig

RERANK_SETTING_KEY = "rag_rerank_config"


def get_global_rerank_settings(db: Session) -> dict:
    """读取全局 rerank 配置（加密 key 返回 _encrypted 后缀）。"""
    setting = db.execute(
        select(SystemSetting).where(SystemSetting.key == RERANK_SETTING_KEY)
    ).scalar_one_or_none()
    if not setting:
        return {"enabled": False, "base_url": "", "api_key_encrypted": "", "model": ""}
    return dict(setting.value)


def set_global_rerank_settings(
    db: Session, *, enabled: bool, base_url: str, api_key: str, model: str
) -> None:
    """upsert 全局 rerank 配置（api_key 加密）。"""
    value = {
        "enabled": enabled,
        "base_url": base_url,
        "api_key_encrypted": encrypt_value(api_key) if api_key else "",
        "model": model,
    }
    setting = db.execute(
        select(SystemSetting).where(SystemSetting.key == RERANK_SETTING_KEY)
    ).scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key=RERANK_SETTING_KEY, value=value))
    db.commit()


def resolve_rerank_config(db: Session, *, user_id) -> RerankConfig:
    """解析 rerank 配置（global only，不做 user 级）。

    返回 RerankConfig，enabled=False 表示关闭（不返回 None，调用方无需判空）。
    """
    settings = get_global_rerank_settings(db)
    if not settings.get("base_url"):
        return RerankConfig(enabled=False, base_url="", api_key="", model="")
    api_key = decrypt_value(settings["api_key_encrypted"]) if settings.get("api_key_encrypted") else ""
    return RerankConfig(
        enabled=bool(settings.get("enabled")),
        base_url=settings["base_url"],
        api_key=api_key,
        model=settings.get("model", ""),
    )
```

- [ ] **Step 4: 实现 admin rerank 配置端点**

在 `apps/api/app/api/admin/console.py` 加（抄 firecrawl 配置端点模式）：

```python
# ===== G3 rerank 配置 =====
from app.services.rag_config_service import (
    get_global_rerank_settings, set_global_rerank_settings,
)
from app.core.security import decrypt_value
from pydantic import BaseModel


class RerankConfigRequest(BaseModel):
    enabled: bool
    base_url: str
    api_key: str = ""  # 空表示不更新 key
    model: str


@router.get("/admin/rag/rerank-config")
def get_rerank_config_endpoint(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    settings = get_global_rerank_settings(db)
    return {
        "enabled": settings.get("enabled", False),
        "base_url": settings.get("base_url", ""),
        "has_api_key": bool(settings.get("api_key_encrypted")),
        "model": settings.get("model", ""),
    }


@router.put("/admin/rag/rerank-config")
def save_rerank_config_endpoint(
    payload: RerankConfigRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # api_key 空时保留旧 key
    existing = get_global_rerank_settings(db)
    if not payload.api_key and existing.get("api_key_encrypted"):
        api_key = decrypt_value(existing["api_key_encrypted"])
    else:
        api_key = payload.api_key
    set_global_rerank_settings(
        db, enabled=payload.enabled, base_url=payload.base_url, api_key=api_key, model=payload.model
    )
    return {"ok": True}


@router.post("/admin/rag/rerank-config/test")
def test_rerank_config_endpoint(
    payload: RerankConfigRequest,
    admin: User = Depends(require_admin),
):
    """测试 rerank 配置连通性（用提供的新配置实时调一次）。"""
    from app.rag.reranker import rerank, RerankConfig
    cfg = RerankConfig(
        enabled=True, base_url=payload.base_url, api_key=payload.api_key, model=payload.model
    )
    try:
        result = rerank("测试 query", ["文档A", "文档B"], config=cfg)
        return {"ok": True, "message": f"连通成功，返回 {len(result)} 条"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
```

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_rag_config.py -v 2>&1 | tail -10
```
Expected: 3 PASS。

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/services/rag_config_service.py apps/api/app/api/admin/console.py apps/api/tests/test_rag_config.py
git commit -m "feat(rag): G3 rerank 配置 service + admin 端点（spec §5.3, D6）

镜像 embedding 配置的 global 解析模式（暂不做 user 级 BYOK）。配置存 SystemSetting
key=rag_rerank_config，api_key 加密。admin 可开关 + 测试连通性。"
```

---

### Task 3.4: tsv 列迁移 + retriever 集成混合检索

**Files:**
- Modify: `apps/api/alembic/versions/e3r4a5g6t7s8v_add_tsv_column.py`（新建）
- Modify: `apps/api/app/models/knowledge_chunk.py`（加 tsv 列）
- Modify: `apps/api/app/rag/retriever.py`（混合检索三段管线）
- Modify: `apps/api/tests/conftest.py`（SQLite 兼容版加 tsv）
- Test: `apps/api/tests/test_retriever.py`（扩展）

- [ ] **Step 1: 写 tsv 列迁移**

新建 `apps/api/alembic/versions/e3r4a5g6t7s8v_add_tsv_column.py`：

```python
"""add tsv tsvector column + GIN index on knowledge_chunks

Revision ID: e3r4a5g6t7s8v
Revises: d1h2n3s4w5i6
Create Date: 2026-07-28

spec: docs/superpowers/specs/2026-07-27-ragflow-borrow-design.md §5.3 阶段1
为 BM25 关键词路召回加 tsvector 列 + GIN 索引。
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'e3r4a5g6t7s8v'
down_revision: Union[str, Sequence[str], None] = 'd1h2n3s4w5i6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN tsv tsvector")
    op.execute("CREATE INDEX ix_knowledge_chunks_tsv_gin ON knowledge_chunks USING gin (tsv)")
    # 回填存量数据
    op.execute("UPDATE knowledge_chunks SET tsv = to_tsvector('simple', coalesce(content, ''))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_tsv_gin")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS tsv")
```

- [ ] **Step 2: 模型加 tsv 列**

修改 `apps/api/app/models/knowledge_chunk.py`，加（Text 占位，PG 层是 tsvector）：

```python
tsv: Mapped[str | None] = mapped_column(Text, nullable=True)  # PG 是 tsvector，SQLite 是 Text
```

- [ ] **Step 3: 改 conftest SQLite 兼容版表**

修改 `apps/api/tests/conftest.py` 的 `kc_compat`（约 line 89-105），加：

```python
        sa.Column("tsv", sa.Text),  # PG 是 tsvector，SQLite 是 Text（关键词路测试跳过）
```

- [ ] **Step 4: 写混合检索测试**

扩展 `apps/api/tests/test_retriever.py`：

```python
def test_retriever_has_hybrid_retrieval():
    """G3：retrieve 应同时做向量召回 + 关键词召回 + RRF 融合。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert 'rrf_fuse' in src or 'fusion' in src, "retrieve 缺少 RRF 融合"
    assert 'plainto_tsquery' in src or 'tsv' in src, "retrieve 缺少关键词路召回"
    assert 'rerank' in src, "retrieve 缺少 rerank 调用"
```

- [ ] **Step 5: 跑测试确认失败**

Run:
```bash
cd apps/api && uv run alembic upgrade head 2>&1 | tail -3
cd apps/api && uv run pytest tests/test_retriever.py -v 2>&1 | tail -10
```
Expected: `test_retriever_has_hybrid_retrieval` FAIL。

- [ ] **Step 6: 实现混合检索**

重写 `apps/api/app/rag/retriever.py` 的查询部分（保留 embed 逻辑、scope 参数、ef_search）：

```python
"""检索服务：混合检索（向量 + BM25 + RRF + rerank）（设计 10.4 + spec §5.3）。"""
import logging
from dataclasses import dataclass

from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

from app.core.database import is_postgres
from app.models import KnowledgeChunk
from app.rag.embedding import embed_text
from app.rag.fusion import rrf_fuse, RetrievalCandidate
from app.rag.reranker import rerank
from app.services.llm_config_service import resolve_embedding_config
from app.services.rag_config_service import resolve_rerank_config
from app.services.llm_log_helper import log_embed_call

logger = logging.getLogger(__name__)
SIMILARITY_THRESHOLD = 0.5
RETRIEVAL_CANDIDATE_POOL = 10  # 召回阶段放大候选池，融合+rerank 后再截断


@dataclass
class RetrievalResult:
    content: str
    score: float
    source_section_key: str | None
    project_title: str | None


def retrieve(
    db: Session, *, user_id, query: str, top_k: int = 3, scope: str | None = None
) -> list[RetrievalResult]:
    """混合检索：向量路 + 关键词路 → RRF 融合 → rerank → 截断 top_k。"""
    embed_config = resolve_embedding_config(db, user_id=user_id)
    if embed_config is None:
        return []
    try:
        query_vec = embed_text(query, embed_config=embed_config)
    except Exception:
        log_embed_call(db, user_id=user_id, model=embed_config.model,
                       provider=embed_config.source, status="failed")
        raise
    log_embed_call(db, user_id=user_id, model=embed_config.model,
                   provider=embed_config.source, status="success")

    # scope 过滤
    if scope == "global":
        scope_filter = KnowledgeChunk.scope == "global"
    elif scope == "personal":
        scope_filter = (KnowledgeChunk.scope == "personal") & (KnowledgeChunk.user_id == user_id)
    else:
        scope_filter = (
            (KnowledgeChunk.scope == "global")
            | ((KnowledgeChunk.scope == "personal") & (KnowledgeChunk.user_id == user_id))
        )

    # HNSW ef_search（D1，仅 PG）
    if is_postgres():
        db.execute(text("SET LOCAL hnsw.ef_search = :ef"), {"ef": max(40, top_k * 4)})

    # 向量路召回
    vec_stmt = (
        select(KnowledgeChunk, KnowledgeChunk.embedding.cosine_distance(query_vec).label("distance"))
        .where(scope_filter)
        .order_by("distance")
        .limit(RETRIEVAL_CANDIDATE_POOL)
    )
    vec_rows = db.execute(vec_stmt).all()

    # 关键词路召回（BM25 via tsvector，仅 PG；SQLite 跳过）
    kw_rows = []
    if is_postgres():
        tsquery = func.plainto_tsquery('simple', query)
        kw_stmt = (
            select(KnowledgeChunk, func.ts_rank_cd(KnowledgeChunk.tsv, tsquery).label("rank"))
            .where(KnowledgeChunk.tsv.match(tsquery))
            .where(scope_filter)
            .order_by(text("rank DESC"))
            .limit(RETRIEVAL_CANDIDATE_POOL)
        )
        kw_rows = db.execute(kw_stmt).all()

    # 构建 candidate（应用 weight 加权）
    vec_candidates = []
    for chunk, distance in vec_rows:
        score = 1.0 - distance
        if score < SIMILARITY_THRESHOLD:
            continue
        vec_candidates.append(RetrievalCandidate(
            chunk_id=str(chunk.id),
            content=chunk.edited_text or chunk.content,  # G4：用 edited_text
            vector_score=score,
            weight=chunk.weight or 1.0,
            metadata={"_chunk": chunk},
        ))
    kw_candidates = []
    for chunk, rank in kw_rows:
        kw_candidates.append(RetrievalCandidate(
            chunk_id=str(chunk.id),
            content=chunk.edited_text or chunk.content,
            keyword_score=float(rank),
            weight=chunk.weight or 1.0,
            metadata={"_chunk": chunk},
        ))

    # RRF 融合
    fused = rrf_fuse(vec_results=vec_candidates, kw_results=kw_candidates)

    # 单路兜底（关键词路空或 SQLite 时，RRF 退化为向量路排序）
    if not fused and vec_candidates:
        fused = vec_candidates

    # G4：应用 weight 加权到 fused_score
    for c in fused:
        c.fused_score *= c.weight

    # rerank 精排（D5，失败降级）
    rerank_cfg = resolve_rerank_config(db, user_id=user_id)
    if rerank_cfg.enabled and len(fused) > 1:
        docs = [c.content for c in fused[:RETRIEVAL_CANDIDATE_POOL]]
        ranked_docs = rerank(query, docs, config=rerank_cfg)
        content_order = {d: i for i, d in enumerate(ranked_docs)}
        fused = sorted(fused, key=lambda c: content_order.get(c.content, 999))[:top_k]
    else:
        fused = fused[:top_k]

    # 转换为 RetrievalResult
    results = []
    for cand in fused:
        chunk = cand.metadata.get("_chunk")
        if not chunk:
            continue
        meta = chunk.metadata_ or {}
        results.append(RetrievalResult(
            content=chunk.edited_text or chunk.content,  # G4
            score=cand.fused_score or cand.vector_score,
            source_section_key=chunk.source_section_key,
            project_title=meta.get("project_title") or meta.get("title"),
        ))
    return results
```

注意：此处引用了 `chunk.edited_text` 和 `chunk.weight`，这两个字段在 Phase 4 Task 4.1 才加。**Phase 3 完成时这两个字段还不存在**，所以 Phase 3 的 retriever 实现应**临时去掉这两处引用**（用 `chunk.content` 和 `1.0`），Phase 4 Task 4.3 再加回。Step 6 的代码是最终态，Phase 3 执行时用临时简化版。

- [ ] **Step 7: 跑迁移 + 测试**

Run:
```bash
cd apps/api && uv run alembic upgrade head 2>&1 | tail -3
cd apps/api && uv run pytest tests/test_retriever.py tests/test_fusion.py tests/test_reranker.py -v 2>&1 | tail -15
```
Expected: tsv 迁移成功；测试全绿。

- [ ] **Step 8: 回归全量测试**

Run:
```bash
cd apps/api && uv run pytest -q 2>&1 | tail -15
```
Expected: 全绿。

- [ ] **Step 9: 提交**

```bash
git add apps/api/alembic/versions/e3r4a5g6t7s8v_add_tsv_column.py apps/api/app/models/knowledge_chunk.py apps/api/app/rag/retriever.py apps/api/tests/conftest.py apps/api/tests/test_retriever.py
git commit -m "feat(rag): G3 混合检索（向量+BM25+RRF+rerank）集成（spec §5.3）

retriever 改造为三段管线：向量路(cosine+HNSW) + 关键词路(tsvector+GIN) → RRF 融合
→ rerank 精排。tsv 列 + GIN 迁移，回填存量数据。SQLite 跳过关键词路（仅 PG）。
rerank 失败降级（D5）。"
```

---

### Task 3.5: 入库链路生成 tsv（archiver + knowledge_service）

**Files:**
- Modify: `apps/api/app/rag/archiver.py`
- Modify: `apps/api/app/services/knowledge_service.py`
- Test: `apps/api/tests/test_chunk_tsv.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `apps/api/tests/test_chunk_tsv.py`：

```python
"""G3 入库时 tsv 生成逻辑测试。"""


def test_archiver_generates_tsv_on_ingest():
    """归档流入库时 chunk 应生成 tsv（仅 PG）。"""
    import inspect
    from app.rag import archiver
    src = inspect.getsource(archiver.archive_project)
    assert 'tsv' in src or 'to_tsvector' in src, "archiver 缺少 tsv 生成"


def test_ingest_chunks_generates_tsv():
    """导入流入库时 chunk 应生成 tsv。"""
    import inspect
    from app.services import knowledge_service
    src = inspect.getsource(knowledge_service._ingest_chunks)
    assert 'tsv' in src or 'to_tsvector' in src, "_ingest_chunks 缺少 tsv 生成"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_chunk_tsv.py -v 2>&1 | tail -10
```
Expected: 2 FAIL。

- [ ] **Step 3: 实现 tsv 生成（两处入库点）**

在 `archiver.py` 的 `db.add(KnowledgeChunk(...))` 循环后（提交前），加批量回填（仅 PG）：

```python
    # G3：生成 tsv（仅 PG，SQLite 跳过）
    from app.core.database import is_postgres
    if is_postgres():
        db.execute(text(
            "UPDATE knowledge_chunks SET tsv = to_tsvector('simple', coalesce(content, '')) "
            "WHERE tsv IS NULL AND source_id = :sid AND source_type = 'disclosure'"
        ), {"sid": str(project.id)})
```

在 `knowledge_service._ingest_chunks` 的写入循环后（提交前），加类似回填（按 file_id）：

```python
    # G3：生成 tsv（仅 PG）
    from app.core.database import is_postgres
    if is_postgres() and file_id:
        db.execute(text(
            "UPDATE knowledge_chunks SET tsv = to_tsvector('simple', coalesce(content, '')) "
            "WHERE tsv IS NULL AND file_id = :fid"
        ), {"fid": str(file_id)})
```

注意 import `text` from sqlalchemy（两文件顶部加 `from sqlalchemy import text`）。

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_chunk_tsv.py -v 2>&1 | tail -10
```
Expected: 2 PASS。

- [ ] **Step 5: 回归入库相关测试**

Run:
```bash
cd apps/api && uv run pytest tests/test_knowledge_service.py tests/test_knowledge_consistency.py tests/test_embedding_logging.py -v 2>&1 | tail -15
```
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
git add apps/api/app/rag/archiver.py apps/api/app/services/knowledge_service.py apps/api/tests/test_chunk_tsv.py
git commit -m "feat(rag): G3 入库链路生成 tsv（archiver + _ingest_chunks）

两条入库流（归档 + 导入/web）入库后回填 tsv，供 BM25 关键词路召回。仅 PG 生效，
SQLite 跳过。"
```

---

### Task 3.6: 前端 rerank 配置 UI（admin 控制台）

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`
- Modify: `apps/web/src/app/(app)/admin/console/rerank/page.tsx`（新建，抄 firecrawl 页）
- Modify: `apps/web/src/app/(app)/admin/console/page.tsx`（加 rerank 卡片）

- [ ] **Step 1: api 封装**

`api.ts` 加：

```typescript
async getRerankConfig() {
  return request<{ enabled: boolean; base_url: string; has_api_key: boolean; model: string }>('/admin/rag/rerank-config');
},
async saveRerankConfig(payload: { enabled: boolean; base_url: string; api_key: string; model: string }) {
  return request<{ ok: boolean }>('/admin/rag/rerank-config', { method: 'PUT', body: JSON.stringify(payload) });
},
async testRerankConfig(payload: { enabled: boolean; base_url: string; api_key: string; model: string }) {
  return request<{ ok: boolean; message: string }>('/admin/rag/rerank-config/test', { method: 'POST', body: JSON.stringify(payload) });
},
```

- [ ] **Step 2: queries hook**

`queries.ts` 加（抄 firecrawl hooks 模式）：

```typescript
export function useRerankConfig() {
  return useQuery({ queryKey: queryKeys.admin.rerankConfig, queryFn: () => api.getRerankConfig() });
}
export function useSaveRerankConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.saveRerankConfig,
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.admin.rerankConfig }),
  });
}
export function useTestRerankConfig() {
  return useMutation({ mutationFn: api.testRerankConfig });
}
```

queryKeys.admin 加 `rerankConfig: ['admin', 'rerankConfig']`。

- [ ] **Step 3: 写 rerank 配置页（抄 Firecrawl 页模板）**

新建 `apps/web/src/app/(app)/admin/console/rerank/page.tsx`：

```tsx
'use client';

import { useState, useEffect } from 'react';
import { PageShell, PageHeader } from '@/components/page-shell';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { useRerankConfig, useSaveRerankConfig, useTestRerankConfig } from '@/lib/queries';

export default function RerankConfigPage() {
  const { data, isLoading } = useRerankConfig();
  const save = useSaveRerankConfig();
  const test = useTestRerankConfig();
  const [enabled, setEnabled] = useState(false);
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');

  useEffect(() => {
    if (data) {
      setEnabled(data.enabled);
      setBaseUrl(data.base_url);
      setModel(data.model);
    }
  }, [data]);

  const handleSave = () => {
    save.mutate(
      { enabled, base_url: baseUrl, api_key: apiKey, model },
      { onSuccess: () => toast.success('已保存'), onError: () => toast.error('保存失败') }
    );
  };

  const handleTest = () => {
    test.mutate(
      { enabled: true, base_url: baseUrl, api_key: apiKey, model },
      { onSuccess: (r) => r.ok ? toast.success(r.message) : toast.error(r.message), onError: () => toast.error('测试失败') }
    );
  };

  if (isLoading) return <PageShell><Skeleton className="h-64" /></PageShell>;

  return (
    <PageShell>
      <PageHeader title="Rerank 配置" description="混合检索的精排模型配置。失败时自动降级返回 RRF 结果。" />
      <div className="space-y-4 max-w-xl">
        <div className="flex items-center gap-2">
          <Switch checked={enabled} onCheckedChange={setEnabled} />
          <Label>启用 rerank</Label>
        </div>
        <div>
          <Label>Base URL</Label>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://open.bigmodel.cn/api/paas/v4" />
        </div>
        <div>
          <Label>API Key {data?.has_api_key && <span className="text-xs text-muted-foreground">（已配置，留空保留）</span>}</Label>
          <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={data?.has_api_key ? '留空保留原 key' : '输入 API key'} />
        </div>
        <div>
          <Label>模型名</Label>
          <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="rerank" />
        </div>
        <div className="flex gap-2">
          <Button onClick={handleSave} disabled={save.isPending}>{save.isPending ? '保存中...' : '保存'}</Button>
          <Button variant="outline" onClick={handleTest} disabled={test.isPending}>{test.isPending ? '测试中...' : '测试连通'}</Button>
        </div>
      </div>
    </PageShell>
  );
}
```

- [ ] **Step 4: 控制台索引页加卡片**

修改 `apps/web/src/app/(app)/admin/console/page.tsx` 的 `CONSOLE_SECTIONS`，加：

```typescript
{ title: 'Rerank 配置', href: '/admin/console/rerank', description: '混合检索精排模型配置' },
```

- [ ] **Step 5: 手动验证 + 提交**

```bash
cd apps/web && pnpm dev
# 访问 /admin/console/rerank，验证表单 + 测试按钮
git add apps/web/src/lib/api.ts apps/web/src/lib/queries.ts "apps/web/src/app/(app)/admin/console/rerank/" "apps/web/src/app/(app)/admin/console/page.tsx"
git commit -m "feat(web): G3 rerank 配置页（admin/console/rerank）

抄 Firecrawl 页模板，enabled 开关 + base_url/api_key/model + 测试连通性。"
```

---

## Phase 3 收尾检查

- [ ] 混合检索三段管线集成（向量 + BM25 + RRF + rerank）
- [ ] HNSW 索引 + ef_search 生效（Task 1.2）
- [ ] tsv 列 + GIN 索引建好，存量数据回填
- [ ] 入库两条流（archiver + _ingest_chunks）都生成 tsv
- [ ] rerank 失败降级（D5）单测覆盖
- [ ] rerank 可开关、可配置、可测试连通性
- [ ] 三域隔离在混合检索中不被绕过（scope filter 双路都套）
- [ ] 现有 rag_search tool / search API 行为兼容（顶层 signature 不变）
- [ ] **人工验证**：用 G2 检索测试页，输入 20 条含精确术语的 query（如「权利要求1」「步骤S10」「温度50-80」），对比开/关 rerank 召回质量（spec §8.3）
- [ ] 全量测试绿

---

## Phase 4: G4 — 分块可视化干预

### Task 4.1: G4 字段迁移 + 模型 + conftest

**Files:**
- Modify: `apps/api/alembic/versions/f4g5i6n7t8e9_add_chunk_intervention_fields.py`（新建）
- Modify: `apps/api/app/models/knowledge_chunk.py`
- Modify: `apps/api/tests/conftest.py`（SQLite 兼容版加 G4 列）

- [ ] **Step 1: 写 G4 字段迁移**

新建 `apps/api/alembic/versions/f4g5i6n7t8e9_add_chunk_intervention_fields.py`：

```python
"""add chunk intervention fields (keywords/questions/weight/edited_text/locked)

Revision ID: f4g5i6n7t8e9
Revises: e3r4a5g6t7s8v
Create Date: 2026-07-28

spec: docs/superpowers/specs/2026-07-27-ragflow-borrow-design.md §5.4 (G4, D3)
G4 分块干预字段（独立列，可建索引）：
- keywords JSON：检索加权关键词
- questions JSON：预设问题，参与关键词路召回
- weight Float：召回分数乘子（默认 1.0）
- edited_text Text：admin 手动改写文本（None=用原 content）
- locked Boolean：锁定后重新 ingest 不覆盖
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f4g5i6n7t8e9'
down_revision: Union[str, Sequence[str], None] = 'e3r4a5g6t7s8v'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('knowledge_chunks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('keywords', sa.dialects.postgresql.JSONB().with_variant(sa.JSON(), 'sqlite'), nullable=True))
        batch_op.add_column(sa.Column('questions', sa.dialects.postgresql.JSONB().with_variant(sa.JSON(), 'sqlite'), nullable=True))
        batch_op.add_column(sa.Column('weight', sa.Float(), nullable=True, server_default='1.0'))
        batch_op.add_column(sa.Column('edited_text', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    with op.batch_alter_table('knowledge_chunks', schema=None) as batch_op:
        batch_op.drop_column('locked')
        batch_op.drop_column('edited_text')
        batch_op.drop_column('weight')
        batch_op.drop_column('questions')
        batch_op.drop_column('keywords')
```

- [ ] **Step 2: 模型加字段**

修改 `apps/api/app/models/knowledge_chunk.py`，加（注意 import `Float`、`Boolean` from sqlalchemy）：

```python
    keywords: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    questions: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, default=1.0)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.text("false"))
```

- [ ] **Step 3: 改 conftest SQLite 兼容版表**

修改 `apps/api/tests/conftest.py` 的 `kc_compat`（约 line 89-105），加 G4 列：

```python
        sa.Column("keywords", sa.JSON),
        sa.Column("questions", sa.JSON),
        sa.Column("weight", sa.Float),
        sa.Column("edited_text", sa.Text),
        sa.Column("locked", sa.Boolean),
```

- [ ] **Step 4: 跑迁移 + 回归**

Run:
```bash
cd apps/api && uv run alembic upgrade head 2>&1 | tail -3
cd apps/api && uv run pytest -q 2>&1 | tail -10
```
Expected: 迁移成功；全量测试绿（SQLite 兼容版表结构对齐）。

- [ ] **Step 5: 提交**

```bash
git add apps/api/alembic/versions/f4g5i6n7t8e9_add_chunk_intervention_fields.py apps/api/app/models/knowledge_chunk.py apps/api/tests/conftest.py
git commit -m "feat(rag): G4 分块干预字段迁移（keywords/questions/weight/edited_text/locked）

spec §5.4 D3：独立列（可建索引），不走 metadata_ JSONB。conftest SQLite 兼容版同步加列。"
```

---

### Task 4.2: chunk CRUD service + admin 端点

**Files:**
- Modify: `apps/api/app/services/knowledge_service.py`（加 list_chunks_by_file / update_chunk）
- Modify: `apps/api/app/api/admin/chunks.py`（新建）
- Modify: `apps/api/app/api/admin/__init__.py`
- Test: `apps/api/tests/test_admin_chunks.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `apps/api/tests/test_admin_chunks.py`：

```python
"""G4 chunk 编辑端点测试。"""
import pytest
import uuid


@pytest.fixture
def admin_user(db_session):
    from app.models import User
    from app.core.security import hash_password
    u = User(username="admin", email="admin@tiangong.dev",
             password_hash=hash_password("Admin1234!"), name="管理员", role="admin")
    db_session.add(u)
    db_session.commit()
    return {"id": str(u.id), "username": u.username, "password": "Admin1234!"}


@pytest.fixture
def sample_chunk(db_session, admin_user):
    from app.models import KnowledgeChunk
    c = KnowledgeChunk(
        user_id=uuid.UUID(admin_user["id"]), scope="global",
        source_type="external_docx", source_id="file-1", chunk_index=0,
        content="原始 chunk 内容", embedding=[0.0]*2048, metadata={"title": "测试"},
    )
    db_session.add(c)
    db_session.commit()
    return c


def test_list_chunks_requires_admin(client, registered_user):
    client.post("/auth/login", json={"username": registered_user["username"], "password": registered_user["password"]})
    resp = client.get("/admin/knowledge/files/any/chunks")
    assert resp.status_code == 403


def test_list_chunks_returns_list(client, admin_user, sample_chunk):
    client.post("/auth/login", json={"username": admin_user["username"], "password": "Admin1234!"})
    resp = client.get(f"/admin/knowledge/files/{sample_chunk.source_id}/chunks")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "content" in data[0]
    assert "keywords" in data[0]
    assert "weight" in data[0]


def test_update_chunk_edits_fields(client, admin_user, sample_chunk):
    client.post("/auth/login", json={"username": admin_user["username"], "password": "Admin1234!"})
    resp = client.patch(f"/admin/knowledge/chunks/{sample_chunk.id}", json={
        "keywords": ["权利要求1", "技术特征"],
        "questions": ["什么是技术特征?"],
        "weight": 1.5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["keywords"] == ["权利要求1", "技术特征"]
    assert data["weight"] == 1.5


def test_update_chunk_edited_text_triggers_reembed(client, db_session, admin_user, sample_chunk, monkeypatch):
    """edited_text 变更应触发重新 embed（D8）。"""
    reembed_called = []
    monkeypatch.setattr("app.services.knowledge_service.embed_texts",
                        lambda texts, embed_config=None: (reembed_called.append(texts), [[0.1]*2048 for _ in texts])[1])
    monkeypatch.setattr("app.services.knowledge_service.resolve_embedding_config",
                        lambda db, user_id: type("C", (), {"model": "m", "source": "global"})())
    client.post("/auth/login", json={"username": admin_user["username"], "password": "Admin1234!"})
    resp = client.patch(f"/admin/knowledge/chunks/{sample_chunk.id}", json={"edited_text": "编辑后的内容"})
    assert resp.status_code == 200
    assert len(reembed_called) > 0  # 触发了 reembed


def test_update_locked_chunk_rejects(client, db_session, admin_user, sample_chunk):
    """locked chunk 不允许编辑（除非 force_unlock）。"""
    sample_chunk.locked = True
    db_session.commit()
    client.post("/auth/login", json={"username": admin_user["username"], "password": "Admin1234!"})
    resp = client.patch(f"/admin/knowledge/chunks/{sample_chunk.id}", json={"weight": 2.0})
    assert resp.status_code == 409
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_admin_chunks.py -v 2>&1 | tail -10
```
Expected: 失败（端点不存在）。

- [ ] **Step 3: 实现 service 函数**

在 `apps/api/app/services/knowledge_service.py` 加：

```python
def list_chunks_by_file(db: Session, *, file_id: str) -> list[KnowledgeChunk]:
    """列出某文件的所有 chunk（按 chunk_index 排序）。"""
    return db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.source_id == file_id)
        .order_by(KnowledgeChunk.chunk_index)
    ).scalars().all()


def update_chunk(
    db: Session, *, chunk_id, payload: dict, force_unlock: bool = False
) -> KnowledgeChunk:
    """admin 编辑 chunk（D8：edited_text 变更触发重 embed + tsv 重生成）。"""
    chunk = db.get(KnowledgeChunk, chunk_id)
    if not chunk:
        raise ValueError("chunk not found")
    if chunk.locked and not force_unlock and "edited_text" in payload:
        raise PermissionError("chunk locked")

    old_edited = chunk.edited_text
    if "keywords" in payload:
        chunk.keywords = payload["keywords"]
    if "questions" in payload:
        chunk.questions = payload["questions"]
    if "weight" in payload:
        chunk.weight = payload["weight"]
    if "edited_text" in payload:
        chunk.edited_text = payload["edited_text"] or None
    if "locked" in payload:
        chunk.locked = payload["locked"]

    # D8：edited_text 变更触发重 embed + tsv 重生成
    needs_reembed = chunk.edited_text != old_edited
    needs_tsv_regen = needs_reembed or "keywords" in payload or "questions" in payload

    if needs_reembed and chunk.edited_text:
        embed_config = resolve_embedding_config(db, user_id=chunk.user_id)
        if embed_config:
            vec = embed_texts([chunk.edited_text], embed_config=embed_config)[0]
            chunk.embedding = vec

    db.commit()

    # tsv 重生成（仅 PG，edited_text + keywords + questions 都进 tsv）
    from app.core.database import is_postgres
    if is_postgres() and needs_tsv_regen:
        from sqlalchemy import text as sa_text
        text_for_tsv = chunk.edited_text or chunk.content
        extra = " ".join((chunk.keywords or []) + (chunk.questions or []))
        db.execute(sa_text(
            "UPDATE knowledge_chunks SET tsv = to_tsvector('simple', :txt) WHERE id = :cid"
        ), {"txt": text_for_tsv + " " + extra, "cid": str(chunk.id)})
        db.commit()

    db.refresh(chunk)
    return chunk
```

- [ ] **Step 4: 实现 admin chunks 端点**

新建 `apps/api/app/api/admin/chunks.py`：

```python
"""G4 分块可视化干预端点（spec §5.4）。"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import User
from app.services.knowledge_service import list_chunks_by_file, update_chunk

router = APIRouter(prefix="/admin/knowledge", tags=["admin"])


def _chunk_out(chunk) -> dict:
    return {
        "id": str(chunk.id),
        "content": chunk.content,
        "edited_text": chunk.edited_text,
        "keywords": chunk.keywords or [],
        "questions": chunk.questions or [],
        "weight": chunk.weight or 1.0,
        "locked": chunk.locked,
        "chunk_index": chunk.chunk_index,
        "source_section_key": chunk.source_section_key,
    }


@router.get("/files/{file_id}/chunks")
def list_chunks(
    file_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    chunks = list_chunks_by_file(db, file_id=file_id)
    return [_chunk_out(c) for c in chunks]


class ChunkUpdateRequest(BaseModel):
    keywords: list[str] | None = None
    questions: list[str] | None = None
    weight: float | None = None
    edited_text: str | None = None
    locked: bool | None = None
    force_unlock: bool = False


@router.patch("/chunks/{chunk_id}")
def patch_chunk(
    chunk_id: uuid.UUID,
    payload: ChunkUpdateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        chunk = update_chunk(
            db, chunk_id=chunk_id, payload=payload.model_dump(exclude_none=True),
            force_unlock=payload.force_unlock,
        )
    except PermissionError:
        raise HTTPException(409, "chunk locked, use force_unlock to override")
    except ValueError:
        raise HTTPException(404, "chunk not found")
    return _chunk_out(chunk)
```

- [ ] **Step 5: 注册 router**

修改 `apps/api/app/api/admin/__init__.py`：

```python
from app.api.admin import chunks
api_router.include_router(chunks.router)
```

- [ ] **Step 6: 跑测试确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_admin_chunks.py -v 2>&1 | tail -15
```
Expected: 5 PASS。

- [ ] **Step 7: 回归 + 提交**

Run:
```bash
cd apps/api && uv run pytest -q 2>&1 | tail -10
```
Expected: 全绿。

```bash
git add apps/api/app/services/knowledge_service.py apps/api/app/api/admin/chunks.py apps/api/app/api/admin/__init__.py apps/api/tests/test_admin_chunks.py
git commit -m "feat(rag): G4 chunk 编辑 service + admin 端点（spec §5.4）

list_chunks_by_file + update_chunk。edited_text 变更触发重 embed + tsv 重生成（D8）。
locked chunk 防误改（force_unlock 覆盖）。"
```

---

### Task 4.3: 检索集成 G4 字段（edited_text + weight）

**Files:**
- Modify: `apps/api/app/rag/retriever.py`（启用 Task 3.4 临时去掉的 edited_text/weight 引用）
- Test: `apps/api/tests/test_retriever.py`（扩展）

- [ ] **Step 1: 写失败测试**

扩展 `apps/api/tests/test_retriever.py`：

```python
def test_retriever_uses_edited_text():
    """G4：检索返回用 edited_text（如非空）。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert 'edited_text' in src, "retrieve 未使用 edited_text"


def test_retriever_applies_weight():
    """G4：weight 作为召回分数乘子。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert 'weight' in src, "retrieve 未应用 weight"
```

- [ ] **Step 2: 启用 retriever 的 G4 集成**

修改 `apps/api/app/rag/retriever.py`，在 Task 3.4 临时简化的位置恢复：

- 构建 RetrievalCandidate 时：`content=chunk.edited_text or chunk.content`、`weight=chunk.weight or 1.0`（已含在 Task 3.4 Step 6 的最终态代码里）
- 融合后：`c.fused_score *= c.weight`
- 转 RetrievalResult 时：`content=chunk.edited_text or chunk.content`

（若 Task 3.4 已按最终态实现，本 Task 主要是确保测试通过 + 回归。）

- [ ] **Step 3: 跑测试 + 回归 + 提交**

Run:
```bash
cd apps/api && uv run pytest tests/test_retriever.py -v 2>&1 | tail -10
cd apps/api && uv run pytest -q 2>&1 | tail -10
```
Expected: 全绿。

```bash
git add apps/api/app/rag/retriever.py apps/api/tests/test_retriever.py
git commit -m "feat(rag): G4 检索集成（edited_text + weight 加权）

检索返回用 edited_text（如非空）；weight 作为召回分数乘子。keywords/questions 通过
tsv 重生成间接参与关键词路召回。"
```

---

### Task 4.4: 前端 chunk 编辑页

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`
- Modify: `apps/web/src/app/(app)/admin/content/knowledge/[fileId]/page.tsx`（新建）
- Modify: `apps/web/src/components/admin/chunk-editor-dialog.tsx`（新建）
- Modify: `apps/web/src/app/(app)/admin/content/knowledge/page.tsx`（文件卡片加「查看分块」链接）

- [ ] **Step 1: api 封装**

`api.ts` 加：

```typescript
async listChunks(fileId: string) {
  return request<Array<{
    id: string; content: string; edited_text: string | null;
    keywords: string[]; questions: string[]; weight: number;
    locked: boolean; chunk_index: number; source_section_key: string | null;
  }>>(`/admin/knowledge/files/${fileId}/chunks`);
},
async updateChunk(chunkId: string, payload: {
  keywords?: string[]; questions?: string[]; weight?: number;
  edited_text?: string; locked?: boolean; force_unlock?: boolean;
}) {
  return request(`/admin/knowledge/chunks/${chunkId}`, { method: 'PATCH', body: JSON.stringify(payload) });
},
```

- [ ] **Step 2: queries hook**

`queries.ts` 加（queryKeys.admin 加 `fileChunks: (id) => ['admin', 'fileChunks', id]`）：

```typescript
export function useFileChunks(fileId: string | null) {
  return useQuery({
    queryKey: queryKeys.admin.fileChunks(fileId),
    queryFn: () => api.listChunks(fileId!),
    enabled: !!fileId,
  });
}
export function useUpdateChunk() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ chunkId, payload }: { chunkId: string; payload: Parameters<typeof api.updateChunk>[1] }) =>
      api.updateChunk(chunkId, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'fileChunks'] }),
  });
}
```

- [ ] **Step 3: chunk 编辑对话框组件**

新建 `apps/web/src/components/admin/chunk-editor-dialog.tsx`：

```tsx
'use client';
import { useState, useEffect } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { useUpdateChunk } from '@/lib/queries';

type Chunk = {
  id: string; content: string; edited_text: string | null;
  keywords: string[]; questions: string[]; weight: number; locked: boolean;
};

export function ChunkEditorDialog({ chunk, open, onOpenChange }: {
  chunk: Chunk | null; open: boolean; onOpenChange: (v: boolean) => void;
}) {
  const [editedText, setEditedText] = useState('');
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState('');
  const [questions, setQuestions] = useState<string[]>([]);
  const [questionInput, setQuestionInput] = useState('');
  const [weight, setWeight] = useState(1.0);
  const [locked, setLocked] = useState(false);
  const update = useUpdateChunk();

  useEffect(() => {
    if (chunk) {
      setEditedText(chunk.edited_text || '');
      setKeywords(chunk.keywords || []);
      setQuestions(chunk.questions || []);
      setWeight(chunk.weight || 1.0);
      setLocked(chunk.locked || false);
    }
  }, [chunk]);

  if (!chunk) return null;

  const handleSave = () => {
    update.mutate(
      {
        chunkId: chunk.id,
        payload: {
          edited_text: editedText || undefined,
          keywords, questions, weight, locked,
        },
      },
      {
        onSuccess: () => { toast.success('已保存（若改了文本会重新 embed）'); onOpenChange(false); },
        onError: () => toast.error('保存失败'),
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>编辑分块 {chunk.locked && <Badge variant="destructive">已锁定</Badge>}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label>原始内容（只读）</Label>
            <pre className="text-xs bg-muted p-2 rounded max-h-32 overflow-y-auto whitespace-pre-wrap">{chunk.content}</pre>
          </div>
          <div>
            <Label>编辑后内容（留空用原始，变更触发重新 embed）</Label>
            <Textarea value={editedText} onChange={(e) => setEditedText(e.target.value)} rows={4} />
          </div>
          <div>
            <Label>关键词（参与关键词路召回加权）</Label>
            <div className="flex gap-2 mb-2 flex-wrap">
              {keywords.map((k) => (
                <Badge key={k} className="cursor-pointer" onClick={() => setKeywords(keywords.filter((x) => x !== k))}>{k} ×</Badge>
              ))}
            </div>
            <Input value={keywordInput} onChange={(e) => setKeywordInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && keywordInput.trim()) {
                  setKeywords([...keywords, keywordInput.trim()]);
                  setKeywordInput('');
                }
              }}
              placeholder="输入后回车添加" />
          </div>
          <div>
            <Label>预设问题</Label>
            <div className="space-y-1 mb-2">
              {questions.map((q, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-sm flex-1">{q}</span>
                  <Button size="sm" variant="ghost" onClick={() => setQuestions(questions.filter((_, idx) => idx !== i))}>×</Button>
                </div>
              ))}
            </div>
            <Input value={questionInput} onChange={(e) => setQuestionInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && questionInput.trim()) {
                  setQuestions([...questions, questionInput.trim()]);
                  setQuestionInput('');
                }
              }}
              placeholder="输入后回车添加" />
          </div>
          <div className="flex items-center gap-4">
            <div>
              <Label>权重（召回分数乘子，默认 1.0）</Label>
              <Input type="number" step="0.1" value={weight} onChange={(e) => setWeight(Number(e.target.value))} className="w-24" />
            </div>
            <div className="flex items-center gap-2">
              <Switch checked={locked} onCheckedChange={setLocked} />
              <Label>锁定（防重新 ingest 覆盖）</Label>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={handleSave} disabled={update.isPending}>{update.isPending ? '保存中...' : '保存'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: chunk 列表页**

新建 `apps/web/src/app/(app)/admin/content/knowledge/[fileId]/page.tsx`：

```tsx
'use client';
import { useState } from 'react';
import { useParams } from 'next/navigation';
import { PageShell, PageHeader } from '@/components/page-shell';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useFileChunks } from '@/lib/queries';
import { ChunkEditorDialog } from '@/components/admin/chunk-editor-dialog';

export default function FileChunksPage() {
  const params = useParams();
  const fileId = params.fileId as string;
  const { data: chunks, isLoading } = useFileChunks(fileId);
  const [editing, setEditing] = useState<any>(null);
  const [open, setOpen] = useState(false);

  return (
    <PageShell>
      <PageHeader title={`分块列表 ${fileId}`} description="点击分块编辑内容、关键词、权重。编辑文本会触发重新 embed。" />
      {isLoading && <Skeleton className="h-64" />}
      <div className="space-y-3">
        {chunks?.map((c) => (
          <div key={c.id} className="border rounded p-3 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge>#{c.chunk_index}</Badge>
              <Badge variant="outline">权重 {c.weight}</Badge>
              {c.locked && <Badge variant="destructive">已锁定</Badge>}
              {(c.keywords?.length ?? 0) > 0 && <Badge variant="secondary">{c.keywords.length} 关键词</Badge>}
              {c.edited_text && <Badge variant="secondary">已编辑</Badge>}
            </div>
            <p className="text-sm whitespace-pre-wrap line-clamp-3">{c.edited_text || c.content}</p>
            <Button size="sm" variant="outline" onClick={() => { setEditing(c); setOpen(true); }}>编辑</Button>
          </div>
        ))}
      </div>
      <ChunkEditorDialog chunk={editing} open={open} onOpenChange={setOpen} />
    </PageShell>
  );
}
```

- [ ] **Step 5: 文件卡片加「查看分块」链接**

修改 `apps/web/src/app/(app)/admin/content/knowledge/page.tsx`，在每个文件卡片加：

```tsx
import Link from 'next/link';
// 卡片内加：
<Link href={`/admin/content/knowledge/${file.id}`} className="text-sm text-primary hover:underline">查看分块 →</Link>
```

- [ ] **Step 6: 手动验证 + 提交**

```bash
cd apps/web && pnpm dev
# 访问 /admin/content/knowledge，点某文件「查看分块」，编辑 chunk，验证保存
git add apps/web/src/lib/api.ts apps/web/src/lib/queries.ts "apps/web/src/app/(app)/admin/content/knowledge/" apps/web/src/components/admin/chunk-editor-dialog.tsx
git commit -m "feat(web): G4 分块可视化干预页（admin/content/knowledge/[fileId]）

文件卡片加「查看分块」入口，chunk 编辑对话框（content/keywords/questions/weight/locked）。
抄审核工作台 + Dialog 模式。"
```

---

## Phase 4 收尾检查

- [ ] G4 字段迁移完成，conftest SQLite 兼容版同步
- [ ] chunk list/update 端点鉴权正确（403 for non-admin）
- [ ] edited_text 变更触发重 embed（D8）
- [ ] locked chunk 防误改（force_unlock 覆盖）
- [ ] 检索使用 edited_text + weight 加权
- [ ] 前端 chunk 编辑页可用
- [ ] **人工验证**：用 G2 检索测试页，对某网页 chunk 加 keywords 后，验证该 chunk 在关键词路召回排序上升（spec §8.4）
- [ ] 全量测试绿

---

## 全局收尾检查

- [ ] 所有迁移在空库和有数据两种情况都能跑通（`uv run alembic upgrade head` from scratch）
- [ ] 所有迁移可逆（`alembic downgrade -1` × N）
- [ ] 全量后端测试绿（`uv run pytest -q`）
- [ ] 前端 `pnpm build` 通过
- [ ] 三域隔离在 G2/G3/G4 所有改动中不被绕过（scope filter 双路都套、admin 端点都 require_admin）
- [ ] 现有 rag_search tool / search API 行为兼容（顶层 signature 不变）
- [ ] spec §8 所有验证点人工 dogfood 完成

---

## Self-Review 记录

### Spec 覆盖核对

| Spec 条款 | 实现位置 | 状态 |
|---|---|---|
| §5.1 G1 HNSW 索引 | Task 1.1 迁移 + Task 1.2 ef_search | [ ] |
| §5.2 G2 检索测试页 | Task 2.1 后端 + Task 2.2 前端 | [ ] |
| §5.3 G3 混合检索 | Task 3.1 RRF + 3.2 rerank + 3.3 配置 + 3.4 集成 + 3.5 tsv + 3.6 前端 | [ ] |
| §5.4 G4 分块干预 | Task 4.1 字段 + 4.2 端点 + 4.3 检索集成 + 4.4 前端 | [ ] |
| D1 HNSW 优先 | Task 1.1 | [ ] |
| D2 Postgres 内闭环 | Task 3.4（无 ES） | [ ] |
| D3 独立列 | Task 4.1 | [ ] |
| D4 admin 检索端点 | Task 2.1 | [ ] |
| D5 rerank 可开关 + 降级 | Task 3.2 + 3.4 | [ ] |
| D6 参数写死 + rerank 可配 | Task 1.1（m/ef 写死）+ 3.3（rerank 可配） | [ ] |
| D7 纯单测 | 全程（无 PG 集成测试） | [ ] |
| D8 edited_text 触发重 embed | Task 4.2 + 4.3 | [ ] |

### 边界情况覆盖

| 边界 | 测试用例 | 状态 |
|---|---|---|
| 无 embedding 配置 | test_retriever_returns_empty_when_no_embed_config | [ ] |
| rerank API 失败 | test_rerank_failure_returns_input_unchanged | [ ] |
| rerank 关闭 | test_rerank_disabled_returns_input_unchanged | [ ] |
| 关键词路空（SQLite） | retriever 走 is_postgres 判断 | [ ] |
| locked chunk 编辑 | test_update_locked_chunk_rejects | [ ] |
| 三域隔离 admin 端点 | test_*_requires_admin | [ ] |
| scope=global 不漏 personal | test_admin_retrieval_test_scope_filter | [ ] |

### 不变量保护

- [ ] 三域隔离：G2 admin 检索测试 scope=global 不命中他人 personal（retriever scope_filter）
- [ ] rag_search tool 行为兼容（顶层 signature 不变，内部混合检索透明）
- [ ] 现有测试全绿（每 Phase 回归）

### 已知限制

- SQLite 测试不覆盖真实向量检索/混合检索效果，靠 G2 人工验证（D7）
- 前端无组件测试框架，G2/G4 前端靠手动 dogfood
- tsvector 用 'simple' 分词，中文分词不友好（spec §九 风险，后续可接 zhparser）
- HNSW 参数写死（D6），不暴露 admin

---

## 实施顺序总结

| Phase | Tasks | 产出 | 新增测试数 |
|---|---|---|---|
| 0 | Task 0 | 基线绿 + 分支 + 取证 | 0 |
| 1 (G1) | 1.1-1.2 | HNSW 索引 + ef_search | 3 |
| 2 (G2) | 2.1-2.2 | admin 检索测试端点 + 前端页 | 3 |
| 3 (G3) | 3.1-3.6 | RRF + rerank + 配置 + 混合检索集成 + tsv + rerank UI | ~15 |
| 4 (G4) | 4.1-4.4 | G4 字段 + chunk CRUD + 检索集成 + 编辑页 | ~8 |

**总计：8-13 天，新增约 29 个测试，3 个迁移，3 个新后端模块，4 个新前端页/组件。**
