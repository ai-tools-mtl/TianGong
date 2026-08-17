# T2 闭环补全：评估建议 → AI 修订 — 设计契约

> 版本 v1.2（2026-08-17）。v1.0 初稿 + v1.1 自查后，v1.2 二轮逻辑审查完成源码级核验：坐实 generate 端点存在「checkpointer + interrupt_on + 无 thread_id」组合隐患（非 revise 新引入）；修正 v1.1 内部的术语指令矛盾（术语表 vs 沿用现状）；补齐维度级建议无修订入口的缺口；跨章节兜底单点化。修订清单见附录 B/C。
> 对应讨论：MVP P0/P1 与五批功能全部落地后，用户拍板优先开发 T2「闭环补全」。
> 三个子功能：A 审查报告建议一键修订、B 项目术语表 + 术语一致性检查、C 新颖性建议差异化改写。

## 1. 目标与范围

### 1.1 问题

系统已有三个「诊断」能力——审查引擎（质量报告）、术语漂移（仅 LLM 审查时顺带发现）、AI 新颖性评估——它们产出报告后流程即终止，用户需要自己对照建议手改章节。「诊断」与「治疗」之间断链。

### 1.2 目标

把三类建议统一为「结构化建议（定位到章节 + 可执行文本）」，经**同一条修订管线**落地：

```
建议 → 修订指令（directives）→ 章节 AI 重写（流式）→ diff 审核（人工勾选 hunks）→ 乐观锁应用
```

### 1.3 范围内

| 子功能 | 内容 |
|---|---|
| A 修订管线（核心） | 新端点 `POST /sections/{sid}/revise`（SSE）+ 审查报告页三个修订入口 + 前端修订确认卡片 |
| A' 审查建议定位增强 | 跨章节 issue 增加 `location_section_keys` 结构化定位；报告页章节标题可点击；报告时效提示条；编辑器 `?section=` 定位 |
| B 项目术语表 | `project_terms` 表 + CRUD + AI 抽取候选 + 一致性检查（规则 + LLM 双路，可选 LLM 复核）+ 生成上下文注入层 |
| C 新颖性建议结构化 | 评估完成后轻量模型解析第三段建议为 `{section_key, text}[]` 持久化 + 前端建议卡「去修订」 |

### 1.4 明确不做（去范围）

- **建议处理状态持久化**：ReviewRecord 是轮次快照，不做「已处理/忽略」标记。修订效果由下一轮审查分数与趋势图体现（趋势图已存在），辅以报告时效提示条（§3.2.2）。避免引入状态机复杂度。
- **自动应用修订**：修订稿必须经 DiffReviewPanel 人工勾选后 apply。不提供任何跳过审核的路径。
- **用户级 / 全局术语库**：本期只做项目级（一件专利一套术语体系，天然归属案件）。用户级软偏好已有 `WritingProfile.terminology`，两者并存（§3.3.4）。admin 全局默认术语模板（seed）不做，内网单团队场景各项目自配可接受。
- **术语变体的直接文本替换**：在 Tiptap JSON 上做跨节点字符串替换风险高（术语可能跨越 marks/段落边界、替换后句子可能不通顺），统一走 LLM 修订管线。
- **多章节批量修订**：一次修订一个章节。跨章节 issue 涉及多章节时逐章发起（§4.3）。
- **generate 端点 checkpointer 隐患的修复**（若探针坐实 langgraph 问题行为）：**纳入批 1 顺带修复**（一行：generate 路径 build_agent 不传 checkpointer），但根因分析单独立项，不扩展本设计范围。

## 2. 总体架构与数据流

### 2.1 数据流总图

```
┌─ 审查报告 ReviewRecord ──────────────────────┐  ┌─ 新颖性 assessment.suggestions ─┐  ┌─ 术语检查 terms/check ─┐
│ ①按章节组 section_issues[]（有 section_key）  │  │ [{section_key, text}]           │  │ rule_issues[]           │
│ ②跨章节 cross_section_issues[]                │  │ （解析自报告第三段，fail-open）  │  │  {term,variant,sections}│
│   （新增 location_section_keys）               │  └────────────────────────────────┘  └─────────────────────────┘
│ ③按维度 dimension_scores[].suggestion（v1.2） │
└──────────────┬───────────────────────────────┘
               │  前端组装（确认卡片上勾选可见）
               ▼
     directives: list[str] + sectionKey + origin
               │  Zustand revision store（跨页传递，单值覆盖语义）
               ▼
     AIChatPanel 弹修订确认卡片 → 用户勾选建议 → 开始修订
               │
               ▼
     POST /api/v1/sections/{sid}/revise   （SSE：token/thinking/tool_call/tool_result/heartbeat/done/error）
       - build_agent 装配复用 generate 路径（RAG/记忆/画像/术语表层全量），checkpointer 显式不传
       - 显式 interrupt_on=None（禁用 HITL，见 §3.1.3 —— 源码已核验：三路均传全局 checkpointer）
       - instruction = 章节策略 + 现有全文 + directives + 最小改动约束（术语表优先，见 §3.1.4）
       - 不写 section.content、不建 Message、不做 checkpoint、不带聊天历史
       - done 事件带权威全文 content
               │
               ▼
     POST /sections/{sid}/diff            （现有端点：Tiptap↔markdown 对齐算 hunks，ai_text=done.content）
               ▼
     DiffReviewPanel 人工勾选 hunks → POST /sections/{sid}/apply-diff（现有端点，乐观锁）
```

### 2.2 复用清单（本设计的地基；标注〔✓已核验〕的均已读源码确认）

