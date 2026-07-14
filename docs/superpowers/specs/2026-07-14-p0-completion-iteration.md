# 天工 TianGong — P0 验收补全迭代设计文档

> 日期：2026-07-14
> 目标：让 MVP 的 P0 验收表（设计 11.1，31 条）100% 达标，使系统具备「小团队真实跑通写交底书」的能力。
> 关联：本文档是 [MVP 设计文档](./2026-07-13-tiangong-mvp-design.md) 的补充，所有章节号引用均指向该设计文档。

---

## 1. 背景与动机

MVP 全部 P0 功能（计划 1–7b）已落地并端到端验证，但逐条对照 P0 验收表与实际代码后发现：**31 条验收点中有 8 条是欠账**——其中几条代码骨架已写好但未接线，几条完全缺失。这 8 条欠账是系统「距离真实使用」的差距。

本迭代的目标是补齐这 8 条欠账，让 P0 验收表 100% 达标。**不引入 P1 新功能**（PDF 导出、专利检索等留后续）。

### 1.1 核心场景

迭代重心服务于「**我自己 / 小团队先跑通**」——优先解决每天写交底书高频踩到的痛点，运营/审计层放最后。

### 1.2 推进路线

纵向串行（方案 A）：每个子计划独立可验证、可提交，按「解决高频痛点 → 补内容完整 → 让沉淀闭环 → 健壮性与扩展 → 运营」的顺序推进。

---

## 2. P0 验收表核对结果

### 2.1 已达标（19 条，本迭代不动）

1（认证）、2（授权）、3（项目 CRUD）、4（元信息）、5（模板解析）、7（模板管理）、8（选模板建项目）、9（章节大纲）、10（AI 对话）、11（生成草稿）、12（编辑器）、14（跨章节上下文）、16（版本快照）、17（预览）、18（导出）、22（审查）、23（稳定性）、24（Rubric 自定义）、25（知识库自定义上传）、27（管理员全局内容）、28/28a-d（LLM BYOK）、31（创建管理员）。

### 2.2 欠账清单（8 条，本迭代补齐）

| P0# | 验收点 | 现状 | 所属计划 |
|---|---|---|---|
| 13 | 富文本自动保存 + 乐观锁 409 | `Section` 无 `version` 字段，PATCH 无并发控制，前端无防抖（每次击键即发请求） | 计划 9 |
| 15 | 附图章节（上传图片+描述） | `Attachment` 实体完全未建 | 计划 10 |
| 19 | 流式中断 + SSE 心跳 + 断线保留 | `ai.py` 只有 token/done/error，无心跳无中断 | 计划 9 |
| 20 | 归档→知识库闭环 | `archive_service`+`rag/archiver` 代码齐全但**无 API 路由无前端入口** | 计划 11 |
| 6 | 异步任务恢复 | 模板解析当前**同步执行**，「卡住任务需重启续跑」场景不存在，需引入真异步 | 计划 12 |
| 26 | agent 技能自定义（启用/禁用） | `AgentSkill` 完全未实现 | 计划 12 |
| 29 | 管理员用户运营（封禁/重置密码） | 只有 `GET /admin/users`，无写操作 | 计划 13 |
| 30 | 管理员监控/审计日志 | 完全没有 | 计划 13 |

### 2.3 关键事实修正（核对代码后发现）

- **#20 归档闭环**：`services/archive_service.py:archive()` 与 `rag/archiver.py:archive_project()` 均完整（含幂等：先删旧 chunk 再重生；内置置 `project.status="archived"` + `archived_at`）。断点仅在「缺 API 路由 + 缺前端按钮 + schema 漏字段」。
- **#6 异步任务**：`templates.py:44` 注释明示「MVP 同步执行（后续可改 BackgroundTasks）」，`run_parse_job` 同步阻塞跑完。故「服务重启续跑卡住任务」场景当前不存在，需先引入真异步执行。
- **#29 封禁拦截**：`authenticate_user`（登录）与 `get_current_user`（鉴权）均已检查 `user.status != "active"`，封禁的「拦截半边」已通，缺的是「写操作」入口。

