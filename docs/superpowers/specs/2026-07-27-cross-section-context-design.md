# 跨章节上下文注入（撰写侧方案 D）— 设计契约

> 日期：2026-07-27
> 状态：已批准
> 范围：`apps/api/app/ai/`（agent / orchestrator / context_assembler）
> 关联：补齐设计文档 5.4「五层上下文装配」、5.10「章节 summary」在 agent loop 路线（Q16-A）下的回归修复
> 背景：本 spec 源自一次 `/grilling` 会话，根因取证见下文 §1.3

---

## 1. 目标与范围

### 1.1 做什么

修复"写完一章进下一章，AI 失忆"的真痛点。根因是 agent loop 路线（`astream_chat` / `astream_generate`）改造时绕过了原有的上下文装配（`assemble_messages`），导致 agent 拿到的只有静态角色 prompt + 一条孤立指令，**看不到项目标题、看不到已写章节、甚至看不到本章节对话历史**。

四项修复（按依赖顺序）：

| 编号 | 修复 | 文件 |
|---|---|---|
| **L1** | `astream_chat` / `astream_generate` 接回 `assemble_messages` 装配出的 system content，传给 agent | `orchestrator.py` |
| **L2** | `astream_chat` / `astream_generate` 把本章节 `history` 透传给 agent | `orchestrator.py` |
| **L4** | 项目元信息（`title` + `metadata`）注入 system prompt 顶部 | `context_assembler.py` |
| **前文直注入** | 同项目所有非空章节的纯文本（截断到 token 软上限）直接塞进 system prompt，**不走 summary** | `context_assembler.py` |

### 1.2 不做什么（YAGNI，显式排除）

| 排除项 | 理由 |
|---|---|
| 增量更新 summary / summary 版本号 / 并发处理 | 不解决"AI 没看到原文"这个核心痛点；summary 是"摘要的摘要"，信息层层失真。进 backlog |
| 全文视图 / 并排视图 UI | UI 不解决 AI 失忆。进 backlog |
| 审查引擎改造（R-A/R-B/R-C/R-D） | 无真实数据、无亲历痛点驱动，全进 backlog（详见 grill 会话 Q11/Q12 决策） |
| 自定义 deepagents 中间件做动态 prompt | deepagents `system_prompt` 构造时锁定，但天工现状本就每请求重建 agent（无 `lru_cache`），走"每次重建 + 动态拼装"零阻力，无需中间件复杂度 |
| token 计数精确化 / 分块/滑动窗口 | MVP 阶段无真实长文数据，8000 字软上限覆盖 90% 场景；超长文场景等真实数据出现再优化 |

### 1.3 依赖与前置事实（grill 取证结论）

**事实 1：`system_prompt` 构造时锁定（deepagents 0.6.12）**
- `create_deep_agent` 的 `system_prompt` 参数类型 `str | SystemMessage | None`，**不支持 callable / RunnableConfig / state 注入**
- 源码证据：`deepagents/graph.py:857-863`（用户 prompt 拼在 SDK base prompt 前）→ `langchain/agents/factory.py:966-972`（转 `SystemMessage`）→ `factory.py:1433-1489`（`model_node`/`amodel_node` 闭包捕获，每次调用 prepend）
- **结论**：动态 prompt 只能在**构造 agent 时**注入

**事实 2：天工现状每请求重建 agent**
- `agent.py:100-108` `build_agent` 直接 `return create_deep_agent(...)`，无 `@lru_cache`
- `orchestrator.py:100-102`（chat）、`:146-148`（generate）每次都 `agent = build_agent(...)`
- **结论**：把 `SYSTEM_PROMPT` 静态字符串升级为 `build_system_prompt(db, section)` 动态函数，性能与现状持平，零新增开销

**事实 3：`build_agent` 签名不含 section**
- 当前签名 `build_agent(db, *, llm_config, user_id)`
- **决策（grill Q13）**：扩展为 `build_agent(db, *, llm_config, user_id, section=None)`，内部装配上下文。改动集中、调用方只多传一个参数

---