| 现有设施 | 复用方式 |
|---|---|
〔✓〕`astream_generate` / `build_agent` 装配（orchestrator.py:275 / agent.py:44） | `astream_revise` 同构实现，换 instruction 构造 + 关闭落库 + 不传 checkpointer（§3.1.3） |
〔✓〕`build_agent` 的 checkplayer/interrupt_on 链（agent.py:49/:176） | interrupt_on 由 `build_interrupt_on(db, checkpointer)` 从 checkpointer 推导；revise 不传 checkpointer 即自然禁用，仍显式断言 |
〔✓〕`AIChatPanel.handleOpenDiff`（ai-chat-panel.tsx:515） | 依赖 `aiDraft` state → revise done 后 `setAiDraft(content)` + `handleOpenDiff()` 即入 `diff-review`，链路成立 |
〔✓〕`POST /sections/{sid}/diff`（sections.py:59，`{ai_text}` Markdown） | ai_text=done.content，契约同构（generate「审查差异」同款） |
〔✓〕novelty `persist_assessment`（novelty_service.py:134，端点 done 前调用） | suggestions 解析插在它之前并入同一 dict 写入 |
〔✓〕`build_system_prompt` parts 顺序（context_assembler.py:363+） | 项目元信息→已写章节→知识库→记忆→画像→章节策略→…；术语层插「已写章节后、知识库前」 |
| `resolve_lite_config` + `outline_extractor` structured_output 失败降级先例 | 术语抽取/检查、novelty 建议解析的降级模式 |
| `resolve_chat_config` 开流前解析（403 真实返回） | revise / extract / check 端点同约定 |
| generate「有意不传 thread_id」约定 | revise 同样不传（AGENTS.md 约定） |
| SSE 帧构造、心跳、乐观锁 apply-diff | 直接复用 |

## 3. 详细设计

### 3.1 修订端点 `POST /sections/{sid}/revise`

#### 3.1.1 请求与协议

**请求**（`schemas/ai.py` 新增）：

```python
class ReviseRequest(BaseModel):
    directives: list[str]          # 1..10 条，每条 1..500 字，去空白后非空
    origin: str = "manual"         # review | novelty | terms | manual —— 白名单校验（422），仅 LLMCallLog 记账标注
    chat_source: str | None = None # 与其它 AI 端点同协议
```

**SSE 协议**：与 chat/generate 完全一致的事件集（token/thinking/tool_call/tool_result/heartbeat/error）。差异点：

- `done` payload：`{"content": <权威全文 Markdown>, "section_id": "..."}`。前端收到后整体替换本地拼接缓冲（参考 resume 端点 done.content 先例，防流式拼接误差）。
- 不发 `title`（不建会话）；不产出 `interrupt`（HITL 已禁用，见下）。

**限流**：挂 `AI_LIMIT`（与其他 AI 端点同档）。**总超时**：沿用 `AGENT_LOOP_TOTAL_TIMEOUT = 120s`（修订输出≈整章长度，与 generate 同档）。

#### 3.1.2 实现要点

1. 前置（开流前完成，真实 HTTP 错误）：`_get_section` 归属校验（404）→ **章节内容非空校验（409）**：判据是 content 抽纯文本后非全空白——不看 status（drafting 状态也可能因断连没有内容）→ `resolve_chat_config`（403/引导）→ directives 与 origin 校验（422）。
2. `build_agent(db, llm_config=..., user_id=..., section=section, intent="edit", tool_scope="section", checkpointer=None)` —— agent 具备 rag_search/save_memory/generate_figure 等工具（修订时可查知识库）；**不传 thread_id**（config=None）。
3. **revise 的输入语义（与 chat/generate 的差异，明确写死）**：
   - agent input = `build_revise_instruction(section, directives)`，**不带任何聊天历史、不调 compress_history、不创建/关联 conversation**（理由：generate 吸收对话意图从零写稿，历史是原料；revise 针对已成文内容做定点修改，现文+建议已自包含，历史反而引入与本次修订无关的噪音）；
   - 记忆检索 query 走 `build_system_prompt` 默认路径（user_input=None → 章节标题+目标）；
   - `chat_source` 复用 AIChatPanel 现有的 LLM 来源选择 UI，确认卡片上不重复造选择器。
4. 流完成：**不写 `section.content`、不建 Message、不触发 summary**。`content` 仅经 done 事件返回。断连/中途停止：丢弃（不落库），用户可从建议入口重新发起（建议源在报告里持久存在，重试成本低）。
5. finally 记账：`LLMCallLog(action="revise", ...)`，meta 带 origin。

#### 3.1.3 禁用 HITL 与 generate 端点同款隐患（v1.2 重写：源码已核验）

**核验事实**：orchestrator.py 三路 `build_agent` 调用（:243 chat、:310 generate、:357 build_resume_agent）**均传入 `checkpointer=get_checkpointer()`**；agent.py:176 的 `interrupt_on = build_interrupt_on(db, checkpointer)` 从 checkpointer 推导——PG 环境下 checkpointer 恒非 None，故 **generate 端点本身就是「checkpointer 非 None + interrupt_on 配置（默认拦 generate_figure）+ config 无 thread_id」的组合**。AGENTS.md 的「checkplayer 为 None 时不拦」fail-open 分支在 chat/generate/resume 三路都不会触发。

**推论**：
1. revise 若照抄 generate 装配，则继承同一组合。langgraph 对「有 checkpointer 但 config 缺 thread_id」的行为未经验证——若框架自动生成 thread_id 并持久化断点，agent 调用被拦工具时修订流挂在 interrupt 上，且 thread_id 从未返回前端，**不可恢复（死流）**。
2. **这同时是 generate 的现存隐患**（触发条件：generate 时 agent 决定调用被拦截工具）。generate 无 message、无 resume 能力，checkpointer 对它**没有收益**（AGENTS.md「有意不传 thread_id」的本意正是不用它的 checkpoint）——传了只有副作用（潜在死流 + 可能的垃圾 checkpoint 写入）。

