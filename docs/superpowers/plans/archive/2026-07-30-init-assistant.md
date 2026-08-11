# 计划：项目初始化 AI 助手 —— 对话式新建项目 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在项目列表页加一个「对话式新建」AI 助手入口。用户用自然语言描述想法,助手对话几轮后生成项目骨架(8 章初稿)入库,之后用户进项目页用现有逐章节流程微调。**助手只用于初始化,不是项目内常驻统筹 agent。**

**Architecture:** 复用现有 skill/section/generate 子系统,新增一层「项目级初始化编排」。对话挂在项目首个 section 下(复用 Conversation/Message,零 schema 改动);对话结束后后端批量生成 8 章初稿并回填(后端编排,非 LLM tool-call 自写)。底层 LLM 调用复用 `llm_client.astream_llm`。

**Tech Stack:** FastAPI + LangChain(deepagents)+ LangGraph agent loop · Next.js + shadcn/ui 3.x · SSE 流式 · 复用 section_prompts(8 套章节策略)

**Spec reference:** 本计划基于 2026-07-30 的两轮代码调研,非既有 spec 的子系统。关联设计:`docs/superpowers/specs/2026-07-13-tiangong-mvp-design.md`(交底书章节结构、AI 编排)。

---

## 0. 关键背景(调研已确认的现状)

| 关注点 | 现状 | 文件:行号 |
|---|---|---|
| 列表页位置 | 在 dashboard 的 `ProjectList`,非 projects/page.tsx | `apps/web/src/app/(app)/dashboard/page.tsx:1-4` → `apps/web/src/components/project-list.tsx` |
| 现有新建入口 | `CreateProjectDialog`(填 title + template_id 两个字段) | `apps/web/src/components/create-project-dialog.tsx:33-91` |
| 建项目入口 | `create_project(db, user, title, template_id, metadata)` 现成 | `apps/api/app/services/project_service.py:10-47` |
| 章节初始化 | 建项目时立即按模板快照生成 8 个空 section(status=empty, content=None) | `project_service.py:34-44` |
| 单章生成链路 | `astream_generate`(基于 section 对话历史生成本章草稿) | `apps/api/app/ai/orchestrator.py:171-231` |
| 章节策略 | 8 套 `SectionPrompt`(goal/output_format/completion_criteria/few_shot) | `apps/api/app/ai/section_prompts.py` |
| 对话存储 | Conversation/Message **强绑 section_id(NOT NULL)**,无项目级会话 | `apps/api/app/models/conversation.py:19-29`、`message.py:9-19` |
| 草稿落库 | `markdown_to_tiptap(md)` + status: empty→drafting | `apps/api/app/ai/markdown_to_tiptap.py:11`、`apps/api/app/api/ai.py:345-349` |
| Agent 工具 | `create_agent_tools(db, user_id)` 闭包,含 rag_search/save_memory | `apps/api/app/ai/tools.py:17-113` |

---

## 1. 三个关键决策(工程判断,执行时可否决)

### 决策 1:对话存储 —— 先建项目再对话,复用现有表 ✅(推荐)
- 第一轮用户输入后,立即调 `create_project(title=草稿名, metadata={"init_description": ...})` 建项目+8空 section
- 对话挂在项目首个 section(发明名称)下,复用现有 Conversation/Message 表
- **零 schema 改动**,最快验证价值
- 代价:对话语义稍勉强(挂某章节名下),但初始化助手是临时会话,入库生成 8 章后即可结束
- **不选「新增项目级会话表」**:那是为常驻 agent 设计的,本助手是一次性冷启动,不值得改 schema。若未来做项目内常驻 agent 再上 project_id 会话表

### 决策 2:生成粒度 —— 全 8 章初稿(一键成型) ✅(推荐)
- 对话结束后,后端对项目 8 个 section 逐个生成初稿并回填
- 复用现成 `get_section_prompt(key)` + `build_generate_instruction`
- 符合用户「内容填充完毕」预期
- 代价:生成耗时长/token 高 → 用流式 SSE + 前端进度展示缓解;init-generate 端点加可选 `sections` 参数让用户控制生成哪几章

### 决策 3:写入方式 —— 后端批量回填 ✅(推荐)
- 用户点「生成项目」后,后端编排函数循环 8 章:取策略 → 生成 Markdown → `markdown_to_tiptap` → 写 section.content + status→drafting
- **不让 LLM 用 tool call 自写**(那难控进度、易漏章、事务复杂)。后端编排可控、可展示进度、可事务化

---

## 2. 交互流程设计