## 2. 总体架构与数据流

### 2.1 改造前后对比

**改造前（当前 bug 状态）：**
```
用户点「生成下一章」
  └─ api/ai.py generate_draft()
       └─ orchestrator.py astream_generate(db, section, history, ...)
            │  history 参数收了但没用 ⚠️
            └─ agent.py build_agent(db, llm_config, user_id)
                 │  system_prompt = SYSTEM_PROMPT  ← 静态、空泛的角色定义
                 └─ create_deep_agent(model, system_prompt=SYSTEM_PROMPT, ...)
            └─ agent.astream_events({"messages": [{"role":"user","content": instruction}]})
                                                  ↑ 只有一条孤立指令
```
agent 看不到：项目标题、已写章节、本章节对话历史、当前章节策略。

**改造后（方案 D）：**
```
用户点「生成下一章」
  └─ api/ai.py generate_draft()
       └─ orchestrator.py astream_generate(db, section, history, ...)
            └─ agent.py build_agent(db, llm_config, user_id, section=section)  ← 新增 section
                 │  system_prompt = build_system_prompt(db, section)  ← 动态装配
                 │    ├─ 项目元信息（title + metadata）       [L4]
                 │    ├─ 当前章节策略（goal + output_format）
                 │    ├─ 已写章节纯文本（截断到 8000 字）     [前文直注入]
                 │    └─ SYSTEM_PROMPT 角色定义（拼接在末尾）
                 └─ create_deep_agent(model, system_prompt=<动态>, ...)
            └─ agent.astream_events({"messages": [
                    {"role":"user","content": msg} for msg in history  ← [L2] 透传历史
                  ] + [{"role":"user","content": instruction}]})
```

### 2.2 模块分层