**处理**：
- **revise**：`build_agent(..., checkpointer=None)`（显式不传）→ interrupt_on 自然为 None → 工具全部直通。一行成本消除整类风险，不赌框架行为。
- **generate（顺带修复，批 1）**：同样去掉 `get_checkpointer()` 传参（恢复其「无 checkpoint」的本意）。修复前先跑 §5 的 HITL 探针测试观察 langgraph 实际行为，把结论记入 GOTCHAS——无论行为如何，去掉 checkplayer 对 generate 都是无损的（它不需要）。
- 若探针发现 langgraph 确实在写垃圾 checkpoint，检查 checkpoint 表存量并清理（运维动作，随修复说明给出 SQL）。

#### 3.1.4 指令构造 `build_revise_instruction(section, directives)`

```
你要对章节《{title}》执行一次针对性修订。

# 修订指令（逐条落实，全部处理）
1. {directive}
2. ...

# 修订约束（必须遵守）
- 最小改动原则：只修改与修订指令相关的段落；未涉及的段落保持原文，禁止重排结构、
  调整编号、改写无关句子。
- 逐字保留：未涉及段落连同其格式（标题层级、列表标记、空行、表格结构）原样输出，
  不做任何风格化改写。
- 术语：若系统提示中给出了本项目术语表，以其为准——正文中不符合术语表的用法
  一并修正为标准术语（即使修订指令未提及）；未给术语表时，沿用全文已确立的用法，
  不引入新的同义表述。
- 若某条指令与章节现状冲突（如建议修改的内容不存在），在相应位置合理落实，
  不虚构不相关内容。
- 输出修订后的整章 Markdown（完整正文，不要输出 diff、解释或前后对照）。

# 现有章节内容（你的输出必须与它逐段对齐，格式风格保持一致）
{tiptap→markdown 全文}
```

> **术语优先级（v1.2 修正，消除 v1.1 内部矛盾）**：v1.1 同时写了「术语沿用全文现状」与 system prompt 术语表层的「必须用标准术语」——当现文恰好含变体（术语检查的正中场景）时两条指令矛盾。v1.2 明确优先级：**术语表 > 沿用现状 > 最小改动**。代价是术语修正会产生超出 directives 范围的额外 hunk——这是用户配表时的合理期望，diff 面板中用户可拒绝对应 hunk。
> 「逐字保留」与「格式风格保持一致」针对**格式伪 diff 噪音**（§7 R2）：LLM 输出与后端 Tiptap→markdown 转换在空行/列表标记风格上的差异会产生内容未变的伪 hunk。

### 3.2 审查端建议定位增强

#### 3.2.1 结构化定位（后端）

现状：`cross_section_issues[].location_sections` 是章节**标题字符串**；`section_issues[]` 已有 `section_key`；**`_aggregate_section_issues`（review_service.py:247，已核验）用「章节标题是否出现在 evidence+suggestion 文本中」做朴素子串匹配聚合**——由此产生两个已知局限，处理如下：

| 局限 | 处理 |
|---|---|
| suggestion 未提及任何章节标题的维度建议，不落入任何章节组（「按章节」视图不可见） | 「按维度」tab 增加修订入口补齐（§3.2.3-③），**不改聚合逻辑** |
| 聚合条目 `suggestion or evidence` 回退 | 接受现状：`DimensionScore.suggestion` 为必填 str，空串概率极低；且 evidence 也具备参考价值（v1.2 关闭 v1.1 的顾虑） |

改造（`review_schema.py` / `review_prompts.py` / `review_service.py`）：

1. `CrossSectionIssue` 增加字段 `location_section_keys: list[str] = []`（旧字段保留渲染用，向后兼容历史数据）。
2. `build_consistency_prompt` 章节清单改为 `"{key}: {标题}"` 格式，prompt 要求 `location_section_keys` 从清单 key 取值。
3. `_check_cross_section_consistency` 后处理兜底：LLM 未给 keys 时按 `location_sections` 标题查本项目 Section 表精确匹配回填。**兜底单点化（v1.2）**：只在后端做，前端直接消费 keys——keys 为空的 issue 仅展示、不提供 chip 入口，前端不再做标题匹配（消除 v1.1 的前后端双重兜底冗余）。

#### 3.2.2 报告时效提示

用户应用修订后回到报告页，旧分数旧建议无标记，易误判「已处理」。修法：报告页拉取项目 sections（现有 API），取 `max(section.updated_at)` 与最新一轮 `review.created_at` 比较——更晚则顶部提示条：「⚠️ 交底书在本轮审查后有修改，建议重新审查以获得最新评估」。
**定性（v1.2 明确）**：近似判断——确认章节等非内容操作也会 touch updated_at 触发提示；但「确认章节」本身会生成 summary、改变后续 AI 输入，「重新审查」提示依然合理。宁可多提示，不做精确 diff 追踪。纯前端计算，旧轮次报告同样适用。

#### 3.2.3 报告页前端（`review/page.tsx`）——三个修订入口