---

## 3. 计划 8（已完成，待提交）

**前端 UI 改造**（主题/布局/logo/暗黑模式/页面骨架壳）。当前工作区有约 `+1145/-388` 行未提交改动 + 新增组件（`logo.tsx`、`page-shell.tsx`、`theme-toggle.tsx`、`(auth)/layout.tsx`、`stores/ui.ts`）。已确认完成，本迭代第 0 步：提交干净。

---

## 4. 计划 9：创作主线加固

**覆盖 P0**：#13（自动保存+乐观锁）、#19（SSE 心跳+服务端异步中断+断线保留）。**另含**：编辑器视觉打磨。

### 4.1 编辑器视觉打磨（9.0）

- 问题：编辑器内容区 `max-w-3xl`（768px），宽屏下中间栏（~1280px 可用）两侧留白过多。
- 改动：`max-w-3xl` → `max-w-5xl`（1024px），内容区占中间栏 ~80%。
- 文件：`apps/web/src/app/(app)/projects/[id]/page.tsx`。

### 4.2 自动保存 + 乐观锁（9.1，设计 13.4）

**后端**

- `Section` 模型加 `version: Mapped[int] = mapped_column(Integer, default=1)`，每次 PATCH 成功 `version += 1`。
- `SectionUpdate` schema 增加可选 `expected_version: int | None`（旧客户端不传也可工作）。
- `PATCH /sections/{id}` 并发控制：客户端传 `expected_version=N`，后端 `UPDATE ... WHERE id=? AND version=?`，`rowcount==0` 即冲突 → **409 Conflict**，body 带当前 `version` 和 `updated_at`。
- `SectionOut` schema 返回 `version`。

**前端**

- `onChange` 后**防抖 2s**（设计 13.4）才发 PATCH，不再每次击键即存。
- 保存时带 `current.version` 作为 `expected_version`。
- 409 处理：toast 提示「内容已被其他端修改」→ 刷新拉最新内容让用户重新编辑。
- 章节切换时若有未保存的防抖定时器，立即 flush 保存。
- 标题栏保存指示器：「保存中…/已保存」。

### 4.3 异步 SSE + 服务端真中断（9.2，设计 13.8 / P0-19）

**核心改造：AI 编排层新增异步版本（保留同步版）**

- `llm_client.py` 新增 `astream_llm(messages) -> AsyncIterator[str]`，用 `llm.astream()`；**保留**同步 `stream_llm`（审查引擎等仍用）。
- `orchestrator.py` 新增 `astream_chat/astream_generate/astream_rewrite`，保留同步版。异步版本只给 SSE 端点用。
- 关键切分：**上下文准备（RAG 检索、summary 装配）保持同步**（生成前一次性完成），**只有 LLM 流式调用是异步**。

**SSE 三端点改异步**（`api/ai.py`：chat / generate / rewrite）

- `def generate()` → `async def generate():`，`await` 遍历 `astream_*`。
- **心跳**：空闲 ~5s yield `heartbeat` 事件，防中间代理掐断。
- **服务端真中断**：前端 AbortController 断开 → Starlette 检测客户端断开 → `async for` 下一个 chunk 时 generator 被取消 → `llm.astream` 底层 httpx 异步连接关闭 → **真正停止从 LLM API 拉取，不浪费 token**。
- **断线内容保留**：`try/finally` 在 generator 结束/取消时，把已累积的 `full_md` / `full_response` 落库。
- **幂等取舍**：仅在 `section.status == "empty"` 时落半截草稿，避免「AI 生成到一半被停，冲掉用户已有内容」。

**前端**

- `lib/api.ts`：`streamChat/streamGenerate` 用 `fetch` + `AbortController`，暴露 `signal` 参数。
- AI 面板：generating/loading 时按钮变「停止」，点击 `abortController.abort()`。
- 收到中断后：已累积文本保留显示，提示「已停止，内容已保留」。

