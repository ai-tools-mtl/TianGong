# Admin MCP 配置页 — 设计文档

> **日期**：2026-07-30
> **主题**：在 admin 控制台新增「MCP（Model Context Protocol）配置页」，支持 stdio / HTTP / SSE 三种传输，全局作用域，全套 CRUD + 测试连接 + AI 接入。
> **状态**：设计中

## 1. 背景与目标

天工的专利撰写 agent 基于 `deepagents`（LangGraph）+ LangChain，已有 `bind_tools()` 工具循环（`apps/api/app/ai/tools.py` 当前提供 `rag_search` / `save_memory`）。MCP 是让 agent 复用外部工具生态（搜索、文件系统、数据库等）的标准协议。

**MCP 在本仓库目前是全新概念**——无任何现有 model / route / component / 设计文档。本设计从零搭建一套 admin 管理能力：让管理员配置一组 MCP server（含凭据），在 agent 生成时自动把这些 server 暴露的工具加载进 agent 的工具列表，并提供「测试连接」验证配置正确性。

### 范围（已确认）

| 维度 | 决策 |
|---|---|
| 功能层级 | **全套**：配置页 + 落库 + AI 接入 + 测试连接 |
| 传输方式 | **stdio + HTTP + SSE**（三种） |
| 作用域 | **仅全局**：admin 配置，所有用户的 agent 共享 |
| 凭据粒度 | **细粒度**：每个 server 多个具名 headers / 多个 env 变量 |
| 落地方案 | **方案 A**：独立 `mcp_servers` 表 + `SystemSetting` 全局开关 |

### 非目标（YAGNI）

- 不做用户级 MCP 配置（非 BYOK，无双表双权限拆分）。
- 不做 MCP server 的工具级白名单/黑名单过滤（整个 server 启用即全部工具可用）。
- 不做工具调用计量计费。

## 2. 数据模型与存储

### 2.1 新表 `mcp_servers`

仿 `apps/api/app/models/skill.py`（UUID PK + timestamps），在 `apps/api/app/models/mcp_server.py` 新建：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | `IdMixin` |
| `name` | String(100), unique, indexed | 唯一标识，如 `web-search`；同时作为 `MultiServerMCPClient` 的连接 key |
| `transport` | String(20) | `stdio` / `http` / `sse` |
| `command` | String(255), nullable | stdio 专用，如 `npx` |
| `args` | JSON (`JSONType`), nullable | stdio 专用，如 `["-y","@modelcontextprotocol/server-filesystem","."]` |
| `url` | String(500), nullable | http/sse 专用，如 `https://.../sse` |
| `headers_encrypted` | JSON (`JSONType`), nullable | 加密后的 header 键值对（**逐值** `encrypt_value`） |
| `env_encrypted` | JSON (`JSONType`), nullable | 加密后的 env 键值对（**逐值** `encrypt_value`） |
| `enabled` | Boolean, default true | per-row 启停 |
| `created_at` / `updated_at` | timestamps | `TimestampMixin` |
| `updated_by` | FK→users, ondelete=SET NULL, nullable | 审计追溯 |

> `JSONType` = `JSONB().with_variant(JSON, "sqlite")`（见 GOTCHAS G2），保证 sqlite 测试库可用。

**凭据加密约定**（逐值加密）：
- 写：前端发 plaintext 的 `headers: {Authorization: "Bearer xxx"}` / `env: {API_KEY: "yyy"}`；后端对 dict 的**每个 value** 调 `app.core.security.encrypt_value` 后整体存入 `headers_encrypted` / `env_encrypted`。
- 读（API 响应）：返回 `headers: {Authorization: {has_value: true}}`——**只回 key 名 + `has_value` 布尔，绝不回明文**（仿 `llm_global_chat_config` 的 `api_key_masked` 思路）。
- 更新：某字段传空 / 缺省 → 保留原值（沿用 LLM config 的「blank = don't change」约定）。

### 2.2 全局开关

`SystemSetting` 表新增一个 key：`mcp_global_enabled`，值为 `{"enabled": bool}`。总开关关闭时，agent **不加载任何** MCP 工具（即便某 server `enabled=true`）。

### 2.3 迁移

`apps/api/alembic revision --autogenerate -m "create mcp_servers"`，`down_revision = '4c736cec13b7'`（当前 head，`pg_trgm_for_keyword_retrieval`）。JSON 列用 `postgresql.JSONB(...).with_variant(sa.JSON(), 'sqlite')`。

> 新模型必须在 `apps/api/app/models/__init__.py` 导入并加入 `__all__`，否则 autogenerate 看不到。

## 3. 后端 API（admin CRUD + 测试连接）