1. **「按章节」tab**：章节标题改为可点击（跳编辑器并定位章节，§3.5.1）；每个章节问题组尾部「AI 修订本章」按钮（Wand 图标），directives = 该组 issues 文本列表。
2. **跨章节 issue 卡**：涉及章节渲染为 chip（来自 `location_section_keys`，key→标题映射用 sections 列表），点击任一 chip → 以 `{suggestion}` 为单条 directive 发起该章节修订；keys 为空的 issue 仅展示。
3. **「按维度」tab（v1.2 新增）**：每个维度卡加「按建议修订」入口——附章节选择下拉（默认第一个未确认章节），directives = `[dimension_scores[i].suggestion]`。补齐「suggestion 未提及章节标题 → 按章节视图不可见」的缺口（§3.2.1）；对「全文术语统一」类天然跨章节的建议，由用户选落点章节。

### 3.3 项目术语表

#### 3.3.1 数据模型（一个 alembic 迁移）

```
project_terms
  id          uuid pk（IdMixin）
  project_id  uuid fk projects.id on-delete cascade, indexed
  term        varchar(100) not null        # 标准术语（唯一约束 project_id+term）
  definition  text nullable                # 术语定义（注入上下文，建议简短）
  variants    jsonb  not null default '[]' # 禁用变体/同义词/错别字列表
  enabled     bool   not null default true
  source      varchar(20) not null default 'manual'   # manual | ai
  created_at / updated_at（TimestampMixin）
  unique(project_id, term)
```

> 迁移注意事项（本项目有前科）：保证 alembic 单头（down_revision 指向当前 head）；若涉及 `scripts/init_db.py` 哨兵逻辑，沿用 `kind='init_dup'` 去重惯例，避免 FK 违例（参考 commit 73926f9 修复的两个存量迁移 bug）。

#### 3.3.2 API（`app/api/terms.py`，挂 `router.py`；全部经 project/term 归属校验，越权 404）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/projects/{pid}/terms` | 列表（term 升序） |
| POST | `/projects/{pid}/terms` | `{term, definition?, variants?}`；唯一冲突 409 |
| PUT | `/terms/{tid}` | 部分更新（term/definition/variants/enabled） |
| DELETE | `/terms/{tid}` | 硬删 |
| POST | `/projects/{pid}/terms/extract` | AI 抽取候选（见下）；挂 AI_LIMIT 限流 |
| POST | `/projects/{pid}/terms/check` | 一致性检查（见下）；挂 AI_LIMIT 限流 |

**extract**（`term_service.extract_candidates`）：
- 输入：项目已写章节全文（复用 `summary_service._extract_text` 抽纯文本，总额 12000 字截断）。
- LLM：`resolve_lite_config` + `with_structured_output(TermCandidates)`，**降级模式照抄 `outline_extractor` 先例（structured_output 失败返回空结果 + 日志，不抛错）**：

```python
class TermCandidate(BaseModel):
    term: str            # 推荐标准术语
    definition: str = ""
    variants: list[str]  # 正文中观察到的其它表述
    occurrences: int     # 标准术语+变体合计出现次数（粗略）

class TermCandidates(BaseModel):
    candidates: list[TermCandidate]   # ≤15 条，按重要性降序
```

- 产出**不入库**，返回候选列表；前端勾选后逐条 POST /terms 入库（source='ai'）。前端去重：term 与已有术语精确匹配置灰；候选 variants 撞已有 term 的给提示。
- 空项目（无已写章节）409；LLM 失败降级返回 `{candidates: [], warning: "..."}`（200，不阻断）。

**check**（`term_service.check_consistency`）双路合并：

1. **规则路（零 token）**：对每个 enabled 术语的每个 variant，在逐章节纯文本中做精确子串扫描 → `rule_issues: [{term, variant, section_keys: [], count}]`（section_keys 为章节 key，前端用 sections 列表映射标题）。
   **误报定性**：子串扫描必然命中复合词（变体「单元」会命中「存储单元」）。规则路结果是**提示性质**，UI 文案明示「子串匹配可能包含误报，请结合上下文判断」；不追求零误报。
2. **LLM 路（lite，fail-open）**：`with_structured_output(DriftSuggestions)`，找「同一概念多种说法但均未登记进术语表」的漂移 → `llm_suggestions: [{concept, variants: [], section_keys: []}]`，前端「加入术语表」一键（预填 term=concept、variants）。失败降级 `llm_suggestions: []` + warning 字段（v1.2 明确降级形态）。
3. **可选 LLM 复核**：请求体 `{llm_verify: bool = false}`（默认关）。开启时把 rule_issues 交 lite 模型逐条判真阳性（复合词误报剔除），返回 `verified: bool` 字段。前端开关默认关、文案「更准但多一次 AI 调用」。
- 术语表为空 → 200 `{rule_issues: [], llm_suggestions: []}`（不调 LLM）。
- 记账：extract/check 的 LLM 路各记 `terms_extract` / `terms_check`（lite）。

#### 3.3.3 生成上下文注入（`context_assembler.build_system_prompt` 新层）

- 位置（✓已核验 parts 结构支持）：**已写章节前文层之后、知识库 RAG 层之前**（术语约束紧贴正文上下文，优先级高于外部参考）。
- 仅注入 `enabled=true` 条目；上限 100 条（超出截断 + warning 日志）；definition 超 200 字截断。
- 格式：

```
# 本项目术语表（写作与修订必须使用标准术语，禁止使用其变体）
- {term}（禁用：变体1、变体2）：{definition}
- {term}（禁用：变体1）
```

- 读取失败静默降级 + `db.rollback()`（与其它层一致，防事务毒化）。
- 动态读取：每次 chat/generate/revise 装配时现查，配置即生效，无会话固化问题。

#### 3.3.4 与用户级术语偏好的关系

`WritingProfile.terminology`（用户级自由文本软偏好）继续在用户画像层注入。项目术语表是**机器可检查的强约束**（变体可扫描），两者并存时项目级优先——注入位置在画像层之前，且措辞为「必须/禁止」。settings 页文案无需改动。

