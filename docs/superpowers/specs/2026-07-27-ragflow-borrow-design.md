# RAGFlow 能力借鉴 — 设计契约

> 日期：2026-07-27
> 状态：待评审
> 范围：apps/api（RAG 检索/分块/解析）+ apps/web（检索测试页、分块可视化干预）
> 相关：[MVP 设计（第 10 章 RAG 架构）](2026-07-13-tiangong-mvp-design.md) · [Firecrawl 网页摄入](2026-07-27-firecrawl-web-ingestion-design.md)（同为 P1 RAG 增强阶段，互补关系） · [GOTCHAS](../../GOTCHAS.md)（E3 / G5）
> 项目阶段声明：MVP 全部 P0 已完成；本设计为 P1 RAG 增强阶段的选型与落地方案，**借鉴 RAGFlow 的能力点，不集成 RAGFlow 产品本身**。
>
> **2026-07-28 修订**：Firecrawl 网页摄入已落地（`web_ingestion_service.py`）。该功能是「喂更多数据进同一根管子」的纯增量——复用同一套 chunker + embedding + retriever + 三域隔离，核心 RAG 文件 diff 为空，**本设计四项改动的前提假设全部仍然成立**。唯一影响见 §5.1（HNSW 必要性增强）与 §5.3（关键词路召回需处理网页 Markdown 噪声）。

---

## 一、背景与动机

天工的 RAG 在 MVP 阶段是**轻量自研实现**：LangChain `OpenAIEmbeddings` + pgvector 直连 + 纯文本解析 + 定长字符滑窗 + 纯向量余弦检索。RAG 不作为独立服务，而是封装成 `rag_search` 工具挂到 deepagents agent loop（`apps/api/app/ai/tools.py:12`），由 agent 自主决定何时调用。

对照 RAGFlow（"基于深层文档理解的开源 RAG 引擎"，主打深文档解析、可视化分块干预、多路召回），天工在**专利撰写场景**的 RAG 能力存在四个明确缺口：

1. **分块黑盒**：定长字符滑窗（800/100）盲切，无可见、无干预；专利知识里大量"切散了就废"的单元（权利要求项、技术特征列表、参数表、法条条款）会被腰斩。
2. **检索精度不足**：纯向量无 rerank，专利海量的**精确术语和编号**（权利要求1、步骤S10、对比文件D2、温度50-80°C）容易被"语义相近但编号/数值不符"的 chunk 淹没。
3. **调参无闭环**：分块对不对、阈值合不合理只能开真实对话盲试，无独立的检索质量验证工具。
4. **向量索引缺失**：pgvector 的 `embedding` 列**没有 IVFFlat/HNSW 索引**，检索是全表暴力扫描（迁移只建了 B-tree，`alembic/.../add_knowledge_chunks_with_pgvector.py:22`）。

RAGFlow 的一些能力（深文档解析、专用向量库、沙箱代码执行、对话助理配置）则**不应借鉴**——要么场景错位、要么过度工程、要么天工已有更先进的方案（agent + tool calling）。

本设计明确**借鉴什么、不借鉴什么、以及怎么落到现有架构**。

---

## 二、核心原则

> **借鉴 RAGFlow 的能力点、自研增量进现有架构；不集成 RAGFlow 产品当 RAG 后端。**

理由：

- 天工的 RAG 深度耦合在 deepagents agent loop + 撰写/审查流程 + **三域隔离（personal / global / admin approve）+ 上报审核流 + 双凭据链路（chat / embedding 独立）**。若换成 RAGFlow 当 RAG 引擎，这三件专利场景的硬约束全部丢失。
- RAGFlow 是 Docker 化重型栈（ES/Infinity + gVisor + 7GB 镜像），天工全栈在 Postgres + pgvector + MinIO，引入第二套存储破坏架构统一性，运维负担陡增。
- 天工的 deepagents + tool calling（agent 自主决定何时检索）比 RAGFlow 的"数据集 → 对话助理"更先进，倒退无意义。

