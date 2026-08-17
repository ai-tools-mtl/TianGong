# T2 闭环补全：评估建议 → AI 修订 — TDD 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通「诊断 → 治疗」闭环：审查报告 / 术语检查 / 新颖性评估三类建议，经统一修订管线（`POST /sections/{sid}/revise` SSE → 现有 diff/apply-diff 人工审核）落到章节内容；配套项目术语表（含生成上下文注入）。

**Architecture:** 后端 1 个 SSE 端点（revise，复用 generate 装配但不落库不 checkpoint）+ 1 张新表（project_terms）+ 6 个 terms REST 端点 + 审查 schema 增强与 novelty 解析扩展；前端 1 个 Zustand store + AIChatPanel 新 phase + 编辑器 query param 定位 + 报告页/术语面板/新颖性页入口。diff 审核链路（/diff + DiffReviewPanel + /apply-diff）零改动复用。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy 2.0 / Alembic / Next.js / React / TanStack Query / Zustand / pytest（SQLite 内存库 + JSONB variant 惯例，GOTCHAS G2）。

**Spec:** `docs/superpowers/specs/2026-08-17-advice-revision-loop-design.md`（v1.2，含源码核验结论——本计划直接引用其 § 编号，不再复述依据）

**分支策略（每批独立分支，完成后 `--no-ff` 合并 main）:**

| 批次 | 分支 | 内容 | 预计 |
|---|---|---|---|
| 1 核心管线 | `feat/revise-core` | revise 端点 + HITL 探针 + generate 隐患修复 + store/定位/revising phase + 报告页按章节入口 | 2-3 天 |
| 2 定位增强 | `feat/revise-locate` | location_section_keys + 按维度/跨章节入口 + 标题 Link | 0.5-1 天 |
| 3 术语表 | `feat/terms-glossary` | 迁移/CRUD/注入/extract/check + 术语面板 | 2-3 天 |
| 4 新颖性闭环 | `feat/novelty-suggestions` | parse_suggestions + 建议卡 + 文档收尾 | 0.5-1 天 |

**测试基线约定（重要，与旧计划不同）:** 当前全量 pytest 存在 pre-existing 失败（约 79 个，见记忆/GOTCHAS E4——Windows 必须先起 docker postgres/minio，否则 startup 重试拖数分钟像挂死）。Task 0 记录基线失败清单为对照集，各批验收标准是**不新增失败**，而非全绿。

---

## 文件结构（全批总览，标注批次）

| 文件 | 责任 | 动作 | 批 |
|---|---|---|---|
| `apps/api/app/schemas/ai.py` | `ReviseRequest` | 改 | 1 |
| `apps/api/app/ai/orchestrator.py` | `build_revise_instruction` + `astream_revise`；generate 去 checkpointer | 改 | 1 |
| `apps/api/app/api/ai.py` | `POST /sections/{sid}/revise` 端点 | 改 | 1 |
| `apps/api/tests/test_langgraph_probe.py` | HITL 探针（langgraph 行为） | 新建 | 1 |
| `apps/api/tests/test_revise_api.py` | revise 端点 + instruction 单测 | 新建 | 1 |
| `apps/web/src/stores/revision-store.ts` | PendingRevision 单值 store | 新建 | 1 |
| `apps/web/src/app/(app)/projects/[id]/page.tsx` | `?section=` 定位；pending 提示条；术语按钮 | 改 | 1/3 |
| `apps/web/src/lib/api.ts` / `types/api.ts` | `streamRevise`、terms 系列、types | 改 | 1/3/4 |
| `apps/web/src/components/ai-chat-panel.tsx` | `revising` phase + 确认卡片 | 改 | 1 |
| `apps/web/src/app/(app)/projects/[id]/review/page.tsx` | 按章节组入口 + 时效提示条（批1）；chip/按维度/Link（批2） | 改 | 1/2 |
| `apps/api/app/ai/schemas/review_schema.py` | `location_section_keys` | 改 | 2 |
| `apps/api/app/ai/review_prompts.py` | consistency prompt 章节清单带 key | 改 | 2 |
| `apps/api/app/services/review_service.py` | keys 兜底回填 | 改 | 2 |
| `apps/api/tests/test_review_*.py`（按现有命名） | 定位增强测试 | 改 | 2 |
| `apps/api/alembic/versions/*_create_project_terms.py` | 建表迁移 | 新建 | 3 |
| `apps/api/app/models/project_term.py` + `models/__init__.py` | `ProjectTerm` | 新建/改 | 3 |
| `apps/api/app/schemas/term.py` | Pydantic schemas | 新建 | 3 |
| `apps/api/app/services/term_service.py` | CRUD/extract/check | 新建 | 3 |
| `apps/api/app/api/terms.py` + `api/router.py` | 6 端点 + 挂载 | 新建/改 | 3 |
| `apps/api/app/ai/context_assembler.py` | 术语注入层 | 改 | 3 |
| `apps/api/tests/test_terms_api.py` | terms 全链测试 | 新建 | 3 |
| `apps/api/app/services/novelty_service.py` | `parse_suggestions` + persist 集成 | 改 | 4 |
| `apps/api/tests/test_novelty.py` | 解析/白名单/fail-open | 改 | 4 |
| `apps/web/src/app/(app)/projects/[id]/patents/page.tsx` | 建议卡 + 手动兜底 | 改 | 4 |
| `apps/web/src/components/terms-panel.tsx` | 术语面板三区块 | 新建 | 3 |
| `docs/llm-usage.md` / `AGENTS.md` / `docs/GOTCHAS.md` | 四调用点 + 新约定 + 探针结论 | 改 | 4 |