新建 `apps/api/app/api/admin/mcp.py`，每个 handler 挂 `Depends(require_admin)`，仿 `skills.py`（CRUD）+ `console.py`（测试连接）风格：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/admin/mcp/servers` | 列出所有 server（凭据 masking，不回明文） |
| POST | `/admin/mcp/servers` | 新建（plaintext headers/env → 逐值加密落库） |
| GET | `/admin/mcp/servers/{id}` | 单个详情 |
| PUT | `/admin/mcp/servers/{id}` | 更新（空字段=保留原值） |
| DELETE | `/admin/mcp/servers/{id}` | 删除 |
| GET | `/admin/mcp/enabled` | 读全局开关 |
| PUT | `/admin/mcp/enabled` | 写全局开关 |
| POST | `/admin/mcp/servers/{id}/test` | **测试连接**：起临时 `MultiServerMCPClient`，`await get_tools()`，返回结果（带 10s 超时，不落库） |

在 `apps/api/app/api/admin/__init__.py` include `mcp.router`。

### 3.1 Schemas（`apps/api/app/schemas/mcp.py`，仿 `skill.py`）

- `McpServerBase`: `name: str`, `transport: Literal["stdio","http","sse"]`, `command: str | None`, `args: list[str] | None`, `url: str | None`, `headers: dict[str,str] | None`, `env: dict[str,str] | None`, `enabled: bool`
- `McpServerCreate(McpServerBase)`
- `McpServerUpdate`：全 `Optional`，partial 更新
- `McpServerOut`：含 `id/created_at/updated_at`（str 化）；`headers` / `env` 返回 `dict[str, {has_value: bool}]` 形态（masking）。`model_config = {"from_attributes": True}`
- `McpGlobalEnabled`: `enabled: bool`
- `McpTestResult`: `ok: bool`, `tool_count: int`, `tool_names: list[str]`, `error: str | None`

### 3.2 Service（`apps/api/app/services/mcp_config_service.py`，仿 `firecrawl_client.py` / `mineru_client.py`）

- `list_mcp_servers(db)` / `get_mcp_server(db, id)` / `create_mcp_server(db, *, payload, actor)` / `update_mcp_server(...)` / `delete_mcp_server(...)`：service 拥有事务，失败 `db.rollback()`
- `get_mcp_enabled(db) -> bool` / `set_mcp_enabled(db, *, enabled, actor)`：读写 `SystemSetting` key `mcp_global_enabled`
- `resolve_mcp_servers(db) -> list[dict]`：**内部函数**，只取 `enabled=True` 的 server，把 `headers_encrypted` / `env_encrypted` **解密**成明文 dict 返回，供 agent 加载与测试连接使用。**绝不进 API 响应**。

> **transport 切换时的字段处理**：`resolve_mcp_servers` 构建 connection 时**只读 transport 及其对应字段**（stdio 读 `command`+`args`+`env`；http/sse 读 `url`+`headers`）。若更新时 transport 从 stdio 改成 http，旧的 `command`/`args`/`env` 会留在库里但被忽略（非正确性 bug）。`update` 服务在 transport 变化时应主动清空旧 transport 专属字段，避免脏数据残留。

写操作调用 `admin_service._audit(...)`，`detail` 里**只放 name / transport / enabled，绝不放 headers / env 明文**。

## 4. AI 接入（agent 加载 MCP 工具）

### 4.1 集成点

`apps/api/app/ai/tools.py` 的 `create_agent_tools(db, user_id)`——当前返回 `[rag_search, save_memory]`，MCP 工具 append 到此列表。

### 4.2 加载逻辑

新增 `load_mcp_tools(db) -> list[BaseTool]`（**异步**）：

```python
async def load_mcp_tools(db: Session) -> list[BaseTool]:
    if not mcp_config_service.get_mcp_enabled(db):
        return []
    servers = mcp_config_service.resolve_mcp_servers(db)  # 仅 enabled 的，凭据已解密
    if not servers:
        return []
    tools: list[BaseTool] = []
    for s in servers:
        try:
            conn = _to_connection(s)  # stdio→{command,args,env} ; http/sse→{url,headers}
            client = MultiServerMCPClient({s["name"]: conn}, tool_name_prefix=True)
            tools.extend(await client.get_tools())
        except Exception as e:
            logger.warning("MCP server %s 加载失败，跳过: %s", s["name"], e)
            continue   # 单 server 失败不阻塞
    return tools
