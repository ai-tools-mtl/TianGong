# ChatGPT 式项目初始化助手 — 设计文档

> **日期**：2026-07-31
> **主题**：把项目初始化助手从「塞在项目列表页的弹窗」改造为「ChatGPT 网页版式的独立全屏对话页」——左侧对话列表 + 右侧主对话区，对话在项目创建之前进行，agent 判断时机 + 用户按扳机创建项目并跳转。
> **状态**：设计中

## 1. 背景与目标

当前「项目初始化助手」（commit `ccfd9ec`~`1fd0513`，详见 `docs/superpowers/plans/archive/2026-07-30-init-assistant.md`）是一个塞在项目列表页 `PageHeader` 里的 shadcn `Dialog` 弹窗，三阶段（输入描述 → 对话 → 生成）。问题：

- **不是正常入口**：弹窗形态局促，刷新丢状态，无法作为独立功能入口被感知。
- **首轮就建项目**：用户第一条消息后端就 `create_project` + 8 空章节，聊两句不合适也留下了垃圾项目。
- **创建时机僵硬**：对话与项目强绑，没有「先聊清楚再决定要不要落地」的空间。

本设计把它重做成 **ChatGPT 网页版式的独立全屏对话页**：对话在前、项目在后，agent 判断信息充分后提示用户按扳机创建项目。

### 范围（已确认）

| 维度 | 决策 |
|---|---|
| 形态 | **独立全屏路由页 `/new`**，ChatGPT 式两栏（左对话列表 + 右主对话区） |
| 对话列表 | **只列初始化助手的对话**（项目创建前的临时会话）；落地成项目后从列表消失 |
| 创建时机 | **agent 判断 + 用户按扳机**：agent 标记「信息已充分」，用户点扳机才创建项目 |
| 对话存储 | **后端临时会话**（项目无关，刷新可恢复）；复用 Conversation/Message 表 |
| 创建后 | 对话里出现「项目已创建，点此进入」跳转卡片，点击进入 `/projects/{id}` |

### 非目标（YAGNI）

- **不做全局助手**：列表只列初始化对话，不合并项目内对话、不做跨项目常驻 agent。
- **agent 不自主创建**：只标记时机，扳机永远在用户手里（防垃圾项目）。
- **不保留旧弹窗形态**：`InitAssistantDialog` + `/projects/{id}/init-*` + `from-chat` 删除。
- **不做对话高级管理**：暂不做会话搜索/置顶/文件夹，只做基础列表+切换+删除。

---

## 2. 整体形态与布局

新增独立全屏路由 `/new`，ChatGPT 式两栏布局：

```
┌──────────────┬─────────────────────────────────┐
│  对话列表     │  顶部：标题/状态区               │
│  (左侧栏)    │  ────────────────────────────── │
│              │                                  │
│ • 对话A      │     消息流（占满中间）            │
│ • 对话B(当前)│     user / assistant 气泡         │
│ • 对话C      │     含 agent 提示的「创建项目」   │
│              │     扳机卡片                      │
│ [+ 新对话]   │                                  │
│              │  ────────────────────────────── │
│              │  底部：输入框（Enter 发送）       │
└──────────────┴─────────────────────────────────┘
```

### 左侧对话列表
- 只列**初始化助手的对话**（项目创建前的临时会话，`kind='init' AND project_id IS NULL`）。
- 点击切换/恢复历史对话（后端临时会话，刷新不丢、多设备同步）。
- 顶部「+ 新对话」→ 创建空白对话，右侧显示引导语 + 聚焦输入框。
- **落地成项目后，该对话从列表消失**（`project_id` 被填上，查询条件 `project_id IS NULL` 不再命中）。

### 右侧主对话区
- **空状态**：一句引导语（如「描述你的发明想法，我帮你理清思路并生成交底书初稿」）+ 输入框聚焦。
- **对话中**：消息流（user/assistant 气泡，assistant 用 ReactMarkdown 渲染）+ agent 引导。
- **agent 判断信息充分** → assistant 回复末尾带 `[READY_TO_CREATE]` 标记 → 前端在气泡下方渲染「创建项目」扳机卡片。
- **用户按扳机** → 建项目 + 填 8 章初稿（流式进度卡片）→ 完成后出现「点此进入项目」跳转卡片。

---

## 3. 数据模型：顶层会话（项目无关）

当前 `Conversation`/`Message` 强绑 `section_id`（NOT NULL FK），对话必须挂在项目章节下。新形态要求**对话在项目创建之前就存在**，故引入「项目无关的顶层会话」。

**方案：复用现有表，`section_id` 可空 + 加会话类型标记。**

### Conversation 表（改 `apps/api/app/models/conversation.py`）