---

# 批 1：核心管线（feat/revise-core）

## Task 0: 工程前置验证（基线 + 分支）

- [ ] **Step 1: 起依赖容器（GOTCHAS E4）**

```bash
docker compose up -d postgres minio
```

- [ ] **Step 2: 记录基线失败清单**

```bash
cd apps/api && uv run pytest -q 2>&1 | tail -5
uv run pytest -q 2>&1 | grep -E "^(FAILED|ERROR)" | sort > /tmp/t2-baseline.txt; wc -l /tmp/t2-baseline.txt
```

Expected: 与既有基线一致（约 79 个 pre-existing）。把清单存好，各批收尾时对照「不新增」。

- [ ] **Step 3: 开分支**

```bash
git checkout main && git checkout -b feat/revise-core
```

## Phase 0: HITL 探针（spec §3.1.3，先于一切实现）

### Task 0.1: langgraph 行为探针测试

**Files:** `apps/api/tests/test_langgraph_probe.py`（新建）

目的：用最小 langgraph 图钉死「checkpointer 非 None + astream_events 无 thread_id + 节点内 interrupt()」的框架行为，结论写进测试 docstring 与 GOTCHAS。**该测试只记录行为，不断言对错**（断言用 `pytest.mark.parametrize` 的观察模式，见骨架）。

- [ ] **Step 1: 写探针测试**

```python
"""HITL 探针（spec §3.1.3）：langgraph 对「checkpointer + 无 thread_id + interrupt()」的行为。

背景：orchestrator 三路 build_agent 均传全局 checkpointer；generate 无 thread_id。
本测试用最小图观察框架行为，结论记入 GOTCHAS。无论结论如何，
revise/generate 均已按设计不传/去掉 checkpointer，本探针仅提供证据。
"""
import pytest
from langgraph.types import interrupt, Command
from langgraph.graph import StateGraph

def _build_probe_graph(checkpointer):
    builder = StateGraph(dict)
    def node(state):
        decision = interrupt({"question": "allow?"})   # 模拟 HumanInTheLoopMiddleware
        return {"ok": decision}
    builder.add_node("n", node)
    builder.set_entry_point("n")
    return builder.compile(checkpointer=checkpointer)

async def test_probe_interrupt_without_thread_id(in_memory_saver):
    graph = _build_probe_graph(in_memory_saver)
    # 观察点 A：不传 configurable.thread_id，astream_events 是否触发 interrupt / 抛错 / 直通
    # 观察点 B：事后 checkpoint 存储（list(...)）是否出现自动生成的 thread_id
    ...
```

