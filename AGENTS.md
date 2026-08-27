# 天工 TianGong — 项目指引

> 本文件给 AI agent 和人类开发者提供项目上下文。**新会话开工前必读。**

## 项目简介

天工是 AI 驱动的专利交底书撰写智能体——从灵感到授权全生命周期的 Agent 系统。
- **当前阶段**：MVP 全部 P0 已完成（计划 1–7b：后端地基→前端地基→模板编辑器→AI 撰写→版本导出→知识库 RAG→审查引擎→管理后台自定义配置）；MVP 后迭代批次（P1 增强、LangGraph 三件套、§8.3 经授权临时查看、AI 新颖性评估、修订管线 T2、连续文档视图等）均已落地，进度总表见 README「开发进度」
- **技术栈**：FastAPI(Python) 后端 + Next.js 前端 + PostgreSQL(pgvector) + LangChain（编排 + Embedding）。注：原设计曾规划 LangGraph + LlamaIndex，落地中调整为纯 LangChain（见 GOTCHAS E3）

## 必读文档（按顺序）

1. **[设计文档](docs/superpowers/specs/2026-07-13-tiangong-mvp-design.md)** — 完整设计（v1.5，13 章），所有架构决策的依据
2. **[踩坑记录](docs/GOTCHAS.md)** ⚠️ — 实际开发踩到的坑（环境兼容/类型/校验等），**开工前必读，避免重复踩**
3. **实施计划（已归档）** — `docs/superpowers/plans/archive/` 下按子系统拆分的 TDD 计划（MVP P0 + P1 扩展均已完成，保留作新功能 TDD 结构参考）
4. **UI 设计契约** — `docs/superpowers/specs/` 下还有 UI 重构等独立设计契约（如 [2026-07-14-ui-redesign-contract.md](docs/superpowers/specs/2026-07-14-ui-redesign-contract.md)），前端改动前先读对应契约
5. **[LLM 调用与模型选型清单](docs/llm-usage.md)** — 所有 LLM 调用点（chat 强模型 / 轻量模型）、触发场景、降级策略。调用点**存在性清单**由脚本生成：改完代码后跑 `cd apps/api && uv run python -m scripts.gen_llm_usage`，CI 以 `--check` 校验新鲜度（漏跑直接红灯）；叙述性章节（场景/降级）仍人工维护。配套的 [SystemSetting 键目录](docs/system-settings-catalog.md)同机制生成

## 代码结构

```
apps/
├── api/    # FastAPI 后端（Python + uv）
│   ├── app/{ai,api,core,eval,models,parsing,rag,sandbox,schemas,services,skills}/
│   ├── tests/    # pytest（1315 个测试）
│   └── scripts/  # create_admin 等命令行工具
├── nli/    # NLI 记忆矛盾判断微服务（端口 7999，软依赖 fail-open）
├── drawio-render/  # drawio 附图渲染微服务（端口 8001，软依赖 fail-closed）
└── web/    # Next.js 前端（pnpm + shadcn/ui 3.x）
    └── src/{app,components,lib,stores,types}/
```

## 常用命令

```bash
# 数据库
docker compose up -d postgres

# 后端
cd apps/api && uv sync --extra dev    # 装依赖
cd apps/api && uv run alembic upgrade head  # 迁移
cd apps/api && uv run pytest          # 测试
cd apps/api && uv run uvicorn app.main:app --reload  # 启动

# 数据库初始化（建表 + 可选建 admin，幂等，见 GOTCHAS G5）
cd apps/api && uv run python -m scripts.init_db
cd apps/api && uv run python -m scripts.init_db --admin-username admin --admin-password '***' --admin-email admin@tiangong.dev

# 前端
cd apps/web && pnpm install
cd apps/web && pnpm dev
cd apps/web && pnpm build

# 管理员（P2 后 username 必填，登录用 username 不是 email）
cd apps/api && uv run python -m scripts.create_admin --username admin --password '***' --email admin@tiangong.dev
```

## 关键约定