### 4.4 文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端模型 | `models/section.py` + 迁移 | +`version` 字段 |
| 后端 schema | `schemas/section.py` | `version` / `expected_version` |
| 后端 service | `services/section_service.py` | 乐观锁 `WHERE version=?` |
| 后端 | `ai/llm_client.py` | 新增 `astream_llm` |
| 后端 | `ai/orchestrator.py` | 新增 `astream_chat/generate/rewrite` |
| 后端 | `api/ai.py` | 三端点 async + 心跳 + 断线捕获 + 断线落草稿 |
| 前端 | `projects/[id]/page.tsx` | 防抖 2s + expected_version + 409 + 保存指示器 + max-w-5xl |
| 前端 | `ai-chat-panel.tsx` | 停止按钮 + AbortController |
| 前端 | `lib/api.ts` | stream 支持 AbortSignal |
| 测试 | `tests/test_sections.py`、`test_ai.py` | 乐观锁并发、异步流式、断线保留 |

### 4.5 取舍

- 编排层同步版本保留不删——审查引擎（计划 7）已验证，隔离改动面。
- 真异步中断需改造编排层，工作量较大但用户已确认接受。
- 断线落草稿只在 section 为空时进行，避免覆盖已有内容。

---

## 5. 计划 10：附图与文件上传

**覆盖 P0**：#15（附图章节，设计 9.5 + 13.2）。

### 5.1 核心约束（设计 9.5）

LLM **仅文本能力**，不引入多模态。附图章节交互模式：
1. 用户上传图片（仅存储 + 编辑器内展示，**LLM 不读图**）。
2. 用户用一两句话文字描述每张图（如"图 1 是本发明装置的整体结构示意图"）。
3. AI 基于文字描述 + 技术方案上下文，润色生成规范图注。

### 5.2 数据模型（设计 3.2）

新增 `Attachment` 实体：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK CASCADE | |
| section_id | UUID FK CASCADE, nullable | MVP 附图章节用 section 级 |
| filename | str | 原始文件名（仅展示） |
| storage_path | str | UUID 生成的存储名 |
| mime_type | str | |
| size | int | |
| created_at / updated_at | datetime | TimestampMixin |

### 5.3 文件存储（附录 B：MVP 本地）

- config 加 `upload_dir: str = "uploads"`、`max_image_size_mb: int = 10`。
- 存储路径 `{upload_dir}/{uuid}.{ext}`，**UUID 命名**（防路径遍历）。
- `.gitignore` 加 `apps/api/uploads/`。
- 访问走鉴权路由 `GET /projects/{project_id}/attachments/{id}/file`，不静态目录直挂。

### 5.4 上传安全（设计 13.2）

- **MIME + 魔数双重校验**：PNG（`\x89PNG`）/ JPEG（`\xff\xd8`）/ GIF（`GIF8`），不轻信扩展名。
- **大小限制**：默认 10MB，超限 413。

### 5.5 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/sections/{section_id}/attachments` | multipart 上传 → 存盘 + 建记录；返回含可访问 URL |
| GET | `/projects/{project_id}/attachments` | 列出附件 |
| GET | `/projects/{project_id}/attachments/{id}/file` | 鉴权后返回图片流 |
| DELETE | `/attachments/{id}` | 删记录 + 删文件 |

所有端点走 `get_current_user` + 资源归属校验。

### 5.6 编辑器与导出集成

**后端导出**：`export_service` 的 `_render_tiptap_to_docx` / `_tiptap_to_markdown` 补 image 节点处理（image 节点带 `src`+`alt`，docx 用 `add_picture`，markdown 用 `![alt](src)`）。

**前端**：
- Tiptap 装 `@tiptap/extension-image`。
- 附图章节（`section.key == "drawings"`）编辑器加「上传图片」按钮。
- 上传成功后 `editor.chain().setImage({src, alt}).run()` 插入图片节点。
- 图片下方写文字描述（普通段落）。

### 5.7 AI 图注润色（设计 9.5 第 3 点）