1. 项目列表页 `ProjectList` 顶部加「AI 对话新建」入口(与现有「新建项目」按钮并列)
2. 点开 → 全屏/侧边对话框
3. **第 1 轮**:用户描述想法 → 助手回复并追问关键技术细节(技术领域/要解决的问题/大致方案)→ **后端同时静默建项目+8空章节,挂对话到首个 section**
4. 后续几轮:助手补充引导,过程中可调 `rag_search` 检索知识库融入
5. 用户点「生成项目骨架」→ 后端流式批量生成 8 章 → 前端展示「正在生成 X/8:章节名...」
6. 完成 → 跳转项目页 `/projects/{id}`,用户看到 8 章初稿,逐章微调

---

## 3. 实施步骤

### 第 1 步:后端 —— 项目级对话编排(核心)
**新文件**:`apps/api/app/ai/init_orchestrator.py`

- [ ] `INIT_SYSTEM_PROMPT`:裁剪自 `context_assembler.py:16-25` 的 `SYSTEM_PROMPT`,重新定位为「项目初始化助手」。目标是引导用户把想法说清楚(技术领域/要解决的问题/大致方案/关键特征),为生成 8 章做准备。**不绑定单 section**。
- [ ] `astream_init_chat(db, project, section, history, user_input, llm_config)`:仿 `orchestrator.py:112-168` 的 `astream_chat`,但用 `INIT_SYSTEM_PROMPT`,挂载首个 section 的 conversation。流式回复 + 可调 `rag_search`/`save_memory` 工具。
- [ ] `astream_init_generate(db, project, history, llm_config, sections=None)`:**批量生成 N 章**。对项目每个 section 循环:
  - 取 `get_section_prompt(section.key)`(`section_prompts.py`)
  - 用 `build_generate_instruction(section)`(`orchestrator.py:81`)构造生成指令
  - 把助手对话历史作为 context + 前面已生成章节的 summary 拼进 messages
  - 调 `llm_client.astream_llm` 生成 Markdown,累积
  - 回写:`section.content = markdown_to_tiptap(md)`、`status: empty→drafting`、`version+1`(乐观锁)
  - 流式产出进度事件:`{"chapter": "背景技术", "index": 3, "total": 8, "status": "generating/done"}`
- [ ] 复用 `_retrieve_knowledge`(RAG)、`section_prompts`、`build_agent`(deepagents agent loop)

**注意**:`build_agent`(`agent.py:38-122`)绑定单 section(system prompt 要 section)。项目初始化对话要么绕过这层用裸 `astream_llm` + 自拼 messages,要么给 agent 传一个「占位 section」。推荐:chat 走 agent loop(能调工具),generate 批量走裸 `astream_llm`(纯生成无需工具)。

### 第 2 步:后端 —— API 端点
**新文件**:`apps/api/app/api/init_assistant.py`(或并入 `apps/api/app/api/ai.py`)

- [ ] `POST /projects/{id}/init-chat`:body `{ message: str }`,流式返回助手回复(SSE,仿 `ai.py` 的 chat 端点)。首轮自动 `_get_or_create_conversation`(`ai.py:57-74`)挂首个 section。
- [ ] `POST /projects/{id}/init-generate`:触发批量生成,body 可选 `{ sections: ["background",...] }`(默认全 8 章)。流式返回进度(SSE:章节名 + 完成状态)。
- [ ] `GET /projects/{id}/init-conversation`:取已有对话历史(刷新页面恢复对话)。
- [ ] 在 `apps/api/app/api/router.py` 注册路由。

### 第 3 步:后端 —— 「描述→建项目」入口
**改**:`apps/api/app/api/projects.py`

- [ ] 新增 `POST /projects/from-chat`:body `{ description: str }`。
  - 从描述提炼标题(或用描述前 30-40 字),调 `create_project(title=..., metadata={"init_description": description})`
  - 返回 `project_id` + 首个 section 的 `conversation_id`
  - 前端拿到 id 后进入对话

### 第 4 步:前端 —— 对话新建入口与对话框
**改**:`apps/web/src/components/project-list.tsx`
- [ ] `PageHeader`(`project-list.tsx:56`)加「AI 对话新建」按钮,与 `CreateProjectDialog` 并列
- [ ] 空态 `EmptyState`(`project-list.tsx:112-118`)也引导此入口

**新文件**:`apps/web/src/components/init-assistant-dialog.tsx` —— 全屏对话框组件:
- [ ] 消息列表 + 输入框,调 `/init-chat` 端点(SSE 消费,仿现有 chat 组件的 SSE 处理)
- [ ] 底部「生成项目骨架」按钮 → 调 `/init-generate`,展示 8 章生成进度(章节卡片逐个变绿)
- [ ] 完成后 `router.push('/projects/{id}')`
- [ ] react-query hooks 加到 `apps/web/src/lib/queries.ts`