**因此本设计的所有改动，约束在现有 Postgres + pgvector + MinIO 栈内闭环，不引入新存储、不破坏 agent tool 架构、不触碰三域隔离。**

---

## 三、目标与非目标

### 目标（本轮做 — P1 RAG 增强）

| 编号 | 能力 | 价值 | 工程量 |
|---|---|---|---|
| G1 | **pgvector HNSW 索引** | 还技术债，解决全表暴力扫描 | 0.5 天 |
| G2 | **检索测试页** | RAG 调参闭环验证工具 | 1-2 天 |
| G3 | **混合检索 + rerank** | 专利术语精度刚需（BM25 + 向量 + rerank） | 3-5 天 |
| G4 | **分块可视化干预** | RAGFlow 杀手锏，专家可干预，专利知识最怕切散 | 3-5 天 |

### 非目标（本轮不做）

- ❌ **不集成 RAGFlow 整体作为 RAG 后端**（丢三域隔离 + 审核流，背运维负担）。
- ❌ **不自建专用向量库**（Infinity / Elasticsearch）—— pgvector + HNSW 已足够，引第二套存储是过度工程。
- ❌ **不做沙箱代码执行**（gVisor）—— 天工无运行用户代码的场景。
- ❌ **不做对话助理配置 UI** —— 天工 agent + tool calling 已更先进，倒退无意义。
- ❌ **不做多 embedding 模型管理面板** —— 配置层已支持任意 OpenAI 兼容 provider 切换（`resolve_embedding_config`，`llm_config_service.py:404`），功能等价。
- ❌ **本轮不做深文档解析 / 多分块模板** —— 见第七章「未来演进」，需先明确产品定位。

---

## 四、承重决策（D1-D6）

- **D1（HNSW 优先于 IVFFlat）** ⚠️：`embedding` 列建 **HNSW** 索引而非 IVFFlat。理由：① pgvector 0.7+ 原生支持 HNSW，召回质量优于 IVFFlat；② IVFFlat 需要建索引时指定 `lists` 并在查询时配 `probes`，调参敏感；③ HNSW 增量写入友好（知识库持续 ingest 场景）。代价：写入略慢、内存占用略高，但天工的写入是低频异步操作，可接受。
- **D2（混合检索在 Postgres 内闭环）** ⚠️：BM25 用 **Postgres 内置全文检索（`tsvector` + `ts_rank_cd`）**，向量用 pgvector，融合用 **RRF（Reciprocal Rank Fusion）**。**不引入 ES / Lucene**。rerank 用**智谱 rerank API**（`rerank` 端点，与 embedding 同 provider 体系）作为首选，本地 bge-reranker 作为 fallback（admin 可配）。
- **D3（分块干预走 metadata JSONB 扩展，不改表结构主键）** ⚠️：分块的 `keywords` / `questions` / `weight` / `edited_text` / `locked` 字段**全部塞进现有 `KnowledgeChunk.metadata_` JSONB**（`models/knowledge_chunk.py:13`），**不新增列、不新增表**。理由：① 改动最小、迁移最轻；② JSONB 查询能力足以支撑按 keywords 过滤；③ 后续如需 SQL 索引化可再抽列。
- **D4（检索测试页复用现有 search API，前端新增）** ⚠️：后端**零改动**——`POST /knowledge/search`（`api/knowledge.py:44`）已返回 content/score/section_key/project_title，前端在 admin 工作台新增「检索测试」页签即可。
- **D5（rerank 作为可开关的 post-retrieval 步骤）** ⚠️：rerank **不替换**向量召回，而是**在召回后、返回前**插一层。admin 可在后台开关 rerank、配 rerank 模型、配 top_n（rerank 后保留数）。默认开。
- **D6（HNSW 参数用 pgvector 推荐默认值，不暴露给 admin）** ⚠️：`m=16, ef_construction=64`（pgvector 官方推荐），`ef_search` 在查询时设为 `max(40, top_k * 4)`。这些参数不暴露到 admin UI，避免误调；后续如需调参走配置文件。

---

## 五、详细设计