- [ ] **Step 2: 跑探针，记录结论**

```bash
cd apps/api && uv run pytest tests/test_langgraph_probe.py -q
```

Expected: 得到明确行为（三选一：interrupt 触发并挂起 / 抛 ValueError / 忽略直通）。把结论写回本测试 docstring + 记到 `/tmp`（批 4 收尾进 GOTCHAS）。
若「触发并挂起」坐实 generate 死流隐患 → Task 2.5 的修复即坐实为 bug fix；若「忽略直通」→ 修复降级为冗余清理，同样执行。

## Phase 1: 后端 revise

### Task 1.1: `ReviseRequest` schema（TDD）

**Files:** `apps/api/app/schemas/ai.py`、`apps/api/tests/test_revise_api.py`（新建）

- [ ] **Step 1: 先写测试**

```python
# apps/api/tests/test_revise_api.py
import pytest
from pydantic import ValidationError
from app.schemas.ai import ReviseRequest

class TestReviseRequest:
    def test_valid(self):
        r = ReviseRequest(directives=["补充实施例"], origin="review")
        assert r.origin == "review"

    def test_directives_empty_rejected(self):
        with pytest.raises(ValidationError):
            ReviseRequest(directives=[])

    def test_directives_over_10_rejected(self):
        with pytest.raises(ValidationError):
            ReviseRequest(directives=["x"] * 11)

    def test_directive_over_500_chars_rejected(self):
        with pytest.raises(ValidationError):
            ReviseRequest(directives=["字" * 501])

    def test_origin_whitelist(self):
        with pytest.raises(ValidationError):
            ReviseRequest(directives=["x"], origin="evil")
        for ok in ("review", "novelty", "terms", "manual"):
            ReviseRequest(directives=["x"], origin=ok)
```

- [ ] **Step 2: 跑红 → 实现 schema → 跑绿**

```python
# schemas/ai.py 追加
_ALLOWED_ORIGINS = {"review", "novelty", "terms", "manual"}

class ReviseRequest(BaseModel):
    directives: list[str] = Field(min_length=1, max_length=10)
    origin: str = "manual"
    chat_source: str | None = None

    @field_validator("directives")
    @classmethod
    def _each_directive(cls, v: list[str]) -> list[str]:
        for d in v:
            d2 = d.strip()
            if not d2 or len(d2) > 500:
                raise ValueError("每条修订指令须为 1..500 字")
        return [d.strip() for d in v]

    @field_validator("origin")
    @classmethod
    def _origin_ok(cls, v: str) -> str:
        if v not in _ALLOWED_ORIGINS:
            raise ValueError("origin 非法")
        return v
```

### Task 1.2: `build_revise_instruction` 纯函数（TDD）

**Files:** `apps/api/app/ai/orchestrator.py`、`apps/api/tests/test_revise_api.py`

- [ ] **Step 1: 测试**（构造 fake section，断言指令包含：章节标题、每条 directive、四类约束关键词——「最小改动」「逐字保留」「术语表」「现有章节内容」段落头）

```python
class TestBuildReviseInstruction:
    def test_contains_directives_and_constraints(self, fake_section):
        text = build_revise_instruction(fake_section, ["补充实施例", "统一术语"])
        assert "补充实施例" in text and "统一术语" in text
        for kw in ("最小改动", "逐字保留", "术语", "现有章节内容"):
            assert kw in text

    def test_empty_content_guards(self, fake_section):
        # 现有内容为空时指令仍可构造（端点层负责 409，纯函数不重复防御）
        ...
```

- [ ] **Step 2: 红绿实现**——按 spec §3.1.4 的指令模板逐字落地（含「术语：若系统提示中给出了本项目术语表…」优先级条款，D13）。

### Task 1.3: `astream_revise`（TDD，mock 装配）

**Files:** `apps/api/app/ai/orchestrator.py`、`apps/api/tests/test_revise_api.py`

