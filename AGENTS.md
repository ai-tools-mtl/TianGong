# 天工 TianGong — 项目指引

> 本文件给 AI agent 和人类开发者提供项目上下文。**新会话开工前必读。**

## 项目简介

天工是 AI 驱动的专利交底书撰写智能体——从灵感到授权全生命周期的 Agent 系统。
- **当前阶段**：MVP 全部 P0 已完成（计划 1–7b：后端地基→前端地基→模板编辑器→AI 撰写→版本导出→知识库 RAG→审查引擎→管理后台自定义配置）
- **技术栈**：FastAPI(Python) 后端 + Next.js 前端 + PostgreSQL(pgvector) + LangChain（编排 + Embedding）。注：原设计曾规划 LangGraph + LlamaIndex，落地中调整为纯 LangChain（见 GOTCHAS E3）

## 必读文档（按顺序）

1. **[设计文档](docs/superpowers/specs/2026-07-13-tiangong-mvp-design.md)** — 完整设计（v1.5，13 章），所有架构决策的依据
2. **[踩坑记录](docs/GOTCHAS.md)** ⚠️ — 实际开发踩到的坑（环境兼容/类型/校验等），**开工前必读，避免重复踩**
3. **实施计划** — `docs/superpowers/plans/` 下按子系统拆分的 TDD 计划
4. **UI 设计契约** — `docs/superpowers/specs/` 下还有 UI 重构等独立设计契约（如 [2026-07-14-ui-redesign-contract.md](docs/superpowers/specs/2026-07-14-ui-redesign-contract.md)），前端改动前先读对应契约

## 代码结构

```
apps/
├── api/    # FastAPI 后端（Python + uv）
│   ├── app/{api,core,models,schemas,services}/
│   ├── tests/    # pytest（36 个测试）
│   └── scripts/  # create_admin 等命令行工具
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
- **「BYOK」术语已更名为「自定义配置」**：本项目原称的 BYOK 实指「用户密钥加密托管」（L1 成本隔离型——每用户用自己的 key 调用，运营方不为用户 token 买单），非严格意义的 BYOK（密钥主权型，服务端零明文）。代码层面 source 协议前缀为 `custom:{config_id}`，用户可见文案统一称「自定义配置」。此为有意决策，非缺陷。