### 5.1 G1：pgvector HNSW 索引（D1 / D6）

**问题**：现状迁移 `add_knowledge_chunks_with_pgvector.py:22-44` 只建了 B-tree（`user_id`、`source_id`），`embedding` 列无向量索引，检索是全表暴力余弦扫描（`retriever.py:24-83` 的 `cosine_distance` + `order_by`）。

> **⚠️ 紧迫性（2026-07-28 修订）**：原 MVP 设计附录 C 把全表扫描列为 🟢低风险，前提是「数据量小」。Firecrawl 网页摄入落地后这一前提已被削弱——单次 crawl 硬上限 100 页（`web_ingestion_service.py:31`），每页 Markdown 按现有 800/100 滑窗约产 3-7 个 chunk，**单次 crawl 可产生 300-700 个 chunk**，是知识库数据增长的主要来源。一旦整站 crawl 成为常态，全表扫描的延迟会快速劣化。G1 应**优先于其他三项尽早落地**。

**方案**：新建 alembic 迁移，为 `knowledge_chunks.embedding` 建 HNSW 索引。

```python
# alembic/versions/xxxxx_add_hnsw_index_on_embedding.py
def upgrade():
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding_hnsw "
        "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

def downgrade():
    op.drop_index("ix_knowledge_chunks_embedding_hnsw", table_name="knowledge_chunks")
```

**查询侧适配**：`retriever.py` 的查询前需设 `ef_search`（HNSW 的动态探测参数，仅当前事务有效）：

```python
# retriever.py 的 retrieve 函数开头
await session.execute(text("SET LOCAL hnsw.ef_search = :ef"), {"ef": max(40, top_k * 4)})
```

**前置条件**：确认生产 pgvector 版本 ≥ 0.5.0（HNSW 引入版本）。当前 `docker-compose.yml:16` 用 `pgvector/pgvector:pg16`，内嵌 pgvector 版本通常 ≥ 0.7，满足。

**风险**：建 HNSW 索引时若表已有数据，会全量重建（耗 CPU/内存）。当前数据量小，可在低峰期直接建。若后续数据量大，需用 `CREATE INDEX CONCURRENTLY`（注意 HNSW 索引 pgvector 0.7+ 才支持并发构建）。

---

### 5.2 G2：检索测试页（D4）

**问题**：分块质量、检索阈值、top_k 等参数现在**只能开真实对话盲试**，RAG 调参是黑盒玄学。RAGFlow 的做法是上传后能"输入测试问题 → 看召回了哪些 chunk → 看分数"，把调参变成可视化闭环。

**方案**：后端零改（`POST /knowledge/search` 已返回所需字段），前端在 `/admin/console/knowledge` 下新增「检索测试」页签。

**前端组件结构**（`apps/web/src/app/(admin)/admin/console/knowledge/retrieval-test/`）：

- 输入区：query 文本框 + scope 选择（personal/global）+ top_k 滑块 + 阈值滑块（可选覆盖默认 0.5）
- 结果列表：每条召回显示 `content`（截断 + 展开）、`score`、`section_key`、`project_title`、来源文件名
- 高级：开关 rerank（G3 完成后），对比开/关 rerank 的召回差异

**价值**：G3/G4 的所有调参都依赖这个页面做验收。**G2 应在 G3 之前完成**。

---

### 5.3 G3：混合检索 + rerank（D2 / D5）

**问题**：专利有海量精确术语和编号，纯向量检索会召回"语义相近但编号/数值不符"的 chunk，在专利场景是致命的（援引错法条/参数）。

**方案**：三段式检索管线（召回 → 融合 → 精排）。

#### 阶段 1：双路召回

