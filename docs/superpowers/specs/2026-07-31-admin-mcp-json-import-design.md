# Admin MCP 配置 —— JSON 导入 设计文档

> **日期**：2026-07-31
> **主题**：把 admin MCP 配置页的「逐个填表单」改为「粘贴整份 JSON 导入」，保留列表的测试/启停/删除能力。
> **状态**：设计中
> **前置**：`docs/superpowers/specs/2026-07-30-admin-mcp-config-design.md`（MCP 配置页 v1，已合并到 main）

## 1. 背景与目标

MCP 配置页 v1 上线后，实际使用中发现：用户手上的 MCP 配置都是标准 JSON（Claude Desktop / Cursor 的 `{"mcpServers": {...}}` 格式，或省略包裹的裸 server 字典），逐个填表单很繁琐。本次改为：**粘贴整份 JSON，后端自行解析并创建 server**。

### 范围（已确认）

| 维度 | 决策 |
|---|---|
| 输入方式 | **只留 JSON**——去掉逐个填表单，配置全靠粘贴整份 JSON |
| JSON 格式 | 支持**两种**：`{"mcpServers": {...}}` 标准格式 + `{...}` 裸 server 字典；自动识别 stdio/http/sse 三种形态 |
| 同名冲突 | **整体回滚报错**——任一 server 同名则整个导入失败，一个都不写入，错误信息指明哪个 server |
| 列表操作 | 列表保留——每行仍可**测试 / 启停 / 删除**；全局开关保留 |
| 编辑 | 去掉编辑入口——要改 server 删了重导 |
| 落地方案 | **方案 A**：数据模型不动，JSON 只是新增的「导入入口」，复用现有 create/resolve/test/AI 加载 |

### 非目标（YAGNI）

- 不动 `mcp_servers` 表结构（仍是一行一个 server）
- 不做 JSON 导出（用户手上已有 JSON，不需要从系统反导出）
- 不做 JSON 的版本/diff 对比
- 不做单个 server 的编辑入口

## 2. 数据模型

**完全不变。** 复用 v1 的 `mcp_servers` 表（`name/command/args/url/headers_encrypted/env_encrypted/enabled/...`）+ `mcp_global_enabled` 全局开关。`create_mcp_server`（含加密、唯一性校验）、`resolve_mcp_servers`、`test_mcp_server`、AI 工具加载全部复用，零改动。

**无新迁移。**

## 3. 后端：解析器 + 导入端点

### 3.1 解析器（`mcp_config_service.py` 新增）

```python
def parse_mcp_json(raw: dict) -> list[dict]:
    """解析 MCP 配置 JSON → 标准 server 配置列表。

    支持两种外层格式：
    - {"mcpServers": {name: {...}}}  标准格式（有 "mcpServers" 键）
    - {name: {...}}                  裸 server 字典（省略包裹）

    自动识别每个 server 的形态：
    - 有 command → transport=stdio（读 command/args/env）
    - 有 url     → transport=http/sse（看显式 transport 字段，否则 http；读 url/headers）

    未知字段忽略。每个 server 单独校验，失败抛 ValidationError 指明 name。
    """
```

**判定逻辑**：
- `if "mcpServers" in raw and isinstance(raw["mcpServers"], dict): servers = raw["mcpServers"]`
- `else: servers = raw`

**为何这样判定安全**：标准格式的外层唯一合法键就是 `mcpServers`；裸字典里每个 value 都含 `command`/`url`。两种结构互不冲突。不会有人把单个 server 命名为 `mcpServers`。

**每个 server 的解析规则**（`name` = 字典 key）：
- 有 `command`：`transport="stdio"`，`command`=必填 str，`args`=list（默认 `[]`，若非 list 报错），`env`=dict（可选）
- 有 `url`：`transport` = 显式 `transport` 字段值为 `"sse"` 时用 `sse`，否则 `http`；`url`=必填 str，`headers`=dict（可选）
- 既无 `command` 又无 `url`：`raise ValidationError(f"server '{name}' 缺少 command 或 url")`
- `value` 本身不是 dict（如 `"feishu": "xxx"`）：`raise ValidationError(f"server '{name}' 配置必须是对象")`

返回 `[{name, transport, command, args, url, headers, env}, ...]`，字段形态与 `create_mcp_server` 入参一致。

### 3.2 导入端点（`api/admin/mcp.py` 新增）

```python
@router.post("/admin/mcp/servers/import", response_model=list[McpServerOut])
def import_servers(payload: dict, admin, db):
    parsed = mcp_config_service.parse_mcp_json(payload)  # dict → list[dict]
    created = []
    try:
        for cfg in parsed:
            s = svc.create_mcp_server(
                db, name=cfg["name"], transport=cfg["transport"],
                command=cfg.get("command"), args=cfg.get("args"),
                url=cfg.get("url"), headers=cfg.get("headers"),
                env=cfg.get("env"), enabled=True, actor=admin,
            )
            created.append(s)  # create_mcp_server 内部做应用层同名检查，命中即抛 ConflictError
    except Exception:
        db.rollback()
        raise  # ConflictError(409) / ValidationError(422) 透传给前端
    admin_service._audit(
        db, actor=admin, action="import_mcp_servers", target_type="mcp_server",
        target_id=None, detail={"count": len(created), "names": [s.name for s in created]},
    )
    return [svc.to_out(s) for s in created]
```

**关键点**：
- **事务原子性**：解析失败（ValidationError）/ 同名（ConflictError，由 `create_mcp_server` 的唯一性校验抛出）→ `db.rollback()` → 一个都不导入。
- **错误信息**：`create_mcp_server` 已抛 `ConflictError(f"MCP server 名「{name}」已存在")`，解析器抛 `ValidationError(f"server '{name}' ...")`——都指明具体 server。
- **请求体**：用 `dict` 直接收原始 JSON（格式灵活，不强类型校验，解析器内部校验）。
- **审计**：`action="import_mcp_servers"`，`detail={"count", "names"}`，不含凭据明文。