```
┌─────────────────────────────────────────────────────────────┐
│  API 层  apps/api/app/api/ai.py                              │
│  chat() / generate_draft() / rewrite()                       │
│  零改动：history 已从 _get_section_with_history 取得并传入   │
└──────────────────────┬──────────────────────────────────────┘
                       │ 调用
┌──────────────────────▼──────────────────────────────────────┐
│  Orchestrator 层  apps/api/app/ai/orchestrator.py            │
│  astream_chat / astream_generate  ← 核心改造点 [L1][L2]      │
│  - 把 section 传给 build_agent                                │
│  - 把 history 展开成 messages 列表传给 agent                  │
└──────────────────────┬──────────────────────────────────────┘
                       │ 调用
┌──────────────────────▼──────────────────────────────────────┐
│  Agent 工厂层  apps/api/app/ai/agent.py                      │
│  build_agent(db, *, llm_config, user_id, section=None)       │
│  - section 非 None 时：调 build_system_prompt(db, section)    │
│  - section 为 None 时：用 SYSTEM_PROMPT 兜底（向后兼容）      │
└──────────────────────┬──────────────────────────────────────┘
                       │ 调用
┌──────────────────────▼──────────────────────────────────────┐
│  上下文装配层  apps/api/app/ai/context_assembler.py          │
│  build_system_prompt(db, section) -> str  ← 新函数           │
│  - 装配项目元信息 [L4]                                        │
│  - 装配当前章节策略                                           │
│  - 装配已写章节纯文本（截断到 8000 字）[前文直注入]            │
│  get_written_sections_text(db, project_id, exclude_key)      │
│  - 查同项目所有非空章节（不论 status）                        │
│  - 排除当前章节                                               │
│  - 截断到 8000 字                                             │
│  assemble_messages(...)  ← 保留，旧路径 stream_* 仍用         │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 关键架构决策

**① 走"每次重建 agent + 动态拼装 system_prompt"，不引入 deepagents 中间件**

deepagents 0.6.12 的 `system_prompt` 构造时锁定（闭包捕获），动态注入唯一干净的官方扩展点是自定义 `AgentMiddleware.wrap_model_call` + `state_schema`/`context_schema`。但天工现状：
- `build_agent` 本就每请求重建（无 `lru_cache`）
- 未使用 `state_schema`/`context_schema`

引入中间件需新增 `state_schema` 定义 + 中间件类 + state 注入逻辑，工程量是"每次重建"方案的 3-5 倍，且收益为零（性能持平）。**YAGNI，直接走每次重建。**

**② 前文走"原文直注入"，不走 summary**

grill Q4 决策：核心痛点是"AI 没看到原文"（病 A），不是"摘要不够勤快"（病 B）。summary 是"摘要的摘要"，对短章节（如发明名称 30 字）会扩写成 150 字废话，信息层层失真。原文直注入保证 AI 看到真实内容。

**③ 前文注入 8000 字软上限（T1 方案）**

grill Q13 决策：全文塞 + 8000 字截断前文。理由：
- MVP 阶段无真实长文数据，根本到不了 5000 字
- 8000 字覆盖 90% 真实交底书规模
- 不引入摘要复杂度
- 超长文场景（>8000 字前文）等真实数据出现再做分块/滑动窗口

**④ `build_agent` 扩展 `section` 参数，而非让调用方拼装 prompt**

grill Q13 决策（用户选）：`build_agent(db, *, llm_config, user_id, section=None)`。理由：
- 改动集中，调用方只多传一个参数
- 上下文查询逻辑（查 project、查已写章节）封装在 agent 工厂内，调用方无感
- `section=None` 兜底保持向后兼容（未来若有非章节场景的 agent 调用）

---

## 3. 详细设计

### 3.1 `context_assembler.py` 新增函数

#### 3.1.1 `build_system_prompt(db, section) -> str`

装配动态 system prompt。拼接顺序（**项目元信息在前，已写章节在中，章节策略+角色定义在后**）：

```python
def build_system_prompt(db, section: Section) -> str:
    project = db.get(Project, section.project_id)
    sp = get_section_prompt(section.key)

    parts: list[str] = []

    # [L4] 项目元信息层（顶部，全局上下文）
    parts.append("# 当前交底书项目")
    parts.append(f"项目标题：{project.title}")
    if project.metadata_:  # dict，可能含技术领域、关键词等
        meta_text = _format_metadata(project.metadata_)
        if meta_text:
            parts.append(f"项目背景信息：\n{meta_text}")

    # [前文直注入] 已写章节层（中部，跨章节上下文）
    written = get_written_sections_text(db, section.project_id, exclude_key=section.key)
    if written:
        parts.append("# 已完成章节内容（请保持术语、技术方案一致性）")
        parts.append(written)

    # 章节策略层（底部偏上，当前章节聚焦）
    parts.append("# 当前正在撰写章节")
    parts.append(f"章节标题：【{section.title}】")
    parts.append(f"本章目标：{sp.goal}")
    parts.append(f"输出格式要求：{sp.output_format}")

    # 角色定义层（最底部，兜底规范）
    parts.append(SYSTEM_PROMPT)

    return "\n\n".join(parts)
```

**为什么项目元信息在顶部、角色定义在底部？**
- 项目元信息是"全局不变量"，应最先建立上下文
- 角色定义是"行为规范"，模型在看到具体任务后理解规范更准确
- 此顺序与原 `assemble_messages` 的拼接顺序一致（项目摘要 → 章节策略 → 系统 prompt），保持心智模型统一

#### 3.1.2 `get_written_sections_text(db, project_id, exclude_key) -> str`

查询同项目所有**非空**章节（不论 status，排除当前章节），提取纯文本，截断到 8000 字。

```python
WRITTEN_SECTIONS_CHAR_BUDGET = 8000  # 前文注入字符软上限（T1 方案）