### 第 5 步:内置 skill 注入(衔接已完成的 builtin-skills 工作)
- [ ] `INIT_SYSTEM_PROMPT` 的「写作要求」段引用项目已有内置 skill 的核心规则(去 AI 味六大特征 / 英文术语首现翻译 / 有益效果三段式 / 章节语言水位)
- [ ] 来源:`assets/skills/patent-de-ai`、`patent-writing-quality`、`patent-effect-contrast`、`patent-figure-design`(已合入 main,启动自动同步)
- [ ] 让助手引导用户时和生成 8 章时都遵守这些规范——即把 skill 规则浓缩进 init system prompt,而非依赖 agent 运行时加载(初始化场景用浓缩版更可控)

### 第 6 步:测试
**新文件**:`apps/api/tests/test_init_orchestrator.py`、`test_init_assistant_api.py`
- [ ] `astream_init_generate` 生成 8 章、status 正确流转(empty→drafting)、content 非 None
- [ ] `/projects/from-chat` 建项目+返回 id、`/init-chat` 流式、`/init-generate` 批量
- [ ] 部分 section 生成失败时不整体回滚(标记该章失败,其余继续)
- [ ] mock LLM(仿现有 `tests/test_ai.py` 的 mock 模式)

---

## 4. 复用的现成部件(无需重写)

| 部件 | 文件:行号 | 用途 |
|---|---|---|
| `create_project` | `project_service.py:10-47` | 建项目+8空章节,metadata 存对话摘要 |
| `get_section_prompt(key)` | `section_prompts.py` | 每章生成策略(goal/format/criteria) |
| `build_generate_instruction` | `orchestrator.py:81-109` | CoT 分步生成指令 |
| `markdown_to_tiptap` | `markdown_to_tiptap.py:11` | 草稿 Markdown→Tiptap 落库 |
| `astream_llm` / `stream_llm` | `llm_client.py` | 底层 LLM 流式调用 |
| `create_agent_tools` | `tools.py:17-113` | rag_search / save_memory 工具 |
| `build_agent` | `agent.py:38-122` | deepagents agent loop(chat 走) |
| `_get_or_create_conversation` | `ai.py:57-74` | 对话挂在 section 下 |
| Conversation/Message | `models/conversation.py`、`message.py` | 对话存储(挂首个 section) |
| `SYSTEM_PROMPT` | `context_assembler.py:16-25` | 裁剪成 INIT_SYSTEM_PROMPT |
| 4 个内置 skill | `assets/skills/*` | 写作规范注入(去AI味/术语/效果/附图) |

---

## 5. 边界(不做的事)

- ❌ **不做项目内常驻统筹 agent**(用户明确:助手只用于初始化)
- ❌ **不改 Conversation/Message schema**(复用,挂 section;未来做常驻 agent 再上 project_id 会话表)
- ❌ **不做权利要求/客体适格性**(交底书阶段无 claims 实体)
- ❌ **不让 LLM 用 tool call 自写章节**(后端编排批量回填,可控可进度化)

---

## 6. 风险与缓解

1. **8 章生成耗时长/token 高**:流式 SSE 推送「正在生成 X/8」进度;init-generate 加可选 `sections` 参数(指定只生成哪几章,默认全 8);部分章节失败标记不整体回滚。
2. **对话挂首个 section 语义勉强**:助手对话主题是项目级,挂「发明名称」section 下。入库后该 section 也会被生成覆盖,可接受。
3. **标题提炼不准**:`from-chat` 用描述前 30-40 字做标题,用户进项目后可改;或助手对话中追问确认标题。
4. **build_agent 绑定单 section**:chat 走 agent loop(需工具)时,给 agent 传首个 section 作占位(用 INIT_SYSTEM_PROMPT 覆盖其章节 prompt);generate 批量走裸 `astream_llm`(纯生成无需工具),绕开这层绑定。

---

## 7. 分阶段实施建议

- **阶段 A(MVP,先打通主链路)**:第 1 步 + 第 2 步 + 第 3 步 + 简化前端(能对话建项目 + 一键生成 8 章,进度用简单 toast/文字)。验证价值。
- **阶段 B(完整体验)**:第 4 步完整对话框 UI + 8 章生成进度卡片 + 第 5 步 skill 注入。
- **阶段 C(健壮性)**:第 6 步测试 + token 控制(可选参数)+ 部分失败处理。

建议先用 worktree 隔离做阶段 A,跑通后评估生成质量和 token 成本,再决定是否进 B/C。

---

## 附:与刚完成的 builtin-skills 工作的衔接

本计划第 5 步直接消费 `assets/skills/` 下的 4 个内置 skill(已在 main,commit `a587b1c`):
- `patent-de-ai` → 去除生成内容的 AI 味
- `patent-writing-quality` → 英文术语首现翻译 + 章节语言水位
- `patent-effect-contrast` → 有益效果章节用三段式
- `patent-figure-design` → 附图说明章节的设计原则

即:内置 skill 不只是 agent 运行时能力,也是项目初始化助手的写作规范来源——两者协同。