- `POST /sections/{section_id}/caption-figures`（仅 `drawings` 章节）。
- 取本节图片 alt 文字描述 + 技术方案章节上下文，调 LLM 润色成规范图注（统一"图 N 是…"格式），流式返回。
- 复用计划 9 的 `astream_llm`，纯文本，非多模态。

### 5.8 文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端模型 | `models/attachment.py`（新）+ `__init__` | Attachment 实体 |
| 后端 | `core/config.py` | `upload_dir` / `max_image_size_mb` |
| 后端 | `services/attachment_service.py`（新） | 存盘 + 魔数校验 + CRUD |
| 后端 | `api/attachments.py`（新）+ `router.py` | 上传/列表/下载/删除 |
| 后端 | `api/ai.py` | `caption-figures` 流式端点 |
| 后端 | `services/export_service.py` | image 节点渲染 |
| 后端迁移 | `alembic/versions/` | `create_attachments` |
| 前端 | `package.json` | `@tiptap/extension-image` |
| 前端 | `editor/tiptap-editor.tsx` | Image 扩展 + 上传按钮 |
| 前端 | `lib/queries.ts` / `types/api.ts` | attachment hooks + 类型 |
| 测试 | `tests/test_attachments.py`（新） | 上传/权限/魔数/导出 |

### 5.9 取舍

- 不做多模态 vision（设计 9.5 明确挡在 MVP 外）。
- 本地文件存储（附录 B），`storage_path` 字段为后续对象存储预留。

---

## 6. 计划 11：归档闭环接线

**覆盖 P0**：#20（归档→知识库闭环）。**最轻的计划**——代码齐全，纯接线。

### 6.1 现状

| 组件 | 状态 |
|---|---|
| `rag/archiver.py: archive_project()` | ✅ 完整（分块→向量化→写 KnowledgeChunk→置 archived，幂等） |
| `services/archive_service.py: archive()` | ✅ 完整（权限校验 + 调 archiver） |
| API 路由 | ❌ 无端点引用 archive_service |
| 前端入口 | ❌ 无归档按钮 |
| `ProjectOut` schema | ❌ 未暴露 `status`/`archived_at` |

### 6.2 设计

**后端**

- `ProjectOut` 补 `status`、`archived_at`；`_to_out` 输出。
- `POST /projects/{id}/archive`：调 `archive_service.archive()`，返回 chunk 数。
- **前置校验**：至少一个非空 confirmed 章节，否则 400「内容不足，无法归档」（防空项目造垃圾 chunk）。
- **重复归档**：archiver 幂等，安全。

**归档后编辑冲突（设计附录 C）**：归档后用户又改内容 → 不自动检测，靠用户主动点「更新知识库」（幂等重生）。

**前端**

- 项目详情页顶栏：`status != "archived"` 显示「归档到知识库」；`== "archived"` 显示「更新知识库」。
- 归档成功 toast：「已归档，写入 N 个知识块」。
- 工作台项目卡片：已归档显示「已归档」徽标。

### 6.3 文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 | `schemas/project.py` | `ProjectOut` 补 `status`/`archived_at` |
| 后端 | `api/projects.py` | `POST /archive` + 前置校验 + `_to_out` 输出 |
| 前端 | `projects/[id]/page.tsx` | 归档/更新知识库按钮 |
| 前端 | `project-card.tsx` | 已归档徽标 |
| 前端 | `types/api.ts` | Project 补字段 |
| 测试 | `tests/test_projects.py` | 归档端点 + 幂等 + 前置校验 + 权限 |

### 6.4 取舍

- 不做自动重归档脏检测（设计附录 C 提示，MVP 退化为用户主动按钮）。
- 归档不锁项目可编辑性，`status` 只是标记。

---

## 7. 计划 12：异步解析恢复 + 技能开关

**覆盖 P0**：#6（异步任务恢复）、#26（agent 技能自定义）。

### 7.1 模板解析改真异步执行 + 恢复扫描（#6，设计 13.2①）

**异步执行改造**