| 字段 | 改动 |
|---|---|
| `section_id` | `NOT NULL → NULL`（项目内对话仍挂 section；init 对话不挂） |
| `kind` | **新增** String(20)，默认 `'project'`；取值 `'project'`（项目内对话）/ `'init'`（初始化对话） |
| `project_id` | **新增** UUID NULL，FK→projects（可选；init 对话落地成项目后记下，用于「已落地」判断） |
| `user_id` | **新增** UUID NOT NULL，FK→users。顶层 init 会话无 section/project 可反查归属，必须直接记 user_id；项目内对话也回填 user_id（迁移 backfill）。 |

### Message 表（改 `apps/api/app/models/message.py`）

| 字段 | 改动 |
|---|---|
| `section_id` | `NOT NULL → NULL`（init 消息 section_id 为 NULL，仅靠 conversation_id 归属） |

`Message.conversation_id` 仍是 NOT NULL（消息必须属于某会话），不变。

### 查询语义
- **左侧列表**：`WHERE user_id=当前用户 AND kind='init' AND project_id IS NULL ORDER BY updated_at DESC`。
- **落地后从列表消失**：`project_id` 被填上 → `project_id IS NULL` 不再命中。
- **项目内对话**：仍按 `section_id` 查（既有逻辑不变），`kind='project'` 与 init 会话互不干扰。

### 落地动作（用户按扳机时，由 `/assistant/conversations/{id}/generate` 执行）
1. `create_project` 建项目 + 8 空章节（复用 `project_service.create_project`）。
2. `init-generate` 填充各章节初稿（复用 `astream_init_generate`）。
3. 把该 init 对话的 `project_id` 填上 → 列表自动不再显示。
4. 对话消息保留（不迁移到项目；仅 `project_id` 关联，便于「该项目由这段对话生成」的追溯，本阶段不展示）。

### 迁移（alembic）
- `conversations`：`section_id` 改 nullable；加 `kind`（server_default `'project'`）、`project_id`（nullable FK）、`user_id`（NOT NULL FK→users）。
- `messages`：`section_id` 改 nullable。
- **backfill**：老数据 `kind='project'`（server_default 兜底）；老会话 `user_id` 由 `section_id → section.project_id → project.user_id` 回填（UPDATE ... FROM 子查询）。
- SQLite 测试库注意：FK 改 nullable 用 `batch_alter_table`（项目既有模式）。

---

## 4. 后端 API

新增顶层 init 会话 CRUD + 改造现有 init 端点适配新模型。所有端点需登录（`get_current_user`），按会话 `user_id` 做归属校验。

### 新增端点（顶层 init 会话管理，新文件 `apps/api/app/api/assistant.py`）
```
POST   /assistant/conversations              创建空 init 会话（kind='init', user_id=当前用户），返回 id
GET    /assistant/conversations              列出当前用户的 init 会话（kind='init', project_id NULL, 按 updated_at 倒序）
GET    /assistant/conversations/{id}         取单个会话 + 消息历史（恢复对话用）
DELETE /assistant/conversations/{id}         删除会话（级联消息）
PATCH  /assistant/conversations/{id}         重命名（可选，本阶段可缓做）
```

### 改造的对话/生成端点（原 `/projects/{id}/init-*`）
```
POST /assistant/conversations/{id}/chat      （原 /projects/{id}/init-chat）
  → 不再需要 project_id；消息存到顶层会话（kind='init', section_id=NULL）
  → system prompt 加规则：信息充分时回复末尾输出 [READY_TO_CREATE] 标记
  → SSE 透传标记（前端据此渲染扳机卡片）

POST /assistant/conversations/{id}/generate  （原 /projects/{id}/init-generate）
  → 用户按扳机时调：建项目 + 填 8 章 + 把会话 project_id 填上
  → 流式进度（chapter_start/done）不变，最后返回 {project_id}
```

### agent 判断时机的落地（关键）
- agent 的 `INIT_SYSTEM_PROMPT` 加一条：「当判断已收集到足够信息（技术领域/要解决的问题/大致方案/关键特征），在回复末尾输出 `[READY_TO_CREATE]` 标记。」
- **agent 不直接创建项目**，只**标记时机**；扳机由前端渲染、用户按。
- **兜底**：前端始终提供一个手动「创建项目」入口（不只依赖 agent 标记）——LLM 可能漏标或误标，标记只是「适时提示」。

### 删除的老端点
- `POST /projects/{id}/init-chat`、`POST /projects/{id}/init-generate`、`GET /projects/{id}/init-conversation`、`POST /projects/from-chat`（与新形态冲突，全部删除）。
- `apps/api/app/api/init_assistant.py` 删除；`init_orchestrator.py` 的 `astream_init_chat`/`astream_init_generate` 复用但签名改造（从 `(project, section, history)` 改为 `(conversation, history)`，generate 内部建项目）。