```python
# rag/retriever.py 扩展
async def retrieve(query, user_id, scope, top_k=10):  # 召回阶段 top_k 放大（如 10）
    query_vec = await embed_text(query)

    # 向量路（pgvector HNSW）
    vec_results = await session.execute(
        select(KnowledgeChunk, KnowledgeChunk.embedding.cosine_distance(query_vec).label("distance"))
        .filter(<scope filter>)
        .order_by("distance")
        .limit(top_k)
    )

    # 关键词路（Postgres 全文检索）
    tsquery = func.plainto_tsquery("simple", query)  # simple 配置，不做中文分词优化（先粗后精）
    kw_results = await session.execute(
        select(KnowledgeChunk, func.ts_rank_cd(KnowledgeChunk.search_vector, tsquery).label("rank"))
        .filter(KnowledgeChunk.search_vector.match(tsquery))
        .filter(<scope filter>)
        .order_by(desc("rank"))
        .limit(top_k)
    )
    return vec_results, kw_results
```

**前置改动**：`knowledge_chunks` 表新增 `search_vector tsvector` 列（存储分词后的文本），并在 ingest 时同步写入。可由 `content` 生成（`to_tsvector('simple', content)`），或在分块干预时由 admin 编辑的 keywords 增强。

#### 阶段 2：RRF 融合

```python
def rrf_fuse(vec_results, kw_results, k=60):
    """Reciprocal Rank Fusion：两路结果按排名倒数加权融合"""
    scores = defaultdict(float)
    for rank, chunk in enumerate(vec_results):
        scores[chunk.id] += 1.0 / (k + rank + 1)
    for rank, chunk in enumerate(kw_results):
        scores[chunk.id] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])
```

RRF 是工业标准融合算法，无需训练、参数少（`k=60` 是经验值），适合天工这种无标注数据的场景。

> **⚠️ 数据质量注意（2026-07-28 修订）**：Firecrawl 抓回的网页 Markdown 经 `content_filter.py` 过滤后仍含导航/链接残留（该 filter 只删 5+ 连续链接行）。这些残留文本会进入 `to_tsvector('simple', content)` 的关键词路召回，把召回结果污染成「匹配到导航链接而非正文」。G3 落地时需配合处理：① 在 `search_vector` 生成前对网页 chunk 做二次清洗（去 URL、去 markdown 链接语法）；② 或在分块干预（G4）阶段，让 admin 给网页 chunk 手动补 keywords 参与召回，绕开正文噪声。详见 §5.4 的 `keywords`/`questions` 机制。

#### 阶段 3：rerank 精排

```python
async def rerank(query, candidates, top_n=3):
    """调智谱 rerank API（或本地 bge-reranker）对 candidates 重排，返回 top_n"""
    if not settings.rerank_enabled:
        return candidates[:top_n]
    docs = [c.content for c in candidates]
    resp = await rerank_client.post("/rerank", json={"model": settings.rerank_model, "query": query, "documents": docs})
    return [candidates[r["index"]] for r in sorted(resp["results"], key=lambda x: -x["relevance_score"])[:top_n]]
```

**整体管线**：`retrieve(top_k=10)` → `rrf_fuse` → `rerank(top_n=3)` → 返回给 `rag_search` 工具。

**rerank 配置**（admin 后台，复用现有 LLM 配置 UI 模式）：rerank_enabled / rerank_provider / rerank_base_url / rerank_api_key / rerank_model。存 `SystemSetting`（key=`rag_rerank_config`）。fallback：rerank 关闭或调用失败时，直接返回 RRF 融合后的 top_n。

---

### 5.4 G4：分块可视化干预（D3）

**问题**：定长滑窗盲切，专家无法干预；专利知识里"权利要求1"被切成两块后两块都召不回完整语义。

**方案**：在 admin 工作台的知识库审核流（已有 `api/admin/review.py`）基础上，扩展出分块编辑能力。

#### 数据层（D3：metadata JSONB 扩展，不改表结构）

`KnowledgeChunk.metadata_` JSONB 新增约定字段（无 schema 强约束，约定 key）：

```python
{
    # 现有字段
    "title": "...",
    # 新增干预字段
    "keywords": ["权利要求1", "特征部分", "前序部分"],   # 检索加权
    "questions": ["什么是权利要求1的技术特征?"],          # 预设问题，参与关键词路召回
    "weight": 1.5,                                       # 召回分数乘子
    "edited_text": None,                                 # admin 手动改写后的文本（None=用原 content）
    "locked": False                                      # 锁定后重新 ingest 不覆盖
}
```