实施前先读现有 orchestrator 测试（若有）或 `tests/` 中 generate/chat 的 mock 模式，复用同一 fake-agent 手法；无先例则 monkeypatch `build_agent` 返回可产出 `on_chat_model_stream` 事件的 fake。

- [ ] **Step 1: 测试**

```python
class TestAstreamRevise:
    async def test_yields_tokens_and_full_content(self, ...):
        # fake agent 事件流 → 收集 yield 的 (kind, payload) → 断言 token 序列 + 最终全文
        ...

    async def test_checkpointer_not_passed(self, monkeypatch, ...):
        # 断言 build_agent(..., checkpointer=None)（spec §3.1.3：capture 调用参数）
        ...

    async def test_no_history_no_compress(self, ...):
        # 断言未调用 compress_history、input 不含历史消息（spec §3.1.2-3 输入语义）
        ...
```

- [ ] **Step 2: 红绿实现**——结构照抄 `astream_generate`（orchestrator.py:275）三处差异：instruction 换 `build_revise_instruction`；不落库（无 `section.content = ...`，全文仅在流内累积返回）；完成信号由调用方（端点）组 done 事件。

### Task 1.4: revise 端点（TDD，端到端）

**Files:** `apps/api/app/api/ai.py`、`apps/api/tests/test_revise_api.py`

- [ ] **Step 1: 端点测试**（复用现有 AI 端点 SSE 测试的消费模式；先 `grep -rn "text/event-stream" apps/api/tests/` 找先例）

```python
class TestReviseEndpoint:
    async def test_404_other_users_section(self, ...): ...
    async def test_409_empty_content(self, ...):
        # content=None 与 content=空白 Tiptap 两种（spec §3.1.2-1：不看 status）
    async def test_422_bad_body(self, ...): ...
    async def test_403_no_llm_config(self, ...): ...   # resolve_chat_config 开流前
    async def test_sse_frames_and_no_persist(self, ...):
        # 断言：token 帧序列、done.content=全文、done 无 title；
        #       section.content 未变、无新 Message、无新 conversation（spec §3.1.2-4）
    async def test_llm_call_log_action(self, ...):
        # LLMCallLog(action="revice"→"revise", meta.origin="review")
```

- [ ] **Step 2: 红绿实现**——结构照抄 generate 端点（ai.py:606-705）：限流 `@limiter.limit(AI_LIMIT, ...)`、前置校验链、`_sse_event` 帧、`_yield_with_heartbeat_tuple` 心跳、finally `_log_llm_call`。done payload：`{"content": full_md, "section_id": ...}`。
- [ ] **Step 3: 手册冒烟**（起 uvicorn + curl 一帧流，确认心跳与 done 结构）。

### Task 1.5: generate 去 checkpointer（spec §3.1.3 顺带修复）

**Files:** `apps/api/app/ai/orchestrator.py`（:310 附近）

- [ ] **Step 1: 改动**——`build_agent(..., checkplayer=get_checkpointer())` → `checkpointer=None`（generate 路径，仅此一处；chat/resume 不动）。
- [ ] **Step 2: 回归**——跑 generate 相关既有测试 + Task 0.1 探针对照（修复后 generate 语义与 revise 一致：工具直通）。
- [ ] **Step 3: 若探针坐实垃圾 checkpoint 写入**，给出清理 SQL 记到批 4 收尾文档（不在本批执行删数据）。

## Phase 2: 前端核心管线

### Task 2.1: revision store

**Files:** `apps/web/src/stores/revision-store.ts`（新建）

- [ ] **Step 1: 实现**（逻辑简单，不建前端测试，dogfood 覆盖）：

```typescript
"use client"
import { create } from "zustand"

export interface PendingRevision {
  sectionKey: string
  directives: string[]
  origin: "review" | "novelty" | "terms"
}

interface RevisionState {
  pending: PendingRevision | null
  launch: (p: PendingRevision) => void   // 单值覆盖（spec §3.5.1）
  consume: () => PendingRevision | null  // 取出并清空
  clear: () => void
}

export const useRevisionStore = create<RevisionState>((set, get) => ({
  pending: null,
  launch: (p) => set({ pending: p }),
  consume: () => { const p = get().pending; set({ pending: null }); return p },
  clear: () => set({ pending: null }),
}))
```