- `templates.py` 的 `upload` 端点：创建 ParseJob → `BackgroundTasks` 投递 `run_parse_job` → 立即返回 202 + `parse_job_id` + `status="processing"`。
- **BackgroundTasks 的 DB session 正确性点**：响应发送后请求的 `db` session 已关闭，`run_parse_job` 需自己开新 session（`SessionLocal` 上下文管理器），不能复用请求的 `db`。
- `run_parse_job` 内部状态机（pending→processing→completed/failed）和 try/except 幂等已就位（`if job.status == "completed": return`）。

**恢复扫描（startup 钩子）**

- `main.py` 的 `on_startup` 加恢复逻辑：
  - 扫描 `status == "processing"`（异常中断）→ 重投 `run_parse_job`。
  - 扫描 `status == "pending"` 且 `created_at` 超 10 分钟（卡队列）→ 重投。
- 幂等：`run_parse_job` 开头 completed 检查兜底。

**查询解析状态端点**

- `GET /templates/parse-jobs/{job_id}`：返回 `{status, template_id?, error_message?}`。
- 前端上传后轮询，completed 后刷新模板列表。

### 7.2 AgentSkill 技能开关 —— 项目级（#26，设计 7.4）

**重要修订**：技能开关是**项目级**而非用户级。同一个用户写不同类型的专利（机械 vs 软件），需要的技能组合不同；同一用户不同专利各自独立配置。

**数据模型**（设计 3.2，`user_id` 改为 `project_id`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK CASCADE | **项目级**（修订自设计 3.2 的 user_id） |
| skill_key | str | rag_search / rubric_review / ... |
| enabled | bool | 该项目是否启用 |
| config | JSONB nullable | 技能配置（top_k 等） |

**注意**：`name`/`description`/`is_builtin` 是系统级定义，用代码常量 `BUILTIN_SKILLS`（不落库），避免每项目/用户冗余存储。

**内置技能定义**（设计 7.4）：

| skill_key | 名称 | 默认 |
|---|---|---|
| `rag_search` | 知识库检索 | 启用 |
| `rubric_review` | Rubric 审查 | 启用 |
| `consistency_check` | 自一致性校验 | 启用 |
| `quality_report` | 质量报告 | 启用 |
| `prior_art_hint` | 现有技术提示 | 启用（占位，检索在 P1） |

**默认值处理（不种库）**：查询时 `内置定义 LEFT JOIN 项目开关`，缺失行 = enabled=true。用户主动关闭某技能时才 upsert 开关行。

**编排接通点（全部已有 project 上下文，零额外取参）**

- `_retrieve_knowledge(db, section, query)` → 前查 `is_skill_enabled(project_id, "rag_search")`，禁用则跳过检索。
- `review_service` → 查 `rubric_review`/`consistency_check`/`quality_report` 开关。
- `prior_art_hint` → 占位，无运行时效果。
- MVP 只做「禁用即跳过」，不做 LangGraph 动态节点装配。