### 3.4 新颖性建议结构化

- 持久化扩展（✓已核验插入点）：主报告流结束、**done 事件发出之前**，`persist_assessment` 调用前先跑 lite 解析 `parse_suggestions(content)`，结果并入同一 dict 写入。fail-open：解析失败/超时不阻断，assessment 仅存 content，日志 warning。

```python
class NoveltySuggestion(BaseModel):
    section_key: str   # 后处理白名单校验：必须 ∈ ["problem","solution","effect","background","summary"]，否则丢弃该条
    text: str          # ≤200 字，可直接作为该章节的修订指令（动宾明确、自包含）

class NoveltySuggestions(BaseModel):
    suggestions: list[NoveltySuggestion]  # ≤4 条
```

- parse prompt 明确「只解析『## 三、差异化撰写建议』段」（v1.2 补：主报告四段结构固定，避免模型从其它段抽取）。
- 存入 `prior_art_refs.assessment.suggestions`（JSONB 内新键，无需迁移）。旧 assessment 无此键，前端兼容；重新评估覆盖（suggestions 重建）；重新**检索**整体重置 prior_art_refs（suggestions 随 assessment 消失）——现有语义自然延伸。
- 断连时整个 assessment 不落库（现有行为），suggestions 亦然。
- 记账 `novelty_parse`（lite）。

### 3.5 前端设计

#### 3.5.1 修订任务 store 与章节定位

`stores/revision-store.ts`（Zustand，不持久化）：

```typescript
interface PendingRevision {
  sectionKey: string
  directives: string[]
  origin: "review" | "novelty" | "terms"
}
// launch(sectionKey, directives, origin) / consume() -> PendingRevision | null
```

- **单值覆盖语义**：新 launch 覆盖旧 pending（一次只持有一个修订任务），文档与 UI 均按此约定。
- **章节定位（✓已核验：编辑器页无 URL 定位机制**，章节为内部 state `current`，无 searchParams）——**批 1 确定任务**：编辑器页支持 `?section={key}` query param（挂载时读取并切到目标章节，读后从 URL 清除避免刷新重复跳转）。所有 launch 跳转统一走它。
- **pending 不匹配当前章节的 UX**：编辑器挂载时若 store 有 pending 但当前章节不匹配，顶部轻提示条「有待执行的修订任务（章节 X）→ 前往」，点击切换章节；确认卡片可关闭（丢弃 pending）。

#### 3.5.2 AIChatPanel 新 phase `revising`

- 状态机扩展：`AIPhase` 增加 `'revising'`。
- 挂载/切章时若 store 有 pendingRevision 且 sectionKey 匹配当前面板 → 弹**修订确认卡片**（顶部卡片，非聊天消息）：
  - 列出 directives 复选框（默认全选）+ 可编辑追加框（手动模式入口）+ 超长 directive 截断至 500 字并提示（v1.2 补：evidence 兜底字符串可能超限）。
  - LLM 来源复用面板现有 chat_source 选择。
  - 「开始修订」→ 勾选项为 directives 调 `api.streamRevise(sectionId, {directives, origin, chat_source})`；revising 进行中不再显示确认卡片（单飞）。
- 流式渲染：复用 AgentSteps（thinking/tool 卡片）+ Markdown 正文（与 generate 阶段同构）。
- done（✓已核验链路）：`setAiDraft(content)` + `handleOpenDiff()`（`diffOrigin='full'`）→ DiffReviewPanel → apply-diff（乐观锁冲突走现有 409 提示）。
- 中断/停止：丢弃缓冲，确认卡片保留可重新发起。
- 修订过程**不产生聊天消息**（不写会话历史）。
- **只读上下文隔离**：admin 临时查看窗口、游客 `/shared/[token]` 页等只读视图**不渲染**确认卡片与术语/修订入口（以编辑器只读态判断，与 SelectionBubbleMenu 在 `editable=false` 时隐藏同模式）。

#### 3.5.3 报告页（review/page.tsx）

见 §3.2.3（三个修订入口 + 时效提示条 + 章节标题 Link）。

#### 3.5.4 术语面板（`components/terms-panel.tsx`）

- 入口：编辑器页顶栏新增「术语」按钮（BookA 图标，与「审查/预览/检索」并列），打开全屏 Dialog。**仅 owner 可编辑上下文显示**。
- 三个区块：
  1. **术语列表**：term / variants chips / definition / enabled Switch / 删除；行内「添加术语」表单。
  2. **AI 抽取**：「从已写章节抽取候选」→ 候选卡片（可勾选，term 重复置灰、variants 撞已有 term 提示）→「入库所选」。
  3. **一致性检查**：「检查全文术语一致性」（旁挂「LLM 复核误报」开关，默认关）→ rule_issues 列表（`{term} ← 误用『{variant}』×N，涉及 {章节}` + 顶部「子串匹配可能包含误报」说明，每条「去修订」launch 到首个涉及章节，directives=[`将本章节中的「{variant}」统一替换为标准术语「{term}」，并保证语句通顺`]）+ llm_suggestions（「加入术语表」预填入库）。

#### 3.5.5 新颖性页（patents/page.tsx）

- 报告卡片下方：若 `assessment.suggestions` 存在，渲染建议卡列表（`{section_key 章节名} · {text}` + 「去修订」按钮 launch）。**目标章节前置校验（v1.2 补）**：suggestions 的 section_key 在项目章节中不存在（模板无此章节）或章节无内容 → 按钮禁用 + 提示文案（「目标章节不存在 / 尚无内容」），避免 launch 后 revise 端点才 409。
- 无 suggestions（旧数据/解析失败）显示兜底入口「手动复制建议去修订」——textarea + 章节选择（仅列出有内容章节）+「开始修订」（走同一 launch 流）。