---

## 5. 前端

### 新路由 + 组件
- `apps/web/src/app/(app)/new/page.tsx` —— 路由页，渲染 `<InitAssistant />`。
- `apps/web/src/components/assistant/init-assistant.tsx` —— 两栏主体（左列表 + 右对话区）。
- 复用现有 UI：消息气泡（ReactMarkdown）、Textarea 输入、SSE 消费（`_consumeSSE`）。

### 左侧对话列表
- 调 `GET /assistant/conversations` 列出 init 会话。
- 点击切换（右侧 `GET /assistant/conversations/{id}` 加载历史）+「+ 新对话」（`POST` 创建空会话）。
- 当前会话高亮；落地成项目后 `qc.invalidateQueries` 刷新（该会话从列表消失）。

### 右侧主对话区
- 空状态：引导语 + 输入框聚焦。
- `POST /assistant/conversations/{id}/chat` 流式对话（复用 SSE 消费）。
- **监听 agent 回复里的 `[READY_TO_CREATE]` 标记** → 渲染「创建项目」扳机卡片（在 assistant 气泡下方）；展示前把标记从可见文本剥掉。
- 用户点扳机 → `POST /assistant/conversations/{id}/generate` → 流式 8 章进度（复用进度卡片）→ 完成后出现「点此进入项目」跳转卡片。

### 入口改造（从哪进 `/new`）
- `project-list.tsx`：把 `InitAssistantDialog`（弹窗）替换成跳 `/new` 的链接按钮。
- dashboard 空态：引导语加「AI 对话新建」→ 跳 `/new`。
- 删除 `init-assistant-dialog.tsx`（弹窗形态废弃）。

### api.ts 改造
- 新增：`listAssistantConversations` / `createAssistantConversation` / `getAssistantConversation` / `deleteAssistantConversation` / `streamAssistantChat`（会话级，不绑项目）/ `streamAssistantGenerate`（按扳机建项目+填章）。
- 删除：`createProjectFromChat` / `streamInitChat` / `streamInitGenerate`。

---

## 6. 测试

### 后端
- 顶层会话 CRUD：创建 / 列表（只列 kind=init 且 project_id NULL）/ 取历史 / 删除。
- `/assistant/conversations/{id}/chat`：SSE 流式 + 消息存到顶层会话（section_id NULL）+ agent 回复含 `[READY_TO_CREATE]` 时正确透传。
- `/assistant/conversations/{id}/generate`：建项目 + 填 8 章 + 会话 project_id 填上 + 列表不再显示它。
- 归属校验：非本人会话 404。
- **回归**：老的项目内对话（`kind='project'`，挂 section）不受影响——`section_id` 可空后，项目内 chat/generate/messages 端点仍正常。
- alembic 迁移：老数据正确 backfill `kind='project'` 与 `user_id`。

### 前端
- typecheck + build（无路由/组件错误）。
- 本阶段不强求前端单测，靠 typecheck + 手测。

---

## 7. 风险与缓解

1. **`section_id` 改可空的回归面广**：项目内 chat/generate/messages 等多端点假设 `section_id` 非空 → 迁移后跑全量后端测试确保无回归；查询项目内对话显式 `WHERE kind='project'` 或 `section_id IS NOT NULL`。
2. **agent 标记 `[READY_TO_CREATE]` 不可靠**：LLM 可能漏标或误标 → 前端兜底始终提供手动「创建项目」入口；标记只是适时提示，非唯一路径。
3. **大量空 init 会话堆积**：用户聊了没创建就走 → 本阶段不做自动清理（留 TODO：后台定期清理 N 天未更新且 project_id NULL 的会话）。
4. **Conversation 加 user_id 的迁移**：老会话无 user_id 列，需 backfill；若有 section 已删的孤儿会话（理论上 CASCADE 已清），backfill 失败的极少数可按 NULL 容错或清理。

---

## 8. 与既有工作的衔接

- 复用 `astream_init_generate`（批量填章逻辑，commit `ccfd9ec`）、`markdown_to_tiptap`、`get_section_prompt`、`build_generate_instruction`、`INIT_SYSTEM_PROMPT`（浓缩内置 skill 规范）。
- 复用 SSE 消费 `_consumeSSE`、心跳包装、进度卡片 UI（commit `4f82043`/`1fd0513`）。
- 删除的是「弹窗形态 + 首轮建项目」这条旧链路，保留「对话引导 + 批量填章 + 进度展示」的内核。