### Task 2.2: 编辑器 `?section=` 定位 + pending 提示条

**Files:** `apps/web/src/app/(app)/projects/[id]/page.tsx`

- [ ] **Step 1:** 挂载时读 `searchParams.get("section")`，匹配章节 key 则 `setCurrent`，随后 `router.replace(pathname)` 清参（spec §3.5.1：读后清除避免刷新重复跳转）。
- [ ] **Step 2:** store 有 pending 且不匹配当前章节 → 顶部轻提示条「有待执行的修订任务（{章节标题}）→ 前往」，点击 setCurrent；可关闭（clear）。
- [ ] **Step 3:** dogfood：`/projects/{id}?section=problem` 直达问题章节。

### Task 2.3: `streamRevise` + types

**Files:** `apps/web/src/lib/api.ts`、`apps/web/src/types/api.ts`

- [ ] **Step 1:** types 加 `ReviseRequest`；api.ts 加 `streamRevise(sectionId, body, onToken, signal, onDone?)`——结构照抄 `streamAssessNovelty`（api.ts:374），POST `/sections/{id}/revise`，走 `_consumeSSE`。

### Task 2.4: AIChatPanel `revising` phase

**Files:** `apps/web/src/components/ai-chat-panel.tsx`

- [ ] **Step 1:** `AIPhase` 加 `'revising'`；`PendingRevision` 相关 state（卡片数据、流式缓冲）。
- [ ] **Step 2:** 挂载/切章 effect：`useRevisionStore` 有 pending 且 `section.key` 匹配 → `consume()` 存入本地 state，弹确认卡片。
- [ ] **Step 3:** 确认卡片 UI：directives 复选框（默认全选，超 500 字截断+提示）+ 手动追加框 + 「开始修订」→ `streamRevise`（revising 中卡片隐藏，单飞）。
- [ ] **Step 4:** done：`setAiDraft(content)` + `handleOpenDiff()`（`diffOrigin='full'`，spec §3.5.2 已核验链路）→ DiffReviewPanel → apply-diff。
- [ ] **Step 5:** 只读上下文隔离：编辑器只读态（admin 临时查看 / 游客复用场景）不渲染卡片。
- [ ] **Step 6:** dogfood 完整链：确认卡片 → 流式 → diff → 应用 → 内容更新。

### Task 2.5: 报告页「按章节」入口 + 时效提示条

**Files:** `apps/web/src/app/(app)/projects/[id]/review/page.tsx`、`apps/web/src/lib/queries.ts`

- [ ] **Step 1:** 补 `useSections(projectId)`（若已有 hook 复用；否则 `api.listSections` + queryKey `['sections', id]`）。
- [ ] **Step 2:** 「按章节」tab 每组尾部「AI 修订本章」按钮 → `launch({sectionKey, directives: 组内 issues, origin: "review"})` + `router.push(/projects/{id}?section={sectionKey})`；sectionKey 在 sections 中不存在 → toast「章节不存在」不跳（边界 #17）。
- [ ] **Step 3:** 时效提示条：`max(sections.map(updated_at)) > latestReview.created_at` → 顶部提示（近似判断，spec §3.2.2）。
- [ ] **Step 4:** dogfood：跑一轮审查 → 按章节修订 → 应用 → 回报告页见提示条 → 重新审查分数变化。

## 批 1 收尾

- [ ] 对照 `/tmp/t2-baseline.txt` 跑全量：不新增失败。
- [ ] Self-Review（见文末模板）：spec §3.1 全项核对；占位符扫描（grep TODO/FIXME）。
- [ ] `git commit`（原子拆分：探针/schema+instruction/astream_revise/端点/generate修复/store+定位/panel/报告页）→ `git checkout main && git merge --no-ff feat/revise-core`。

---

# 批 2：定位增强（feat/revise-locate）

## Task 0: 基线 + 分支（同批 1 Task 0，基线文件换批 1 合并后的最新）

## Task 1: schema + prompt + 兜底回填（TDD）