#### 3.5.6 api.ts / queries.ts / types

- `streamRevise(sectionId, body, onToken, signal, onDone)`（走通用 `_consumeSSE`）。
- `listTerms/createTerm/updateTerm/deleteTerm/extractTerms/checkTerms` + `useTerms` 系列 hooks；报告页补 `useSections` 拉取（时效提示与 key→标题映射用）。
- types：`ReviseRequest`、`TermEntry/TermCandidate/RuleIssue/DriftSuggestion`、`NoveltyAssessment.suggestions?`。

## 4. 边界情况与降级

| # | 场景 | 行为 |
|---|---|---|
| 1 | revise 目标章节无内容（content 空/纯空白，不论 status） | 409「章节尚无内容，请先撰写或生成草稿」 |
| 2 | directives 空/超限（>10 条/单条>500 字）、origin 非白名单 | 422；前端确认卡片禁用开始按钮 + 超长截断提示 |
| 3 | 修订流中断（断网/用户停止/120s 总超时） | 缓冲丢弃（不落库），确认卡片保留可重试 |
| 4 | 历史轮次报告 + 章节内容已变化 | 建议基于当前内容执行（建议非位置锚定），不锁定轮次；报告页时效提示条兜底（§3.2.2） |
| 5 | revise 与 chat/generate 并发同章节 | revise 不写库无冲突；apply-diff 乐观锁兜底 → 409 现有提示 |
| 6 | 修订 confirmed 章节 | diff 应用不改 status；**summary 不自动更新——与编辑器直接编辑既有语义一致，重新确认章节时才刷新**（非 bug，验收勿误报）；版本快照在重新确认时照常触发 |
| 7 | 术语表空 / 全 disabled | 注入层整体跳过；check 返回空且不调 LLM |
| 8 | extract LLM 失败 | 200 + 空 candidates + warning（前端 toast），不阻断（降级同 outline_extractor） |
| 9 | novelty suggestions 解析失败 | fail-open：assessment 仅存 content；前端手动兜底入口 |
| 10 | suggestions 的 section_key 非法（不在白名单） | 后处理丢弃该条 + 日志，不入库 |
| 11 | 旧 ReviewRecord 无 location_section_keys | 后端兜底（§3.2.1-3）写回后即有；运行期仍缺 keys 的 issue 仅展示不提供 chip 入口（**前端不做二次匹配，v1.2 单点化**） |
| 12 | pendingRevision 跨页丢失（刷新） | store 不持久化，刷新即清空——建议源持久存在可重新发起；滞留 pending 可见性见 §3.5.1 提示条 |
| 13 | 术语规则路误报（复合词命中） | 定性提示性质：UI 明示可能误报；可选 llm_verify 复核剔除 |
| 14 | revise 时 LLM 输出偏离（重写过度/格式漂移） | prompt「逐字保留/格式一致」强约束 + diff 人工勾选兜底；**术语修正产生的额外 hunk 是设计内行为（§3.1.4 优先级），用户可拒绝**；验收抽检伪 hunk 占比（§8.6） |
| 15 | 只读上下文（admin 临时查看、游客 shared 页） | 不渲染修订确认卡片与术语/修订入口 |
| 16 | 用户连续发起多个修订任务 | store 单值覆盖；同一面板 revising 进行中不重复发起 |
| 17 | 建议/章节错位（v1.2 补） | 报告页 launch 时 sectionKey 在项目中不存在（章节被删）→ 前端提示「章节不存在」不 launch；patents 页同款前置校验（§3.5.5） |
| 18 | 术语修正超出 directives 范围 | 设计内：术语表 > 最小改动（§3.1.4）；diff 面板逐 hunk 可拒 |

## 5. 测试策略（pytest，SQLite 内存库 + JSONB variant 惯例）

**revise 端点（test_revise_api.py）**
- 归属校验：他人章节 404；空内容章节 409（含 status=drafting 但 content 空）；directives/origin 校验 422。
- SSE：token/done 帧序列；done.content 为全文；**断言不写 section.content、不新建 Message、不建 conversation**。
- **HITL 探针（§3.1.3，批 1 首个测试）**：全局 agent_hitl_config 开启且 agent 带 generate_figure 工具时，revise 流（checkpointer=None）中工具直通、无 interrupt 事件。**同款探针对 generate 各跑一次**（修复前后各一次）：修复前若复现 interrupt/死流即坐实隐患，修复后（去 checkpointer）断言同样直通；观察是否产生垃圾 checkpoint（坐实则给清理 SQL 并记 GOTCHAS）。
- **输入语义断言**：revise 不带聊天历史、不调 compress_history。
- LLMCallLog action=revise（meta.origin）；chat_source 协议与 chat 一致。
- astream_revise 单测（mock agent events）：instruction 含 directives、最小改动约束、「格式一致」与「术语表优先」约束。

**审查定位（test_review_*.py 增补）**
- consistency structured_output roundtrip 含 location_section_keys；LLM 未给时后端标题兜底回填；历史数据兼容（无新字段旧 JSON 可读）。

**术语表（test_terms_api.py）**
- CRUD + 跨用户隔离（他人项目 404、他人 term 404）；unique 冲突 409；variants JSONB 存取。
- extract：mock LLM 两路（成功/失败降级）；空项目 409；限流挂载。
- check：规则扫描纯函数单测（多章节、多变体、计数、复合词命中——断言命中而非漏报）；llm_verify 开/关两路；LLM 路失败降级 `llm_suggestions: []`；空表不调 LLM。
- context_assembler：术语层注入格式 / disabled 不注入 / 超 100 截断 / **注入位置顺序**（前文层后、RAG 层前）/ 读取失败静默。