**检索侧适配**（G3 的关键词路召回）：
- `keywords` + `questions` 拼入 `search_vector` 生成（让它们参与全文检索匹配）
- `weight` 在 RRF 融合后乘到最终分数
- `edited_text` 非空时，检索返回和喂给 LLM 都用 `edited_text` 而非 `content`

#### 接口层

```python
# apps/api/app/api/admin/knowledge.py 新增
@router.put("/admin/knowledge/chunks/{chunk_id}")
async def update_chunk(chunk_id: UUID, payload: ChunkUpdate, ...):
    """admin 编辑 chunk：改 content、加 keywords/questions、设 weight、锁定"""
    chunk = await get_chunk(chunk_id)
    if chunk.metadata_.get("locked") and payload.unlock is False:
        raise HTTPException(409, "chunk locked")
    chunk.metadata_.update({
        "keywords": payload.keywords,
        "questions": payload.questions,
        "weight": payload.weight,
        "edited_text": payload.edited_text,
        "locked": payload.locked,
    })
    # 若 edited_text 变更，需重新 embed 并更新 embedding 列
    if payload.edited_text and payload.edited_text != chunk.metadata_.get("edited_text"):
        chunk.embedding = await embed_text(payload.edited_text)
```

#### 前端

`/admin/console/knowledge/files/{file_id}` 页：列出该文件的所有 chunk（卡片），每个 chunk 可：
- 查看 content（默认）/ edited_text（如有）
- 编辑文本（触发重新 embed）
- 加 keywords（标签输入）、questions（列表）
- 设 weight（数字输入）
- 合并相邻 chunk（拼成一块）/ 拆分（按光标位置切成两块）
- 锁定（防重新 ingest 覆盖）

**重新 ingest 行为**：文件被重新解析时，`locked=True` 的 chunk 保留（按 chunk_hash 或 sequence 匹配），其余按新分块覆盖。

---

## 六、落地顺序与依赖

```
1️⃣  G1 HNSW 索引          ←  0.5 天，立刻收益，无依赖
2️⃣  G2 检索测试页          ←  1-2 天，依赖 G1（用真实索引验证），为 G3/G4 铺路
3️⃣  G3 混合检索 + rerank   ←  3-5 天，依赖 G2（调参验证）
4️⃣  G4 分块可视化干预      ←  3-5 天，依赖 G2（验证干预效果）、与 G3 并行
```

**关键依赖**：G2（检索测试页）必须前置——它是 G3/G4 所有调参的验收工具，没有它的话 G3 的 RRF 参数、rerank top_n、G4 的 weight/keywords 加权全是盲调。

**总工程量**：8-13 天（单人）。

---

## 七、未来演进（非本轮）

以下能力**不在本轮范围**，但记录在此供后续决策：

### 7.1 深文档解析（表格 / 版面 / OCR）

**何时考虑**：天工定位往「专利撰写器」演进时（需处理权利要求对照表、参数表、对比文件的表格结构）。

**怎么做**：**接轻量开源库替换 `pypdf`，不接 RAGFlow 整体**。候选：
- **docling**（IBM 出品，表格/版面强，Apache 2.0）
- **unstructured**（通用，生态广）
- **MinerU**（中文 PDF 强，国产）

接口边界保持不变：`parsing/dispatcher.py` 的 `extract_text` 签名不变，内部从 `pypdf` 切到 docling，下游 `chunker` / `archiver` 无感。

**不做**：❌ 接 RAGFlow 整体只为拿它的解析（架构污染）；❌ AI 生成附图（法律准确性问题，画错编号误导审查）。

### 7.2 Patent-aware 分块模板

**何时考虑**：G4 分块干预落地后，发现通用分块对专利文档（权利要求 / 实施例 / 背景技术章节结构差异大）召回质量不够。