def get_written_sections_text(db, project_id, exclude_key: str) -> str:
    sections = db.scalars(
        select(Section).where(
            (Section.project_id == project_id)
            & (Section.key != exclude_key)
            & (Section.content.isnot(None))
        ).order_by(Section.order)
    )
    parts: list[str] = []
    total = 0
    for s in sections:
        text = _extract_text(s.content).strip()
        if not text:
            continue
        chunk = f"## {s.title}\n{text}"
        if total + len(chunk) > WRITTEN_SECTIONS_CHAR_BUDGET:
            # 软上限：保留前面已装配的，当前章截断后中止
            remaining = WRITTEN_SECTIONS_CHAR_BUDGET - total
            if remaining > 100:  # 剩余空间太小就不塞半截
                parts.append(f"## {s.title}\n{text[:remaining]}\n…（已截断）")
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)
```

**关键设计点：**
- **不论 status**：drafting / confirmed 都注入。grill 取证发现 summary 只在 confirmed 后生成是 L3 bug 的根因之一；前文直注入绕开 summary，自然不受 status 限制
- **`content.isnot(None)`**：空章节（content 为 None）跳过
- **8000 字软上限**：按章节顺序装配，超限时截断当前章并中止（保证前面的章节完整）
- **复用 `_extract_text`**：从 `summary_service` 导入（已有函数，提取 Tiptap JSON 纯文本）

#### 3.1.3 `_format_metadata(metadata: dict) -> str`

格式化项目 metadata（JSON dict）为可读文本。metadata 结构未定死，做防御性格式化：

```python
def _format_metadata(metadata: dict) -> str:
    if not isinstance(metadata, dict) or not metadata:
        return ""
    # 防御性：只取字符串/数字值，跳过嵌套结构
    lines = []
    for k, v in metadata.items():
        if isinstance(v, (str, int, float)):
            lines.append(f"- {k}：{v}")
    return "\n".join(lines)
```

### 3.2 `agent.py` 扩展 `build_agent`

```python
def build_agent(
    db, *, llm_config: ResolvedChatConfig, user_id,
    section: Section | None = None,  # ← 新增
) -> CompiledStateGraph:
    check_tool_support(model=llm_config.model)
    store = MinIOSkillStore(bucket="global")
    backend = StoreBackend(store=store, namespace=lambda ctx: ("skills",))
    skill_sources = build_agent_skill_sources(db, user_id=user_id)
    llm = get_llm(llm_config, streaming=True)

    # [L1][L4][前文直注入] section 非 None 时装配动态 system prompt
    if section is not None:
        from app.ai.context_assembler import build_system_prompt
        system_prompt = build_system_prompt(db, section)
    else:
        system_prompt = SYSTEM_PROMPT  # 向后兼容兜底

    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        tools=[rag_search_tool],
        skills=skill_sources if skill_sources else None,
        backend=backend,
        store=store,
    )
    return agent
```

**向后兼容性：** `section` 默认 None，现有非章节场景调用（如有）不受影响。但本 spec 范围内，所有 agent 调用点（chat/generate）都会传 section。

### 3.3 `orchestrator.py` 改造 `astream_chat` / `astream_generate`

#### 3.3.1 `astream_generate`（[L1] + [L2]）

```python
async def astream_generate(
    db, section: Section, history: list[Message],
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    from app.ai.agent import build_agent

    # [L1] 传 section，让 build_agent 装配动态 system prompt
    agent = build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section), section=section)

    sp = get_section_prompt(section.key)
    instruction = (
        f"请根据对话历史和已完成章节，整理生成本章节【{section.title}】的草稿。"
        f"要求：{sp.output_format}。用 Markdown 格式输出。"
    )

    # [L2] 透传本章节对话历史
    messages = []
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": instruction})

    async for event in agent.astream_events({"messages": messages}, version="v2"):
        # ... 事件透传逻辑不变
```

**关键改造：**
1. `build_agent(...)` 新增 `section=section` 参数（[L1]）
2. `messages` 不再只有一条 instruction，而是 `history + instruction`（[L2]）

#### 3.3.2 `astream_chat`（[L1] + [L2]，对称改造）

```python
async def astream_chat(
    db, section: Section, history: list[Message], user_input: str,
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    from app.ai.agent import build_agent

    # [L1] 传 section
    agent = build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section), section=section)

    # [L2] 透传历史 + 当前用户输入
    messages = []
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_input})

    async for event in agent.astream_events({"messages": messages}, version="v2"):
        # ... 事件透传逻辑不变