**novelty（test_novelty.py 增补）**
- parse 成功持久化（done 前完成、只解析第三段）；section_key 白名单过滤；失败 fail-open；重新评估覆盖、重新检索重置。

前端按项目惯例手工走查 + E2E 冒烟（五条验收路径：按章节组/跨章节 chip/按维度卡/术语去修订/新颖性建议卡）。

## 6. 实施顺序（TDD 任务预案，每批独立可合并 --no-ff）

| 批次 | 内容 | 依赖 |
|---|---|---|
| 1 核心管线 | ReviseRequest / astream_revise / build_revise_instruction / revise 端点（checkpointer=None）/ **HITL 探针测试（revise + generate 双跑，坐实则顺带去 generate 的 checkplayer）** / revision store / **编辑器 `?section=` 定位（已确认需要）** / AIChatPanel revising phase / 报告页「按章节」组入口 + 时效提示条 | 无 |
| 2 定位增强 | consistency schema 新字段 + prompt + 后端兜底回填 + 跨章节 chip 入口 + 「按维度」修订入口（v1.2）+ 章节标题 Link | 批 1 |
| 3 术语表 | 迁移 + 模型 + CRUD API + 注入层 + extract/check（含 llm_verify）+ 术语面板前端 | 无（与批 1/2 并行可行，前端「去修订」入口依赖批 1 的 launch） |
| 4 新颖性闭环 | parse_suggestions + 持久化 + 建议卡前端（含目标章节前置校验） | 批 1 |

## 7. 风险与未决事项

- **R1 LLM「最小改动」服从性**：修订模型仍可能重写过度。缓解：指令强约束 + diff 人工审核最终防线；验收抽检 3 个真实章节。若普遍过度，后备改「逐 hunk 定位改写」策略，本期不做。
- **R2 格式伪 diff 噪音**：LLM 输出与 Tiptap→markdown 转换结果的格式差异产生内容未变的伪 hunk。缓解：prompt「逐字保留 + 格式一致」；验收抽检伪 hunk 占比（§8.6）；不达标则后备做 diff_service 规范化预处理（统一列表标记/折叠空行），批 1 验收时决策。
- **R2b generate 隐患（v1.2 并入）**：§3.1.3 坐实的组合在 generate 上线至今未被报告触发，推测因 draft 意图下 agent 极少调 generate_figure——低概率但非零，且修复无损。批 1 探针定夺，不扩大范围。
- **R3 术语抽取噪音**：候选不准导致筛选负担。缓解：≤15 条按重要性排序、勾选制入库。
- **R4 prompt 体积增长**：术语层最多 100 条 + definition 截断，可控；超限优先截断 definition。
- **未决 U1**：术语双向（also_ok）——本期单向，后续按需。
- **U2 已关闭**：revise 显式禁用 HITL（§3.1.3），无配置项。
- **未决 U3**：术语表随归档沉淀（供后续项目复用）——本期不做。

## 8. 验收标准

1. 报告页三类入口（按章节组 / 跨章节 chip / 按维度卡）任一发起 → 编辑器该章节流式修订 → diff 审核勾选应用成功，重新审查分数可见变化；修订应用后回报告页可见时效提示条。
2. 跨章节 issue 能定位章节（keys 或后端兜底回填），chip 入口闭环；章节标题可点击跳编辑器。
3. 术语表：CRUD、AI 抽取勾选入库、一致性检查两路可用（误报有明示、llm_verify 可选）；配表后新会话/生成上下文含术语约束层（后端测试断言注入）。
4. 新颖性评估完成后建议结构化展示，逐条「去修订」闭环走通（目标章节不存在/为空时按钮禁用有提示）；解析失败时手动兜底入口可用。
5. 既有测试无回归——**相对既有 79 失败基线不新增失败**；新增测试全绿（Windows 先起 docker postgres/minio，GOTCHAS E4）。
6. **修订质量抽检**：3 个真实章节各修订一次，人工核对 diff——未涉及段落零变更、建议相关段落有落实；伪变更 hunk（仅格式变）占比 >30% 即触发 R2 后备方案。
7. `docs/llm-usage.md` 增补 4 个调用点（revise 强模型；terms_extract / terms_check / novelty_parse lite）。
8. AGENTS.md 增补约定（修订管线：显式禁 HITL、不 checkpoint 不落库、directives 前端组装、术语表层注入位置与优先级）。

## 附录 A：决策记录