- **测试账号**：邮箱用合法域名（`@tiangong.dev` / `@test.com`），**别用 `.local`**（见 GOTCHAS G4）
- **数据库测试**：用 SQLite 内存库 + `JSONB().with_variant(JSON, "sqlite")`（见 GOTCHAS G2）
- **数据库初始化**：用 `scripts/init_db.py`（幂等），别手动一条条敲；pgvector 扩展已在迁移内 `CREATE EXTENSION`（见 GOTCHAS G5）
- **密码**：用 bcrypt 库直接调用，不用 passlib（见 GOTCHAS G1）
- **shadcn/ui**：锁 3.x，不用 4.x（见 GOTCHAS F1）；CLI 与 MCP SDK 冲突装不了组件，要新组件**手写**（见 GOTCHAS F8）
- **开发端口**：后端 8000、前端 3000，都用 `localhost`（不用 127.0.0.1，见 GOTCHAS F4）
- **LLM provider 模板**：新增/调整 LLM 供应商预设（智谱/OpenAI/DeepSeek 等，含 base_url、默认模型、拉模型端点）改 `apps/api/app/services/llm_provider_templates.py` 的 `PROVIDER_TEMPLATES`（静态数据，前端 `/settings` 与 `/admin/console/llm` 共用）。`models_endpoint` 字段是相对路径（OpenAI 兼容 `/models`，Ollama `/api/tags`），由 `llm_config_service.list_provider_models` 拼到 `base_url` 后。
- **chat 与 embedding 凭据完全独立**：chat 和 embedding 是两套独立的凭据链路（独立表 `user_llm_configs` / `user_embedding_configs`、独立 dataclass `ResolvedChatConfig` / `ResolvedEmbeddingConfig`、独立 resolve 函数 `resolve_chat_config` / `resolve_embedding_config`），支持跨供应商混搭（如智谱 chat + OpenAI embedding）。source 协议拆双值：前端发 `chat_source`（chat 端点）或走 embedding 的内部 fallback；取值空间 `global` / `custom-chat:{id}` / `custom-emb:{id}` / `env`。两条 fallback **不互通**（embedding 没配就报错，不隐式回退 chat 凭据）。admin grant 仍按用户单一授权（一个 grant 同时覆盖全局 chat + 全局 embedding）。全局 chat 配置存 SystemSetting key `llm_global_chat_config`（共用 `llm_global_enabled` 开关）；embedding 已无全局可配（统一固定 bge-m3 微服务、env 提供连接信息，历史上的 `llm_global_embedding_config` 双 key 设计未落地已废弃，键目录见 docs/system-settings-catalog.md）。
- **「BYOK」术语已更名为「自定义配置」**：本项目原称的 BYOK 实指「用户密钥加密托管」（L1 成本隔离型——每用户用自己的 key 调用，运营方不为用户 token 买单），非严格意义的 BYOK（密钥主权型，服务端零明文）。用户可见文案统一称「自定义配置」。此为有意决策，非缺陷。
- **记忆热度全自动（v1.1）**：`user_memories` 表的 `hit_count`/`last_hit_at` 由系统自动维护——检索命中自动累加、超 200 条自动淘汰（30 天半衰期热度排序）。无用户反馈机制，不暴露热度/复核端点。
- **NLI 矛盾覆盖全自动（v1.1，已启用）**：新旧记忆语义相似但内容冲突时，自动用新覆盖旧（用户认知更新纠错）。由自建 NLI 微服务（`apps/nli/`，端口 7999，sentence-transformers CrossEncoder 跑 `cross-encoder/nli-deberta-v3-base`）提供 `/nli` 端点做句子对推理，每次 0 token。NLI 是软依赖——故障时 `judge_relation` 降级 neutral 走合并不删，绝不误删。注：原用 Infinity `/classify`，因不支持句子对已弃用，改自建微服务。
- **专利附图 AI 生成（drawio 渲染）**：「附图说明」章节支持 AI 生成附图——后端调 chat 强模型生成 drawio XML，再调自建 drawio 渲染微服务（`apps/drawio-render/`，端口 8001，draw.io desktop headless CLI + xvfb + Chromium）导出 PNG，落库为 `Figure`（含可编辑 XML 源 + style）+ `Attachment`（PNG）。drawio 渲染是软依赖但 **fail-closed**（与 NLI 的 fail-open 相反）——服务故障时 figure 生成整体报 503，不降级、不留半成品，故 api 不 depends_on drawio。两条触发路径：(1) 用户在 drawings 章节点「生成附图」按钮（`FigureGenerate` 组件，走 `figures` API）；(2) 章节 agent 在对话中自主调用 `generate_figure` 工具（用户说「画一下系统框图」时 agent 直接产出图，归到 drawings 章节）。agent 工具仅 section 场景可见（init 阶段项目未成型不装配），复用同一 `figure_service`。**风格预设**（`app/ai/figure_presets.py`）：3 个内置预设——patent-bw（专利黑白，默认，符合《专利审查指南》正式申请标准：纯黑白线条/白底/统一线宽1.5px/宋体/数字标号）、clean-color（清晰彩色）、technical（技术灰度）。渲染规格三预设统一高规格：scale=3（≈300DPI）+ border=20px 白边距。admin 可在 console 微调预设的字体/字号/线宽（`figure_style_presets` SystemSetting，深合并覆盖内置，不能增删预设）。镜像较重（Chromium ~500MB+），memory 限制 2g。LLM 调用走 `resolve_chat_config`（非轻量），见 `docs/llm-usage.md` 第五节。
- **LangGraph 三件套（resume / HITL / Store）**：(1) **Resume 断点续跑**——崩溃/断连/HITL 中断的 turn 经 `POST /sections/{sid}/messages/{mid}/resume` 续跑；thread 约定：`thread_id` = 该 turn user 消息 id；崩溃续跑 input=None，HITL 恢复 `Command(resume={"decisions":[{type,message}]})`；完成时以 checkpoint 权威重建全文（`collect_final_answer`——被中断节点整段重放，DB 半截+续跑流直拼会有重复前缀），done 事件带权威 content。generate 端点**有意不传** thread_id（复用聊天锚点会污染同 thread 续跑的全文重建）。(2) **HITL 工具确认**——`SystemSetting agent_hitl_config {enabled, tools}`（admin console「工具确认」页），默认拦 `generate_figure`（approve/reject 两决策，前端聊天面板确认卡片）；checkpointer 为 None（fail-open）时自动放行全部工具（断点无处持久化，宁可不拦）。(3) **Store 统一记忆**——`app/ai/store.py` CompositeAgentStore 按 namespace 路由：`("memories", user_id)` → user_memories 表（经 memory_service，单一真源，fail-open），其余（skills 等）→ MinIOSkillStore 透传（异常如实上抛）；配套热门记忆常驻注入（`context_assembler` 双路：按 query 检索 + 热度 top-15 补位，exclude 去重）。
- **经授权临时查看（§8.3 完整版）**：用户在 ShareDialog「技术支持」tab 生成 8 位一次性授权码（`support_access_codes` 表，默认 30 分钟须核销）→ admin 在 console「支持查看」页凭码核销（一次性，开 30 分钟只读查看窗口，仅核销 admin 可看）→ 每次访问写审计 `support_view_project`（detail 不含码明文）。与游客浏览（ShareLink 公开 token、无审计）正交。防探测：所有失败统一 404。
- **vision 探测名单 admin 可配**：`SystemSetting vision_model_markers {enabled, extra_markers}`（console「Vision 模型名单」页），extra 与内置保守名单合并（小写子串匹配）；enabled=False 全局禁用 vision（图注走文字降级）。无配置时行为与内置名单完全一致。
- **AI 新颖性评估**：专利检索页「AI 新颖性评估」——对比文件（含 `legal_status` 字段）× 交底书核心章节（problem/solution/effect/background/summary，单章 1500 字/总 6000 字截断）→ chat 强模型流式 Markdown 报告（总体风险/逐篇对比/差异化建议/法律状态提示），持久化 `prior_art_refs.assessment`（新检索整体重置）。AI 辅助参考定位，不构成法律意见（前端明示）。
- **修订管线（评估建议→AI 修订，T2）**：审查报告/术语检查/新颖性评估三类建议统一走「前端组装 directives（确认卡片勾选）→ `POST /sections/{sid}/revise`（SSE）→ `/diff` + `apply-diff` 人工审核」管线。revise 走 agent loop 但 **checkpointer 显式 None（HITL 随之禁用，工具直通——langgraph 入口级要求有 checkpointer 必须有 thread_id，见 GOTCHAS E7）**、不带聊天历史、不落库不建 Message（候选稿必经人工 diff，无自动应用路径）。指令含「最小改动/逐字保留/术语表优先」约束（优先级：术语表 > 沿用现状 > 最小改动，D13）；现文用 `_tiptap_to_markdown`（与 /diff 同款转换器）嵌入减少伪 hunk。跨页传递用 `revision-store`（Zustand 单值覆盖）+ 编辑器 `?section=` 深链（读后清参）。项目术语表（`project_terms`）注入 context_assembler「已写章节后、RAG 前」，仅 enabled、上限 100 条。
- **工作区单章/全文双模式（连续文档视图）**：中栏顶栏可切 `editorMode`（ui store 持久化，`single` 单章 / `continuous` 全文）。连续模式 = 各章纵向堆叠（`SectionBlock`：章头+状态徽标+图章章块槽），**激活章唯一可编辑**（其余只读 TiptapEditor，`key` 含 `edit/read` 变体强制重挂载）。激活章切换：点击（大纲/章头）立即 + 滚动停稳 500ms 自动跟随（IntersectionObserver 顶部 40% 带），受**两把锁**冻结——编辑锁（激活章在视口内且未 flush/焦点在编辑器）、AI 忙碌锁（`AIChatPanelRef.getPhase()` 非 idle，含 done/diff-review 防丢待审草稿）；显式点击不受锁约束。保存状态机仍是单例（唯一可编辑实例），配套 **per-section 编辑器引用表 `editorRefs`**（多实例同挂，单例 ref 会串章）与**每章内容缓存 `contentCacheRef`**（快速回切时 refetch 未落地，挂载一律读缓存防内容回退）。滚动定位经 `pendingScrollRef` 标记 + currentId 变化 effect 统一执行（挂载后）。设计契约见 `docs/superpowers/specs/2026-08-18-continuous-document-view-design.md`。