**Files:** `apps/api/app/ai/schemas/review_schema.py`、`app/ai/review_prompts.py`、`app/services/review_service.py`、`tests/test_review_*.py`

- [ ] **Step 1: 测试**

```python
class TestLocationSectionKeys:
    def test_field_default_empty(self):
        # CrossSectionIssue 旧 JSON（无新字段）可解析 → 历史兼容
    def test_prompt_lists_keys(self):
        # build_consistency_prompt 的章节清单为 "{key}: {标题}"，且 prompt 文本要求 keys 从清单取值
    def test_backfill_by_title(self, db_with_sections):
        # LLM 只给 location_sections（标题）→ 后处理按 Section 表精确匹配回填 keys（spec §3.2.1-3，仅后端）
    def test_backfill_no_match_leaves_empty(self, ...): ...
```

- [ ] **Step 2: 红绿实现**：schema 加 `location_section_keys: list[str] = []`；prompt 清单与要求；`_check_cross_section_consistency` 后处理（标题→key 精确匹配，查库一次）。

## Task 2: 报告页三入口收齐

**Files:** `apps/web/src/app/(app)/projects/[id]/review/page.tsx`、`types/api.ts`（`CrossSectionIssue.location_section_keys?`）

- [ ] **Step 1:** 跨章节 issue：chips 来自 `location_section_keys`（key→标题用 sections 列表映射）；点 chip → `launch(targetKey, [issue.suggestion], "review")` + 跳转；keys 为空仅展示（**前端不做标题匹配**，D14）。
- [ ] **Step 2:** 「按维度」tab 维度卡加「按建议修订」：章节下拉（默认第一个未确认章节）+ `launch(key, [d.suggestion], "review")`（D12）。
- [ ] **Step 3:** 章节标题 Link 化（按章节 tab）。
- [ ] **Step 4:** dogfood：三类入口（按章节组 / chip / 按维度）各走一遍到 diff 应用。

## 批 2 收尾（同批 1：基线对照 / Self-Review / 原子提交 / --no-ff 合并）

---

# 批 3：术语表（feat/terms-glossary）

## Task 0: 基线 + 分支

## Task 1: 迁移 + 模型

**Files:** `apps/api/app/models/project_term.py`（新建）、`models/__init__.py`、`alembic/versions/{rev}_create_project_terms.py`

- [ ] **Step 1: 模型**——`ProjectTerm(IdMixin, TimestampMixin)`：project_id（FK cascade + indexed）/ term(String 100) / definition(Text nullable) / variants(JSONType, default list) / enabled(bool, True) / source(String 20, "manual")；`UniqueConstraint("project_id", "term")`；JSONB 用 `JSONB().with_variant(JSON, "sqlite")`（GOTCHAS G2）。
- [ ] **Step 2: 迁移**——`down_revision` 指向当前 head（`alembic heads` 确认单头，防多 head 前科）；init_db 哨兵不涉及（纯建表）。
- [ ] **Step 3:** `alembic upgrade head` + SQLite 内存库建表验证（跑任意既有模型测试确认无破坏）。

## Task 2: schemas + service CRUD + API（TDD）

**Files:** `app/schemas/term.py`、`app/services/term_service.py`、`app/api/terms.py`、`api/router.py`、`tests/test_terms_api.py`

- [ ] **Step 1: 测试**（先写，复用现有跨用户隔离测试的 user/project fixture 模式）

```python
class TestTermsCRUD:
    def test_create_list_update_delete(self, ...): ...
    def test_isolation_other_project_404(self, ...): ...
    def test_isolation_other_users_term_404(self, ...): ...
    def test_unique_conflict_409(self, ...): ...
    def test_variants_jsonb_roundtrip(self, ...): ...   # ["单元", "部件"] 存取
    def test_enabled_toggle(self, ...): ...
```

- [ ] **Step 2: 红绿实现**——service 四函数（list/create/update/delete，归属校验链 term→project→owner）；路由 6 条挂 `router.py`；PUT 部分更新语义照抄 `profile_service.upsert_profile`。