| # | 决策 | 备选 | 理由 |
|---|---|---|---|
| D1 | 独立 revise 端点，不给 generate 加参数 | generate 加 directives 分支 | 语义分离：generate 自动落库（权威草稿）、revise 候选稿必经人工 diff |
| D2 | revise 不传 thread_id、不落 Message、不带聊天历史 | 走 chat 端点注入修订消息 | 与 generate 同理防污染 resume 重建；修订非对话行为；generate 需吸收对话意图而 revise 的现文+建议自包含 |
| D3 | directives 前端组装（确认卡片勾选可见） | 后端按 review_id 重组 | 报告 JSON 前端已持有；用户可见可控；端点不耦合建议源结构 |
| D4 | 术语表项目级 | 用户级 / 全局库 | 术语体系属于案件；用户级软偏好已存在；全局库属已砍的平台化 |
| D5 | 建议处理状态不持久化，时效提示条替代 | ReviewRecord 加 processed 标记 | 快照语义；状态机复杂度不值；趋势图+提示条已覆盖需求 |
| D6 | 术语统一走 LLM 修订而非文本替换 | Tiptap JSON 字符串替换 | 跨节点替换风险高不保证通顺；修订管线现成 |
| D7 | novelty 建议用 lite 在 done 前同步解析 | 主报告输出机器可读块 / 异步补写 | 主报告纯 Markdown 流式可读；lite 足够；同步免轮询 |
| D8 | 修订必须人工 diff 审核 | 自动应用开关 | 内容安全底线 |
| D9（v1.2 重述） | revise `checkpointer=None` 显式禁 HITL——**源码已核验**三路 build_agent 均传全局 checkplayer，generate 同款组合坐实存在 | 依赖「无 thread_id 不拦」隐式行为 | langgraph 对该组合行为未验证，最坏死流不可恢复；revise 不需要 checkpoint，不传即零成本消除；generate 顺带修复（无收益纯隐患） |
| D10 | 规则路误报定性提示 + 可选 llm_verify | 中文词边界精确匹配 | 误报人工判断成本低；精确分词复杂度不成比例 |
| D11 | 报告时效前端比较 updated_at | 后端算 stale 标记 | 纯展示逻辑前端已有全部数据；近似判断宁可多提示 |
| D12（v1.2） | 维度级建议入口放「按维度」tab + 用户选章节 | 改造 _aggregate 聚合逻辑（LLM 定位/结构化） | 聚合是展示优化非修订契约；维度 suggestion 本身完整可执行；改造聚合涉及旧数据 shape 兼容，收益不成比例 |
| D13（v1.2） | 优先级：术语表 > 沿用现状 > 最小改动 | v1.1 的「沿用现状」与术语表层并存 | 并存时现文含变体则两指令矛盾；术语修正是配表用户的合理期望，额外 hunk 可拒 |
| D14（v1.2） | 跨章节 keys 兜底只在后端做 | v1.1 前后端双重兜底 | 单点化消除冗余与不一致；后端一次写回历史数据即收敛 |

## 附录 B：v1.0 → v1.1 自查修订清单

1. §3.1.3 新增：revise 显式禁用 HITL（原依赖未验证隐式行为）；批 1 HITL 探针测试；U2 关闭。
2. §3.1.4 新增「逐字保留/格式一致」；§7 新增 R2 伪 diff 风险与后备；§8.6 抽检标准。
3. §3.3.2 规则路误报定性 + UI 明示；可选 llm_verify；extract 降级照抄 outline_extractor；extract/check 补限流。
4. §3.4 明确解析时机（done 前同步）与 section_key 白名单；断连语义对齐。
5. §3.2.2 报告时效提示条（D11）。
6. §3.5.1 定位机制待验证 + pending 滞留提示条 + 单值覆盖语义。
7. §3.5.2 只读上下文隔离；chat_source 复用。
8. §3.1.1 origin 白名单；§3.1.2 空章节判据看 content；revise 输入语义写死。
9. §3.3.1 迁移注意（alembic 单头 + init 哨兵惯例）。
10. 边界表补 #6/#13/#15/#16；§5 测试补探针/输入语义/注入顺序/白名单/llm_verify；§8.5 措辞改相对基线；新增 U3。

## 附录 C：v1.1 → v1.2 二轮逻辑审查修订清单（含源码核验）

**源码核验结论（消除 v1.1 的「待验证」）**：
1. 〔核验〕orchestrator.py:243/:310/:357——chat/**generate**/resume 三路均传 `checkpointer=get_checkpointer()`；agent.py:176 interrupt_on 由 checkpointer 推导。→ §3.1.3 重写：**generate 同款隐患坐实存在**（非 revise 新引入），revise 不传 checkpointer，generate 批 1 顺带修复；探针测试双跑；R2b 并入。D9 重述。
2. 〔核验〕review_service.py:247 `_aggregate_section_issues` 朴素标题子串匹配坐实 → §3.2.1 两个局限分列处理：**「按维度」tab 新增修订入口**（§3.2.3-③，D12）；evidence 回退接受现状（suggestion 必填，概率极低，v1.1 顾虑降级关闭）。
3. 〔核验〕编辑器页无 URL 章节定位（内部 state，无 searchParams）→ §3.5.1 定位机制从「若无则加」改为**批 1 确定任务**。
4. 〔核验〕ai-chat-panel.tsx:515 `handleOpenDiff` 依赖 aiDraft state → §3.5.2 revise done 链路确认成立（标注已核验）。
5. 〔核验〕novelty_service.py:134 `persist_assessment` 端点 done 前调用 → §3.4 解析插入点确认。
6. 〔核验〕context_assembler.py:363+ parts 顺序 → §3.3.3 注入位置确认可行。

**逻辑修正**：
7. **消除 v1.1 内部矛盾（§3.1.4 / D13）**：「术语沿用全文」与术语表层「必须用标准术语」冲突——改为术语表 > 沿用现状 > 最小改动；边界 #18；指令文本同步改写。
8. 跨章节 keys 兜底**单点化**（D14）：只后端做，前端去掉二次匹配；边界 #11 更新。
9. §3.4 parse prompt 补「只解析第三段」约束（报告四段结构固定）。
10. §3.5.5 建议卡目标章节前置校验（不存在/无内容禁用+提示）；边界 #17；§8.4 验收同步。
11. §3.3.2 check LLM 路失败降级形态明确（llm_suggestions: [] + warning）。
12. §3.1.1 补 120s 总超时沿用；§3.5.2 确认卡片超长 directive 截断提示；§3.2.2 时效提示「近似判断、宁可多提示」定性；§3.5.6 报告页补拉 sections（时效提示与 key→标题映射）；§5 探针测试扩至 generate 双跑、E2E 路径扩至五条。