```

**逐 server try/except**：单个 server 连不上时记日志、跳过，其余 server 正常加载（避免一个挂掉的远程 server 让整个专利生成瘫痪）。`tool_name_prefix=True` 避免多 server 工具重名冲突。

### 4.3 异步化改造（关键约束）

`MultiServerMCPClient.get_tools()` 是 `async`，而现有 `create_agent_tools` / `build_agent` 链路是同步的。采用**方式 1：调用方改异步**：

- `create_agent_tools(db, user_id)` → `async def create_agent_tools(...)`
- `build_agent(...)`（`apps/api/app/ai/agent.py`）→ `async def build_agent(...)`
- `build_agent` 的调用处（orchestrator / 路由）本来就跑在 async 路由里，加 `await build_agent(...)`

最干净，符合 LangChain/MCP 原生 async 语义。`check_tool_support` 已有（gate function-calling），MCP 工具继承此守卫。

> **GOTCHAS 提醒**：`agent.py` 注释明确「不要 pre-`bind_tools`」——deepagents 内部自己 `model.bind_tools(tools)`。MCP 工具是普通 `BaseTool`，直接 append 进 list 即可，保持此约定。

## 5. 前端页面

### 5.1 新页面

`apps/web/src/app/(app)/admin/console/mcp/page.tsx`，仿 LLM / MinerU 配置页风格。

**页面结构**（两个区块）：

1. **全局开关区块**（顶部卡片）：`Switch` 绑 `mcp_global_enabled`，附说明「关闭后，所有 MCP server 的工具都不会被 AI 加载」。保存即写 `/admin/mcp/enabled`。

2. **MCP Server 列表区块**（主体卡片）：
   - table：`名称 | 传输方式 | 目标(command/url) | 启用状态 | 操作`
   - 右上角「+ 添加 Server」→ 弹 `Dialog` 表单
   - 每行操作：**测试**（调 `/test`，loading → toast 显示 `{ok, tool_count, tool_names}` 或错误）/ **编辑**（弹同一 Dialog，预填，凭据字段显示「已设置，留空则不变」）/ **删除**（确认后 DELETE）
   - 启用状态列用 inline `Switch` 直接切 per-row `enabled`（单点即存）

### 5.2 添加/编辑表单（Dialog 内）

- `name`（Input，必填，唯一）
- `transport`（Select：stdio / http / sse）
- **stdio 时显示**：`command`（Input，如 `npx`）+ `args`（Textarea，每行一个参数）+ `env` 键值对（动态增删行，key Input + value password Input）
- **http/sse 时显示**：`url`（Input）+ `headers` 键值对（动态增删行，key Input + value password Input）
- 根据 `transport` 动态切换显示字段（条件渲染）

### 5.3 导航接入

- `apps/web/src/app/(app)/admin/console/page.tsx` 的 `CONSOLE_SECTIONS` 加一张 MCP 卡片（仿 LLM/MinerU，`lucide-react` 选一个图标如 `Wrench` / `Plug`）
- **不额外加 navbar 入口**（仿 LLM/MinerU/Firecrawl，只在 console 网格里）

### 5.4 前端 wiring（仿 MinerU / Rerank）

- `apps/web/src/lib/api.ts` 加 `mcp` 方法组
- `apps/web/src/lib/queries.ts` 加 `queryKeys.admin.mcpConfig` + hooks：`useMcpServers` / `useMcpGlobalEnabled` / `useSaveMcpServer` / `useDeleteMcpServer` / `useTestMcpServer` / `useToggleMcpServer` / `useToggleMcpGlobal`
- `apps/web/src/types/api.ts` 加 `McpServer` / `McpTestResult` 类型

### 5.5 样式约定

复用 `PageShell` / `PageHeader`、Apple-glass 卡片（`var(--shadow-card)`、`apple-lift`、rounded-2xl、border `border-black/[0.07] dark:border-white/10`）；Toast 用 `sonner`。新 shadcn 组件**手写**（CLI 坏，见 GOTCHAS F8）。

## 6. 依赖、测试、审计、安全

### 6.1 新增依赖

- 后端：`langchain-mcp-adapters`（加 `apps/api/pyproject.toml`，`uv sync`）。stdio 依赖 `mcp` 包（adapter 带入）；HTTP/SSE 依赖 `httpx`（项目已有）。

### 6.2 后端测试（`apps/api/tests/test_admin_mcp_api.py`，仿 `test_admin_skills_api.py`）

- 用 `_login` / `_make_admin` / `db_session` fixtures
- 覆盖：CRUD 全流程、权限（非 admin → 403）、全局开关读写、凭据 masking（写后 GET 不回明文、只回 has_value）、更新时空字段保留原值
- **测试连接**：`monkeypatch` 替换 `MultiServerMCPClient`，断言 `/test` 返回 `{ok, tool_count, tool_names}`；注入失败分支断言 `error` 字段
- **AI 接入**：`monkeypatch` `create_deep_agent`（仿 `agent.py` 测试约定），断言 MCP 工具被 append 进 tools 列表；单 server 失败被跳过

### 6.3 审计

所有写操作（create/update/delete server、toggle 全局开关）调 `admin_service._audit(db, actor=admin, action="mcp_*", target_type="mcp_server"/"system_setting", target_id, detail={...})`。`detail` 只放 name/transport/enabled。

### 6.4 安全边界

- 凭据全程加密存储，API 响应只回 `{key: {has_value: bool}}`
- 测试连接是临时连接、不持久化、带 10s 超时
- stdio server = 后端起子进程：属 admin 信任域操作（仅 admin 可配，`require_admin` 兜底），不在本次加白名单

### 6.5 错误处理

- AI 接入：单 server 失败 → 日志 + 跳过（§4.2）
- 测试连接：失败返回 `error` 字段，不抛 500
- 全程保留「service 拥有事务 + `db.rollback()`」约定

## 7. 实施顺序（概览）

1. 数据层：模型 + 迁移 + schemas + service（CRUD + resolve + masking）
2. 后端 API：admin/mcp.py（CRUD + enabled + test）+ 注册
3. AI 接入：tools.py `load_mcp_tools` + 异步化 `create_agent_tools` / `build_agent`
4. 前端：页面 + 表单 + wiring + console 卡片
5. 测试 + 审计 + 安全收尾

详细步骤由后续 writing-plans 产出。