## Task 3: extract + check（TDD）

**Files:** `app/services/term_service.py`、`tests/test_terms_api.py`

- [ ] **Step 1: 测试**

```python
class TestExtract:
    async def test_success_returns_candidates(self, mock_lite_llm): ...
    async def test_llm_failure_degrades_empty(self, ...): ...   # 200 + warning（照抄 outline_extractor 降级）
    def test_empty_project_409(self, ...): ...

class TestCheck:
    def test_rule_scan_finds_variants(self, ...):
        # 多章节多术语：term=处理模块 variants=[单元] → 命中计数与 section_keys 正确
    def test_rule_scan_compound_word_hits(self, ...):
        # 「存储单元」命中（误报定性：断言命中而非漏报，spec §3.3.2）
    def test_empty_terms_skips_llm(self, ...): ...
    async def test_llm_drift_suggestions_fail_open(self, ...): ...  # 失败 → llm_suggestions: [] + warning
    async def test_llm_verify_filters_false_positive(self, ...): ... # verified 标记
```

- [ ] **Step 2: 红绿实现**——`TermCandidates/DriftSuggestions` schema（structured_output）；`resolve_lite_config`；规则扫描纯函数独立（易测）；`llm_verify` 默认 False。挂 AI_LIMIT。

## Task 4: 上下文注入层（TDD）

**Files:** `app/ai/context_assembler.py`、`tests/test_context_assembler*.py`（按现有命名）

- [ ] **Step 1: 测试**

```python
class TestTermsInjection:
    def test_enabled_terms_injected_with_format(self, ...):
        # "- 处理模块（禁用：单元、部件）：..." 且含标题行「本项目术语表」
    def test_disabled_not_injected(self, ...): ...
    def test_position_between_written_and_rag(self, ...):
        # prompt.index("已写章节标记") < index("术语表") < index("知识库参考")
    def test_over_100_truncated(self, ...): ...
    def test_read_failure_silent(self, ...): ...   # monkeypatch 抛错 → 不影响整体 prompt
```

- [ ] **Step 2: 红绿实现**——parts 列表在已写章节层后、知识库层前插入；读取失败 `db.rollback()` 静默。

## Task 5: 前端术语面板

**Files:** `apps/web/src/components/terms-panel.tsx`（新建）、`lib/api.ts`、`lib/queries.ts`、`types/api.ts`、编辑器 page.tsx（顶栏按钮）

- [ ] **Step 1:** types + api 六方法 + `useTerms` 系列（queryKey `['terms', projectId]`，写操作后 invalidate）。
- [ ] **Step 2:** 面板三区块（spec §3.5.4）：列表（Switch/删除/行内添加）、AI 抽取（勾选入库、重复置灰）、一致性检查（误报说明文案 + 每条「去修订」→ `launch` + 跳转；llm_suggestions「加入术语表」预填）。「LLM 复核」开关默认关。
- [ ] **Step 3:** 入口：编辑器顶栏「术语」按钮（BookA 图标），仅 owner 可编辑态显示。
- [ ] **Step 4:** dogfood：建表 → 抽取入库 → check → 去修订统一变体 → diff 应用；再开新 chat 会话验证术语约束生效（对照后端注入测试）。

## 批 3 收尾（基线对照 / Self-Review / 原子提交 / --no-ff 合并）

---

# 批 4：新颖性闭环 + 文档收尾（feat/novelty-suggestions）

## Task 0: 基线 + 分支

## Task 1: `parse_suggestions` + persist 集成（TDD）

**Files:** `app/services/novelty_service.py`、`tests/test_novelty.py`

- [ ] **Step 1: 测试**

```python
class TestParseSuggestions:
    async def test_parses_third_section_only(self, mock_lite_llm): ...
    def test_section_key_whitelist_filters(self, ...):
        # LLM 返回 key="claims"（非法）→ 该条丢弃；合法五 key 保留
    async def test_persist_includes_suggestions(self, ...): ...      # assessment dict 含 suggestions
    async def test_parse_failure_fail_open(self, ...): ...           # 仅 content，无 suggestions 键
    async def test_reassess_overwrites(self, ...): ...
```