**API**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/projects/{project_id}/skills` | 内置定义 + 项目开关合并（未配置默认启用） |
| PUT | `/projects/{project_id}/skills/{skill_key}` | `{enabled, config?}` 更新 |

**前端**：技能配置从设置页移到**项目详情页**（顶栏「技能」入口 + 抽屉）。切项目即切技能集。

### 7.3 文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 | `services/parse_service.py` | `run_parse_job` 改用独立 session |
| 后端 | `api/templates.py` | upload 改 BackgroundTasks + 查询状态端点 |
| 后端 | `main.py` | startup 恢复扫描钩子 |
| 后端 | `core/database.py` | 确认/暴露 `SessionLocal` |
| 后端模型 | `models/agent_skill.py`（新）+ `__init__` | AgentSkill（project_id） |
| 后端 | `services/skill_service.py`（新） | BUILTIN_SKILLS 常量 + 项目级 CRUD + `is_skill_enabled` |
| 后端 | `ai/orchestrator.py` | `_retrieve_knowledge` 前查 rag_search 开关 |
| 后端 | `services/review_service.py` | 查 rubric_review/consistency_check 开关 |
| 后端 | `api/projects.py` | `GET/PUT /projects/{id}/skills` |
| 后端迁移 | `alembic/versions/` | `create_agent_skills` |
| 前端 | `projects/[id]/page.tsx` | 技能入口 + 配置抽屉 |
| 前端 | `template-manager.tsx` | 上传后轮询解析状态 |
| 测试 | `tests/test_parse_recovery.py`（新）、`test_skills.py`（新） | 异步+恢复幂等、技能开关+编排跳过+跨项目隔离 |

### 7.4 取舍

- 异步改造正确性：BackgroundTasks 独立 session 是核心点，TDD 先测「任务在新 session 完成」。
- 技能编排接通只做「禁用即跳过」，不做动态节点装配。
- 恢复扫描竞态靠 `run_parse_job` completed 检查兜底。

---

## 8. 计划 13：管理后台运营闭环

**覆盖 P0**：#29（用户运营）、#30（监控/审计）。**合规约束最严**（设计 8.3 红线 + 自我保护 + 脱敏）。

### 8.1 用户运营（#29，设计 8.2③）

**现状**：`GET /admin/users` 已返回聚合列表；封禁拦截半边已通（`authenticate_user:30` + `get_current_user:32` 均查 `status`）。缺写操作。

**新增端点**（全部 `require_admin`）

| 方法 | 路径 | 说明 |
|---|---|---|
| PATCH | `/admin/users/{user_id}/status` | `{status: "active"\|"disabled"}` 封禁/解禁 |
| POST | `/admin/users/{user_id}/reset-password` | `{new_password}` 重置密码 |

**封禁/解禁**：设 `user.status`，登录拦截 + 即时下线已就位，无需额外改。

**重置密码**：复用 `hash_password`，`user.password_hash = hash_password(new_password)`；不返回响应；管理员线下告知用户。

**自我保护约束**（必须有测试）：
- 管理员不能封禁/重置自己。
- `is_superuser`（命令行超管）不可被封禁。
- 不能封禁其他管理员。

### 8.2 监控运维（#30，设计 8.2④）

**设计 8.3 红线：只看元数据（耗时/token/状态），不看 LLM 调用内容。**

**LLM 调用记录模型**（新建）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | UUID nullable | BYOK 时是用户；全局时 null |
| project_id | UUID nullable | 调用来源项目 |
| action | str | chat/generate/rewrite/review/embed |
| model | str | 模型名 |
| provider | str | user/global |
| token_prompt | int nullable | |
| token_completion | int nullable | |
| duration_ms | int nullable | |
| status | str | success/failed |
| error | str nullable | 失败原因（不含内容） |
| created_at | datetime | |

**记录点**：`llm_client` 统一返回 usage（LangChain chunk 带 `usage_metadata`），日志落库职责在 `api/ai.py` 的三个流式端点（chat/generate/rewrite）的 generate() wrapper 中——这些 wrapper 持有 db session，generator 正常结束或取消时各记一条。`llm_client` 本身保持纯净，不碰 db。

**监控端点**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/stats/llm` | 按 时间/用户/模型 聚合（总调用、总 token、平均耗时、失败率） |
| GET | `/admin/stats/llm?days=7` | 近 N 天趋势 |

聚合用 SQL（SUM/COUNT/AVG），用户只显示邮箱+聚合数字，绝不返回内容。

### 8.3 审计日志（#30，设计 8.2⑤）

**设计 8.2⑤：管理员自身操作日志——防权限滥用，可追溯。**

**审计日志模型**（新建）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| actor_id | UUID | 操作者（管理员） |
| actor_email | str | 冗余存邮箱，防用户删除后查不到 |
| action | str | set_global_llm/ban_user/reset_password/... |
| target_type | str | user/system_setting/... |
| target_id | str nullable | 被操作对象 |
| detail | JSONB | 变更摘要（不含 key 明文等敏感值） |
| created_at | datetime | |

**记录点**：所有 `/admin/*` 写操作执行后记一条（service 层 helper 统一记录）。