**关于同名检测的实现**：现有 `create_mcp_server` 在 service 层先做 `select ... where name=...` 唯一性检查（应用层），命中即抛 `ConflictError(f"MCP server 名「{name}」已存在")`——**这是主路径**，导入循环里靠它触发回滚。端点里**不需要** `flush()` 也不需要处理 `IntegrityError`：因为 JSON 导入在同一请求、同一事务、串行执行，应用层 select 检查足够（无并发 race）。端点的 try/except 只需捕获 `ConflictError`/`ValidationError` 做 `rollback + raise` 透传即可。这样实现最简单，不引入 `IntegrityError` 转换的复杂度。

## 4. 前端改造

**改动文件**：`apps/web/src/app/(app)/admin/console/mcp/page.tsx`

### 4.1 顶部区改造（替换原「添加 Server」按钮 + Dialog）

- 一个大 `<textarea>`（粘 JSON，`min-h-[200px]`），placeholder：
  ```
  {
    "mcpServers": {
      "server-name": {
        "command": "npx",
        "args": ["-y", "..."]
      }
    }
  }
  ```
- 「导入」按钮（可选旁边「清空」按钮）。
- 点导入：
  1. 前端先 `JSON.parse(text)` 粗校验——非法 JSON 直接 `toast.error("JSON 格式错误")`，不发请求。
  2. 合法 → POST `/admin/mcp/servers/import`。
  3. 成功：`toast.success("已导入 N 个 server")` + 清空文本框 + `invalidateQueries` 刷新列表。
  4. 失败（409 同名 / 422 解析错）：`toast.error(err.message)`（后端返回的具体错误，如「MCP server 名「feishu-mcp」已存在」）。

### 4.2 下方 server 列表 —— 保留

表格不动，每行仍可：
- 测试（FlaskConical 图标）
- 启停（inline Switch，单点即存）
- 删除（Trash2 图标 + confirm）
- 全局开关卡片保留在顶部

### 4.3 删除的代码

- 整个 `McpServerDialog` 组件（手写 Dialog 表单）
- 整个 `KVEditor` 组件（headers/env 动态编辑器）
- `FormState` / `EMPTY_FORM` 类型与常量
- `dialogOpen` / `editingId` / `form` state
- `openCreate` / `openEdit` / `handleSubmit` 函数
- 列表行的「编辑」按钮（Pencil 图标）及 `openEdit` 调用
- 不再使用的 imports：`Pencil`（删）、`Plus`（导入按钮可改用 Upload 图标，或保留 Plus）

### 4.4 新增

- `apps/web/src/lib/api.ts`：`importMcpServers(json: object)` 方法 → `POST /admin/mcp/servers/import`
- `apps/web/src/lib/queries.ts`：`useImportMcpServers` hook（mutation，成功后 invalidate `queryKeys.admin.mcpServers`）
- 顶部 state：`const [jsonText, setJsonText] = useState('')`

### 4.5 保留的 imports

`useState`、`toast`（sonner）、hooks（`useMcpServers`/`useMcpEnabled`/`useToggleMcpGlobal`/`useUpdateMcpServer`/`useDeleteMcpServer`/`useTestMcpServer` + 新增 `useImportMcpServers`）、`McpServer` 类型、`PageShell/PageHeader`、`Button/Input/Skeleton/Switch`、`Table*`、`Trash2`/`FlaskConical` 图标、卡片样式（`var(--shadow-card)` 等）。

## 5. 测试、审计、错误处理

### 5.1 后端测试（追加到 `tests/test_mcp_config_service.py` + `tests/test_admin_mcp_api.py`）

解析器测试（`test_mcp_config_service.py`）：
- 标准 `{"mcpServers": {...}}` 格式 → 正确解析
- 裸字典格式 → 正确解析
- stdio 形态（command/args/env）
- http 形态（url/headers，默认 transport=http）
- sse 形态（显式 `transport: "sse"`）
- 缺 command 且缺 url → `ValidationError`，信息含 server name
- args 非 list → `ValidationError`
- value 非 dict → `ValidationError`
- 未知字段忽略（不报错）

端点测试（`test_admin_mcp_api.py`）：
- `POST /servers/import` 成功：粘 2 个 server → 都创建，返回 list，凭据 masking
- 同名冲突：先建一个 feishu-mcp，再导含 feishu-mcp 的 JSON → 409 + 整体回滚（库里没多出第二个，第一个还在）
- 非法 JSON 结构（缺 command/url）→ 422 + 错误信息含 name
- 非 admin → 403
- 审计记录写入（`action="import_mcp_servers"`）

### 5.2 前端

无单测（项目无前端测试框架）。验证靠 `tsc --noEmit` + 手动。

### 5.3 错误处理

- 解析失败 / 同名 → 事务回滚，前端拿到带具体 server name 的错误信息
- 非法 JSON（前端 `JSON.parse` 失败）→ 前端 toast 拦截，不发请求
- 审计 `detail` 不含凭据明文

## 6. 实施顺序（概览）

1. 后端：`parse_mcp_json` 解析器 + 测试
2. 后端：`POST /admin/mcp/servers/import` 端点 + 测试
3. 前端：`importMcpServers` API 方法 + `useImportMcpServers` hook
4. 前端：页面改造（textarea + 导入按钮，删 Dialog/KVEditor，列表保留）
5. 全量回归（后端 pytest + 前端 tsc/build）

详细步骤由后续 writing-plans 产出。