```

#### 3.3.3 `astream_rewrite` 不动

`astream_rewrite`（段落重写）走的是 `astream_llm` 直连路径，不经过 agent loop，且其语义是"选中文字 + 指令重写"，不需要跨章上下文。**本 spec 不改。**

### 3.4 旧路径 `stream_chat` / `stream_generate` 的处置

**保留不动。** 理由：
- 这两个同步函数当前在 orchestrator 里**已无调用方**（grep 确认 `astream_*` 是唯一在用路径）
- 但它们调用了 `assemble_messages` + `get_project_summaries`，是"上下文装配正确"的活样本
- 保留作为参考实现，未来若需要同步路径（如 CLI 工具）可复用
- **不删除，避免破坏可能的外部依赖**

**注：** `get_project_summaries` 因 `stream_*` 保留而保留。但本 spec 不再依赖它（前文直注入绕开了 summary）。它成为"历史代码"，等未来清理。

---

## 4. 边界情况与降级

### 4.1 token 超限

**场景：** 前文 8000 字 + 项目元信息 + 章节策略 + 角色定义，叠加后 system prompt 可能接近某些模型的 context window（如 8k token 模型）。

**处理：**
- `get_written_sections_text` 的 8000 字软上限是**字符级**截断，保守估计约 4000-6000 token
- 加上其他部分，总 system prompt 约 5000-7000 token
- 对主流模型（GLM-4 128k、DeepSeek 64k、GPT-4o 128k）安全
- **若用户配置了小 context 模型（如 8k）导致超限：** LLM 层会返回 context length exceeded 错误，经 `friendly_llm_error` 转友好提示。**本 spec 不做预防性处理**——等真实遇到再优化（YAGNI）

### 4.2 项目无 metadata

**场景：** `project.metadata_` 为 None 或空 dict。

**处理：** `_format_metadata` 返回空字符串，`build_system_prompt` 跳过该段。system prompt 仍有项目标题 + 章节策略 + 角色定义，不空。

### 4.3 当前章节是第一章

**场景：** 写第一章（如"发明名称"）时，`get_written_sections_text` 返回空（无其他非空章节）。

**处理：** `build_system_prompt` 跳过"已完成章节内容"段。system prompt 仍有项目标题 + 章节策略 + 角色定义。**符合预期——第一章本就不该有前文上下文。**

### 4.4 history 为空（直接生成草稿，无对话）

**场景：** 用户没和 AI 对话，直接点"生成草稿"。

**处理：** `messages` 列表只有一条 instruction（无 history 前缀）。agent 仍能基于 system prompt 里的项目元信息 + 已写章节生成。**符合预期——前文上下文不依赖对话历史。**

### 4.5 章节 content 是无效 Tiptap JSON

**场景：** `section.content` 存在但结构损坏（如手动改库）。

**处理：** `_extract_text` 用递归 walk，对非预期结构返回空字符串。该章节在前文注入中被跳过。**不影响其他章节注入。**

---

## 5. 测试策略

### 5.1 测试注入点选型

基于 grill 调研，本 spec 涉及 3 层测试，分别用不同 mock 模式：

| 测试目标 | mock 模式 | 注入点 | 测试文件 |
|---|---|---|---|
| `build_system_prompt` 装配正确性 | 无 mock（纯函数 + DB） | 直接调函数 | `test_context.py`（扩展） |
| `get_written_sections_text` 过滤 + 截断 | 无 mock（纯 DB 查询） | 直接调函数 | `test_context.py`（扩展） |
| `build_agent` 传 section 时装配动态 prompt | 模式 C：mock `create_deep_agent` 捕获 system_prompt | `app.ai.agent.create_deep_agent` | `test_agent_factory.py`（扩展） |
| `astream_generate` / `astream_chat` 传 section + history | 模式 B：mock `build_agent` 捕获调用参数 | `app.ai.agent.build_agent` | `test_orchestrator.py`（**新建**） |

### 5.2 测试用例清单

#### `test_context.py` 扩展（`build_system_prompt` + `get_written_sections_text`）

| 用例 | 验证点 |
|---|---|
| `test_build_system_prompt_includes_project_title` | [L4] system prompt 含项目标题 |
| `test_build_system_prompt_includes_metadata` | [L4] metadata 非空时被格式化注入 |
| `test_build_system_prompt_skips_empty_metadata` | [L4] metadata 为 None/空时不报错、不留空段 |
| `test_build_system_prompt_includes_current_section_strategy` | 含当前章节 goal + output_format |
| `test_build_system_prompt_includes_written_sections` | [前文注入] 含已写章节标题 + 内容 |
| `test_build_system_prompt_excludes_current_section_from_written` | 已写章节段不含当前章节自身 |
| `test_build_system_prompt_includes_system_prompt_role` | 末尾含 SYSTEM_PROMPT 角色定义 |
| `test_build_system_prompt_first_chapter_no_written` | 第一章时跳过"已完成章节"段，不报错 |
| `test_get_written_sections_text_filters_empty_content` | content 为 None 的章节被跳过 |
| `test_get_written_sections_text_orders_by_section_order` | 按 Section.order 排序 |
| `test_get_written_sections_text_truncates_at_budget` | 超 8000 字时截断 + 标注"已截断" |
| `test_get_written_sections_text_truncation_keeps_earlier_full` | 截断时前面章节保持完整 |

#### `test_agent_factory.py` 扩展（`build_agent` 传 section）

| 用例 | 验证点 |
|---|---|
| `test_build_agent_with_section_uses_dynamic_prompt` | 传 section 时，`create_deep_agent` 收到的 system_prompt 含项目标题 + 章节策略 |
| `test_build_agent_without_section_falls_back_to_static` | 不传 section 时，system_prompt == SYSTEM_PROMPT（向后兼容） |
| `test_build_agent_with_section_prompt_not_equal_static` | 动态 prompt 与静态 SYSTEM_PROMPT 不同（防回归） |

#### `test_orchestrator.py` 新建（`astream_generate` / `astream_chat` 透传）

| 用例 | 验证点 |
|---|---|
| `test_astream_generate_passes_section_to_build_agent` | [L1] `build_agent` 收到 section 参数 |
| `test_astream_generate_passes_history_to_agent_messages` | [L2] agent.astream_events 收到 history + instruction |
| `test_astream_generate_empty_history_only_instruction` | [L2] history 为空时 messages 只有 instruction |
| `test_astream_chat_passes_section_to_build_agent` | [L1] chat 路径对称验证 |
| `test_astream_chat_passes_history_and_user_input` | [L2] chat 透传 history + user_input |

### 5.3 测试数据构造（沿用项目惯例）

- **DB 测试**（`build_system_prompt` / `get_written_sections_text`）：用 `db_session` fixture，直接 ORM 构造 `Project` + 多个 `Section`（不同 status / content），不走 service 函数
- **纯函数测试**（`_format_metadata`）：纯内存 dict 入参
- **agent 工厂测试**：沿用 `test_agent_factory.py` 的 `_FakeChatModel` + mock `create_deep_agent` + `captured` dict 模式
- **orchestrator 测试**：mock `build_agent` 返回 fake agent（参考 `test_llm_config_e2e.py:113-135` 的 `_fake_agent_factory`），用 `captured` 捕获调用参数

---

## 6. 实施顺序（TDD 任务拆分预案）

按依赖关系拆为 4 个 Phase，每 Phase 1-3 个 Task。详细 TDD 步骤（红绿循环 + commit message）见配套 plan 文档。

### Phase 1：上下文装配函数（`context_assembler.py`）
- Task 1.1：实现 `get_written_sections_text`（含过滤 + 截断）
- Task 1.2：实现 `build_system_prompt`（含项目元信息 + 章节策略 + 前文 + 角色）
- Task 1.3：实现 `_format_metadata`（防御性格式化）

### Phase 2：Agent 工厂扩展（`agent.py`）
- Task 2.1：扩展 `build_agent` 签名，section 非 None 时调 `build_system_prompt`

### Phase 3：Orchestrator 改造（`orchestrator.py`）
- Task 3.1：`astream_generate` 传 section + 透传 history
- Task 3.2：`astream_chat` 对称改造

### Phase 4：回归与集成验证
- Task 4.1：跑全量 AI 测试集，确认无回归
- Task 4.2：手动 dogfood（用真实交底书流程验证"写完题目进下一章不失忆"）

---

## 7. 风险与未决事项

### 7.1 已识别风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 8000 字软上限对小 context 模型仍可能超限 | 极少数模型配置下报 context exceeded | 本 spec 不做预防；等真实遇到再优化（YAGNI） |
| `_extract_text` 对损坏 Tiptap JSON 的鲁棒性 | 极端情况下返回空，该章节被跳过 | 已有递归 walk 防御；不额外处理 |
| 旧路径 `stream_*` + `get_project_summaries` 成为死代码 | 代码可读性下降 | 保留作参考；未来清理时一并删除 |

### 7.2 显式推迟到 backlog（grill 决策）

| 事项 | 触发条件 |
|---|---|
| 审阅侧 R-A（补术语/标号/衔接维度） | dogfood 时真遇到术语飘移 |
| 审阅侧 R-B（权利要求章节 + 迁移） | 真实用户需要写权利要求时 |
| 审阅侧 R-C（去审查引擎 3000 字截断） | dogfood 时发现审查不全 |
| 审阅侧 R-D（全文审查报告 UI） | 真想看全文审查报告时 |
| 撰写侧前文分块/滑动窗口优化 | 真实交底书前文 >8000 字时 |
| UI 全文视图/并排视图 | 撰写流程顺畅后，UI 痛点浮现时 |

### 7.3 未决事项

无。所有设计决策已在 grill 会话 Q1-Q13 中敲定。

---

## 8. 验收标准

本 spec 完成的判定条件：

1. **功能验收（dogfood）：** 新建项目 → 写完"发明名称"章节 → 进入"技术领域"章节直接点"生成草稿"（不重复说明）→ 生成的草稿**明确引用了发明名称里的技术方向**，证明 AI 看到了前文
2. **测试验收：** §5.2 列出的全部测试用例通过；现有 AI 测试集（`test_ai.py` / `test_agent_factory.py` / `test_context.py` / `test_llm_config_e2e.py` / `test_llm_token_logging.py`）零回归
3. **代码验收：**
   - `build_agent` 签名扩展为 `(db, *, llm_config, user_id, section=None)`
   - `astream_generate` / `astream_chat` 传 `section=section` + 透传 history
   - `context_assembler.py` 新增 `build_system_prompt` + `get_written_sections_text` + `_format_metadata`
   - 旧路径 `stream_*` + `get_project_summaries` 保留不动

---

## 附录 A：grill 会话决策记录

本 spec 源自一次 8 轮 `/grilling` 会话，关键决策链：

| 轮次 | 决策 |
|---|---|
| Round 1-3 | 用户从"分章 vs 整篇"的抽象讨论，被 grill 出真实痛点："写完题目进下一章，AI 上下文丢失" |
| Round 4（Q4） | 痛点定性为**病 A**："AI 没看到原文"，非"摘要不够勤快"（病 B） |
| Round 4（Q5） | 选**方案 D**（前文直注入），放弃方案 C（增量 summary） |
| Round 4（Q6） | 用户坚持"审阅侧也要管" |
| Round 5-6 | 审阅侧 R-A/R-B/R-C/R-D 工作量叠加 15-23 天，被 grill 出"全是想象、无亲历痛点" |
| Round 7（Q11） | 用户承认**状态甲：无真实数据** |
| Round 7（Q12） | 审阅侧全部进 backlog，本轮只做撰写侧方案 D |
| Round 8（Q13） | token 预算选 **T1**（全文塞 + 8000 字软上限）；`build_agent` 扩展 `section` 参数 |

**核心教训：** 抽象的"应该看整篇"会导向过度设计（15-23 天）；代码取证 + 诚实自省能把方案收敛到 3-4 天的真痛点修复。