**脱敏**：`detail` 绝不存 key 明文（全局 LLM 变更只记 model/base_url 变更）。

**审计端点**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/audit-logs` | 审计日志列表（分页，时间倒序） |

### 8.4 文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端模型 | `models/llm_call_log.py`（新）+ `models/audit_log.py`（新）+ `__init__` | 两个日志实体 |
| 后端迁移 | `alembic/versions/` | `create_llm_call_logs` + `create_audit_logs` |
| 后端 | `services/admin_service.py`（新） | 封禁/重置密码 + 审计 helper |
| 后端 | `services/stats_service.py`（新） | LLM 调用统计聚合 |
| 后端 | `api/admin.py` | 状态 PATCH、重置密码 POST、统计 GET、审计 GET |
| 后端 | `api/ai.py` | LLM 调用完成写 LLMCallLog |
| 前端 | `admin/page.tsx` | 封禁/重置密码 + 统计面板 + 审计日志页 |
| 测试 | `tests/test_admin.py`（新） | 封禁/重置/自我保护/统计聚合/审计/脱敏 |

### 8.5 取舍

- 自我保护三条约束必须有测试覆盖。
- 日志体积：MVP 不做自动清理，加 `created_at` 索引。
- 审计 detail 脱敏是合规关键，必须测「全局 LLM 变更不记 key 明文」。
- 密码重置通知：MVP 不做邮件，管理员线下告知（邮件为 P1）。

---

## 9. 全局约束（贯穿所有计划）

### 9.1 遵循 GOTCHAS

- 数据库测试用 SQLite 内存库 + `JSONB().with_variant(JSON, "sqlite")`（G2）——新增模型字段（version、Attachment、AgentSkill、日志表）凡用 JSONB 都要配 variant。
- 密码用 bcrypt 直接调用，不用 passlib（G1）。
- shadcn/ui 锁 3.x（F1）。
- 开发端口用 `localhost`，不用 127.0.0.1（F4）。

### 9.2 资源级授权（设计 13.1）

所有新端点（attachments、archive、skills、admin）必须复用现有 `get_current_user` + 资源归属校验模式，越权访问返回 404。admin 端点加 `require_admin`。

### 9.3 删除语义（设计 13.6）

新增实体的删除：Attachment 删记录同时删文件；AgentSkill 随 project CASCADE；日志表不随用户删除（审计需要留存）。

### 9.4 测试策略（设计 13.9）

- 后端：pytest + SQLite 内存库，每个计划配独立测试文件。
- 前端：交互不便单测，靠 E2E 手验 + build 通过。
- 关键覆盖：乐观锁并发、异步流式中断、断线保留、归档幂等、异步解析恢复、技能跨项目隔离、管理员自我保护、审计脱敏。

---

## 10. 实施顺序与依赖

```
计划 8（已完成）→ 提交
    ↓
计划 9（创作主线加固：9.0/9.1/9.2）
    ↓ astream_llm 供后续复用
计划 10（附图：含 caption-figures 复用 astream_llm）
    ↓ 内容完整（含附图）后归档才有意义
计划 11（归档闭环：纯接线）
    ↓
计划 12（异步解析 + 技能开关）
    ↓
计划 13（管理运营：监控/审计）
```

每个计划独立可验证、可提交。计划 10 依赖计划 9 的 `astream_llm`（图注润色端点）；计划 11 排在 10 之后因归档需要内容完整。

---

## 11. 非目标（本迭代明确不做）

- P1 功能：PDF 导出、专利检索、全篇质量报告、灵感补全（Tab）、agent 长期偏好记忆（设计 11.2）。
- 多模态 vision（设计 9.5 明确挡在 MVP 外）。
- 对象存储（附录 B，MVP 本地）。
- 邮件通知（密码重置通知为 P1）。
- LangGraph 动态节点装配（技能编排只做「禁用即跳过」）。
- 自动重归档脏检测（设计附录 C，MVP 退化为手动按钮）。
- 日志自动清理（设计 8.2④ 数据备份为 P1）。