- [ ] **Step 2: 红绿实现**——`NoveltySuggestion(s)` schema；`parse_suggestions(content)`（lite + structured，prompt 限定「只解析 ## 三、差异化撰写建议 段」）；端点 done 前先 parse 后 `persist_assessment`（并入同一 dict；fail-open 包裹）。

## Task 2: 前端建议卡

**Files:** `apps/web/src/app/(app)/projects/[id]/patents/page.tsx`、`types/api.ts`（`NoveltyAssessment.suggestions?: {section_key, text}[]`）

- [ ] **Step 1:** suggestions 渲染建议卡（`{章节名} · {text}` + 「去修订」）；**前置校验**：sectionKey 不存在或对应章节无内容 → 按钮禁用 + 提示（spec §3.5.5）。
- [ ] **Step 2:** 无 suggestions（旧数据/解析失败）→「手动复制建议去修订」兜底（textarea + 章节 dropdown 仅含有内容章节 + 开始修订 → 同一 launch 流）。
- [ ] **Step 3:** dogfood：跑评估 → 建议卡逐条去修订 → 应用。

## Task 3: 文档收尾（spec §8.7/8.8）

- [ ] **Step 1:** `docs/llm-usage.md` 增补 4 调用点：revise（A 类强模型 agent loop）/ terms_extract / terms_check / novelty_parse（lite，各注明触发场景与降级）。
- [ ] **Step 2:** `AGENTS.md` 增补约定一条（修订管线：revise 显式禁 HITL 不 checkpoint 不落库、directives 前端组装、术语表层注入位置与「术语表>沿用现状>最小改动」优先级）。
- [ ] **Step 3:** `docs/GOTCHAS.md`：记 Task 0.1 探针结论（langgraph 无 thread_id + checkpointer 行为）；若坐实垃圾 checkpoint，附清理 SQL 说明。
- [ ] **Step 4:** spec 文档头部标注「已实施（4 批，合并 commit 见 git log）」。

## 批 4 收尾 + 总验收

- [ ] 基线对照：不新增失败。
- [ ] **spec §8 六条验收逐项走查**：三类入口闭环 / 跨章节定位 / 术语全链 / 新颖性卡 / 修订质量抽检（3 真实章节，伪 hunk 占比 >30% 触发 R2 后备）/ 文档同步。
- [ ] Self-Review + 原子提交 + `--no-ff` 合并 main。

---

## Self-Review 记录（每批收尾填写）

### Spec 覆盖核对
- [ ] 对照 spec §3.x 逐条：本批实现的每一点在 spec 有出处，无 spec 外私自加戏
- [ ] 对照 spec §4 边界表：本批涉及的边界行号已覆盖（列表出）

### 类型一致性核对
- [ ] 后端 schema ↔ types/api.ts 字段一一对应（无孤儿字段）
- [ ] SSE 事件 payload 前后端一致（done.content 等）

### 已知限制（透明）
- （每批列出接受现状的点，如批 2 的 evidence 回退）

### 占位符扫描
- [ ] `grep -rn "TODO\|FIXME\|XXX" apps/api/app apps/web/src | grep -v node_modules` 无新增

## 实施顺序总结

```
批1 feat/revise-core      探针(0.1) → schema(1.1) → instruction(1.2) → astream(1.3) → 端点(1.4) → generate修复(1.5)
                          → store(2.1) → 定位(2.2) → api(2.3) → revising phase(2.4) → 报告页(2.5)
批2 feat/revise-locate    schema/prompt/兜底(1) → 三入口(2)
批3 feat/terms-glossary   迁移模型(1) → CRUD(2) → extract/check(3) → 注入层(4) → 面板(5)
批4 feat/novelty-suggestions  parse/persist(1) → 建议卡(2) → 文档收尾(3) → 总验收
```

依赖关系：批 2/3/4 的前端入口都依赖批 1 的 `launch`/定位/revising phase；批 3 后端与批 1/2 无耦合可并行开发（合并顺序仍按 1→2→3→4 或 1→3→2→4 均可）。