**怎么做**：自研 patent-aware chunker，**借鉴天工已有的 `parsing/structure_extractor.py`**（原本给"套模板"识别 Word 章节的逻辑），按章节类型分发策略：
- 权利要求：逐项一块，绝不可切
- 实施例：按段落切
- 背景技术：可粗切

**不做**：❌ 抄 RAGFlow 的通用分块模板——专利结构天工自己最懂。

### 7.3 专利撰写能力升级（与 RAG 无关但相关）

若天工往「专利撰写器」演进，最高优先级是**权利要求生成**（结构化：前序部分 + 特征部分 + 独立/从属层级 + 与技术方案的一致性校验），这是从"交底书助手"跨到"专利撰写器"的唯一门槛。详见后续独立设计。

---

## 八、验证标准

### 8.1 G1 验证

- [ ] 迁移在空库和有数据两种情况下都能跑通（`uv run alembic upgrade head`）
- [ ] `EXPLAIN ANALYZE` 验证检索查询走 HNSW 索引扫描而非 seq scan
- [ ] 现有所有 RAG 相关测试通过（`uv run pytest tests/` 中 knowledge/retrieval 相关）
- [ ] 召回结果与建索引前一致（HNSW 是近似但高质量，召回集合应基本一致）

### 8.2 G2 验证

- [ ] `/admin/console/knowledge/retrieval-test` 页可输入 query，返回召回列表
- [ ] 可切换 personal/global scope
- [ ] 召回结果展示 score / section_key / project_title / 来源文件
- [ ] G3 完成后，可开关 rerank 对比召回差异

### 8.3 G3 验证

- [ ] 含精确术语（如"权利要求1"）的 query，混合检索召回相关 chunk 的精度优于纯向量（人工标注 20 条 query 对比）
- [ ] rerank 开启后，top_3 的相关性优于未 rerank（人工评估）
- [ ] rerank 关闭或 API 失败时，降级到 RRF 融合结果，不报错
- [ ] 三域隔离不被破坏（personal 不被他人召回）
- [ ] 现有 `rag_search` 工具行为向后兼容（agent 调用方式不变）

### 8.4 G4 验证

- [ ] `/admin/console/knowledge/files/{file_id}` 可查看所有 chunk
- [ ] 可编辑 chunk 文本（触发重新 embed）
- [ ] 可加 keywords/questions、设 weight、锁定
- [ ] keywords 参与关键词路召回（在检索测试页验证）
- [ ] weight 影响召回排序（在检索测试页验证）
- [ ] locked chunk 在重新 ingest 时被保留

---

## 九、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| HNSW 建索引耗资源 | 低（数据量小） | 低峰期建；后续用 `CONCURRENTLY` |
| `simple` 分词对中文不友好 | 关键词路召回精度打折 | 先用 simple 粗召，rerank 兜底；后续接 zhparser/jieba 分词 |
| rerank API 延迟 | 单次检索 +200-500ms | 默认开但可关；agent tool 场景对延迟不敏感（非实时聊天） |
| 分块 edited_text 与原 content 不一致 | 喂给 LLM 的内容与展示给用户的不一致 | 检索返回和 LLM 注入**统一用 edited_text**（如非空），UI 标注"已编辑" |
| 三域隔离在混合检索中被绕过 | 数据泄漏 | 双路召回都套同一个 scope filter，单测覆盖 |

---

## 十、参考资料

- **RAGFlow 官方文档**：https://ragflow.com.cn/docs
- **pgvector HNSW 文档**：https://github.com/pgvector/pgvector#hnsw
- **RRF 论文**：Cormack et al., "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods", SIGIR 2009
- **本项目相关**：
  - MVP 设计第 10 章 RAG 架构（`docs/superpowers/specs/2026-07-13-tiangong-mvp-design.md:1248-1366`）
  - GOTCHAS E3（LlamaIndex 不支持国产 embedding → 弃用改 LangChain，`docs/GOTCHAS.md:164-170`）
  - GOTCHAS G5（pgvector 迁移必须 `CREATE EXTENSION`，`docs/GOTCHAS.md:48-58`）
