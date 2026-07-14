# 天工 TianGong

> AI 驱动的专利交底书撰写智能体 —— 从技术交底到专利申请文件，巧夺天工。

天工陪伴一件专利从灵感到授权的全生命周期：用 AI 引导撰写技术交底书、用确定性评估管线稳定地审查评分、连接事务所协作、辅助审查答复，并将每一件专利沉淀为可检索、可复用的知识库。

## 核心能力

- **交底书撰写**：从模糊灵感到结构完整的交底书，AI 逐章节引导 + 富文本编辑 + 模板套用
- **稳定审查评分**：Rubric 驱动的确定性评估管线，根治通用 Agent「跨对话评分漂移」问题
- **知识库 RAG**：交底书归档即沉淀，撰写新交底书时自动检索相似历史案例
- **全生命周期**：交底书 → 事务所协作 → 审查答复 → 归档，架构为全流程预留
- **可自定义**：审查标准、知识库内容、Agent 技能、LLM Key 均可按用户配置

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLAlchemy 2.0 · Alembic · uv |
| 前端 | Next.js · TypeScript · shadcn/ui · Tailwind CSS · pnpm |
| 数据库 | PostgreSQL 16 + pgvector |
| AI 编排 | LangChain（编排 + 流式 SSE，详见设计文档 5 章）|
| RAG 检索 | LangChain Embedding + pgvector |
| LLM | GLM-5.2（OpenAI 兼容，可切换）|

> 注：原设计曾规划 LangGraph + LlamaIndex，实际落地为纯 LangChain（原因见 GOTCHAS E3：LlamaIndex 不支持国产 embedding 模型名）。

## 项目结构

```
TianGong/
├── apps/
│   ├── api/                    # FastAPI 后端
│   │   ├── app/
│   │   │   ├── api/            # 路由（auth/projects/health）
│   │   │   ├── core/           # 配置/安全/数据库/异常
│   │   │   ├── models/         # ORM 模型（User/Project/SystemSetting）
│   │   │   ├── schemas/        # Pydantic 模型
│   │   │   ├── services/       # 业务逻辑
│   │   │   └── main.py         # 应用入口
│   │   ├── alembic/            # 数据库迁移
│   │   ├── scripts/            # 命令行工具（create_admin 等）
│   │   └── tests/              # pytest 测试
│   └── web/                    # Next.js 前端
│       └── src/
│           ├── app/            # App Router 页面
│           ├── components/     # 组件（含 shadcn/ui）
│           ├── lib/            # API client / Query hooks
│           ├── stores/         # Zustand 状态
│           └── types/          # 类型定义
├── docs/
│   ├── superpowers/
│   │   ├── specs/              # 设计文档
│   │   └── plans/              # 实施计划
│   └── GOTCHAS.md              # 踩坑记录 ⚠️
├── docker-compose.yml          # PostgreSQL + pgvector
├── AGENTS.md                   # 项目指引（新会话必读）
└── README.md                   # 本文件
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+ / pnpm
- Docker（用于 PostgreSQL）

### 1. 启动数据库

```bash
docker compose up -d postgres
```

### 2. 启动后端

```bash
cd apps/api
cp .env.example .env          # 编辑配置（数据库/JWT/加密密钥）
uv sync --extra dev            # 安装依赖
uv run alembic upgrade head    # 执行数据库迁移
uv run python -m scripts.create_admin --email admin@tiangong.dev --password 你的密码  # 创建管理员
uv run uvicorn app.main:app --reload    # 启动开发服务器（http://localhost:8000）
```

### 3. 启动前端

```bash
cd apps/web
pnpm install
pnpm dev                       # 启动开发服务器（http://localhost:3000）
```

### 4. 访问应用

浏览器打开 `http://localhost:3000`，用上一步创建的管理员账号登录。

## 常用命令

```bash
# 后端测试
cd apps/api && uv run pytest

# 前端构建
cd apps/web && pnpm build

# 数据库迁移（修改模型后）
cd apps/api && uv run alembic revision --autogenerate -m "描述变更"
cd apps/api && uv run alembic upgrade head
```

## 开发进度

| 计划 | 状态 | 说明 |
|---|---|---|
| 1 后端地基 | ✅ 完成 | FastAPI + 数据模型 + 认证 + 项目 CRUD + 资源级权限 |
| 2 前端地基 | ✅ 完成 | Next.js + 登录注册 + 工作台 + 项目管理 |
| 3 模板与编辑器 | ✅ 完成 | Word 解析（三层编号策略）+ Tiptap 富文本 + 样式继承解析 |
| 4 AI 撰写引擎 | ✅ 完成 | LLM Client + Prompt 注册表 + 五层上下文装配 + 流式 SSE + 跨章节 summary |
| 5 版本/预览/导出 | ✅ 完成 | 章节版本快照 + 全篇预览 + Word/Markdown 导出渲染器 |
| 6 知识库 RAG | ✅ 完成 | LangChain Embedding + pgvector + 分块归档 + 检索注入（注：弃用 LlamaIndex，见 GOTCHAS E3）|
| 7 审查引擎+Rubric | ✅ 完成 | 确定性评估管线 + Rubric 覆盖式配置 + 自一致性 + 跨对话稳定验证 |
| 7b 管理后台+BYOK | ✅ 完成 | 管理员 API + 三级 Provider 解析 + 全局开关 + 用户自配 Key + 前端管理/设置页 |

> **MVP 全部 P0 功能已落地并端到端验证。** 下一步见设计文档 11.2（P1 迭代：专利检索 / PDF 导出 / 全篇质量报告 / 灵感补全 / agent 记忆）。

## 文档

- [设计文档](docs/superpowers/specs/2026-07-13-tiangong-mvp-design.md) —— 完整架构设计（13 章）
- [踩坑记录](docs/GOTCHAS.md) —— ⚠️ 开发前必读
- [项目指引](AGENTS.md) —— 新会话/新开发者上手指南
- [实施计划](docs/superpowers/plans/) —— 按子系统拆分的 TDD 计划

## License

私有项目。
