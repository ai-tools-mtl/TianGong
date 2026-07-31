# MCP 配置 JSON 导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 admin MCP 配置页的「逐个填表单」改为「粘贴整份 JSON 导入」，保留列表的测试/启停/删除能力。

**Architecture:** 数据模型不动（复用 v1 的 `mcp_servers` 表 + 加密 + resolve + test + AI 加载）。新增 `parse_mcp_json` 解析器（支持标准 `mcpServers` 包裹 + 裸字典两种格式，自动识别 stdio/http/sse）+ `POST /admin/mcp/servers/import` 端点（事务原子性，同名整体回滚）。前端把 Dialog 表单换成 textarea + 导入按钮，列表保留。

**Tech Stack:** FastAPI + Pydantic v2（后端）；Next.js + React Query + shadcn/ui（前端）。

**Spec:** `docs/superpowers/specs/2026-07-31-admin-mcp-json-import-design.md`

---

## File Structure

**后端修改：**
- `apps/api/app/services/mcp_config_service.py` — 新增 `parse_mcp_json` 解析器（+ import `ValidationError`）
- `apps/api/app/api/admin/mcp.py` — 新增 `POST /admin/mcp/servers/import` 端点
- `apps/api/tests/test_mcp_config_service.py` — 追加解析器测试
- `apps/api/tests/test_admin_mcp_api.py` — 追加导入端点测试

**前端修改：**
- `apps/web/src/lib/api.ts` — 新增 `importMcpServers` 方法
- `apps/web/src/lib/queries.ts` — 新增 `useImportMcpServers` hook
- `apps/web/src/app/(app)/admin/console/mcp/page.tsx` — 表单换 textarea + 导入按钮，删 Dialog/KVEditor，列表保留

**无新迁移、无新表、无新 schema 类。**

---

## Task 1: parse_mcp_json 解析器 + 测试

**Files:**
- Modify: `apps/api/app/services/mcp_config_service.py`
- Test: `apps/api/tests/test_mcp_config_service.py`

- [ ] **Step 1: 写失败测试**

追加到 `apps/api/tests/test_mcp_config_service.py` 末尾：

```python
import pytest

from app.core.exceptions import ValidationError


def test_parse_json_standard_format():
    """标准 {"mcpServers": {...}} 格式 → 正确解析。"""
    from app.services import mcp_config_service as svc
    raw = {
        "mcpServers": {
            "feishu": {"command": "npx", "args": ["-y", "pkg"]},
        }
    }
    parsed = svc.parse_mcp_json(raw)
    assert len(parsed) == 1
    s = parsed[0]
    assert s["name"] == "feishu"
    assert s["transport"] == "stdio"
    assert s["command"] == "npx"
    assert s["args"] == ["-y", "pkg"]


def test_parse_json_bare_dict_format():
    """裸字典格式（省略 mcpServers 包裹）→ 正确解析。"""
    from app.services import mcp_config_service as svc
    raw = {
        "feishu": {"command": "cmd", "args": ["/c", "npx"]},
    }
    parsed = svc.parse_mcp_json(raw)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "feishu"
    assert parsed[0]["command"] == "cmd"


def test_parse_json_stdio_with_env():
    """stdio 形态读 env。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "s": {"command": "npx", "args": [], "env": {"API_KEY": "x"}},
    }})
    assert parsed[0]["env"] == {"API_KEY": "x"}
    assert parsed[0]["transport"] == "stdio"


def test_parse_json_http_default_transport():
    """有 url → 默认 transport=http，读 headers。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "w": {"url": "https://x/mcp", "headers": {"Authorization": "Bearer t"}},
    }})
    assert parsed[0]["transport"] == "http"
    assert parsed[0]["url"] == "https://x/mcp"
    assert parsed[0]["headers"] == {"Authorization": "Bearer t"}


def test_parse_json_sse_explicit_transport():
    """显式 transport: sse → transport=sse。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "w": {"transport": "sse", "url": "https://x/sse"},
    }})
    assert parsed[0]["transport"] == "sse"


def test_parse_json_missing_command_and_url():
    """既无 command 又无 url → ValidationError，信息含 name。"""
    from app.services import mcp_config_service as svc
    with pytest.raises(ValidationError) as ei:
        svc.parse_mcp_json({"mcpServers": {"bad": {"foo": "bar"}}})
    assert "bad" in str(ei.value)


def test_parse_json_args_not_list():
    """args 非 list → ValidationError。"""
    from app.services import mcp_config_service as svc
    with pytest.raises(ValidationError):
        svc.parse_mcp_json({"mcpServers": {"s": {"command": "npx", "args": "not-a-list"}}})


def test_parse_json_value_not_dict():
    """server value 非 dict → ValidationError。"""
    from app.services import mcp_config_service as svc
    with pytest.raises(ValidationError) as ei:
        svc.parse_mcp_json({"mcpServers": {"s": "just-a-string"}})
    assert "s" in str(ei.value)


def test_parse_json_ignores_unknown_fields():
    """未知字段（type/disabled 等）忽略。"""
    from app.services import mcp_config_service as svc
    parsed = svc.parse_mcp_json({"mcpServers": {
        "s": {"command": "npx", "args": [], "type": "stdio", "disabled": False},
    }})
    assert parsed[0]["command"] == "npx"
    assert "type" not in parsed[0]
    assert "disabled" not in parsed[0]


def test_parse_json_empty():
    """空 mcpServers → 返回空列表（不报错）。"""
    from app.services import mcp_config_service as svc
    assert svc.parse_mcp_json({"mcpServers": {}}) == []
    assert svc.parse_mcp_json({}) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_mcp_config_service.py -v -k parse_json`
Expected: FAIL（`parse_mcp_json` 不存在）。

- [ ] **Step 3: 实现 `parse_mcp_json`**

先在 `apps/api/app/services/mcp_config_service.py` 顶部 import 行（第 16 行 `from app.core.exceptions import ConflictError, NotFoundError`）加上 `ValidationError`：

```python
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
```

然后在文件末尾（`resolve_mcp_servers` 之后，或 `_to_connection` 之前均可——放在 resolve 之后）追加：

```python
# ── JSON 导入解析 ──

def parse_mcp_json(raw: dict) -> list[dict[str, Any]]:
    """解析 MCP 配置 JSON → 标准 server 配置列表。

    支持两种外层格式：
    - {"mcpServers": {name: {...}}}  标准格式（有 "mcpServers" 键）
    - {name: {...}}                  裸 server 字典（省略包裹）

    自动识别每个 server 的形态：
    - 有 command → transport=stdio（读 command/args/env）
    - 有 url     → transport=http/sse（看显式 transport 字段，否则 http；读 url/headers）

    未知字段忽略。每个 server 单独校验，失败抛 ValidationError 指明 name。
    返回 [{name, transport, command, args, url, headers, env}, ...]。
    """
    if "mcpServers" in raw and isinstance(raw["mcpServers"], dict):
        servers_dict = raw["mcpServers"]
    else:
        servers_dict = raw

    result: list[dict[str, Any]] = []
    for name, cfg in servers_dict.items():
        if not isinstance(cfg, dict):
            raise ValidationError(f"server '{name}' 配置必须是对象")

        # 自动识别形态
        has_command = "command" in cfg
        has_url = "url" in cfg

        if has_command:
            command = cfg.get("command")
            if not isinstance(command, str):
                raise ValidationError(f"server '{name}' 的 command 必须是字符串")
            args = cfg.get("args", [])
            if not isinstance(args, list):
                raise ValidationError(f"server '{name}' 的 args 必须是数组")
            env = cfg.get("env")
            if env is not None and not isinstance(env, dict):
                raise ValidationError(f"server '{name}' 的 env 必须是对象")
            result.append({
                "name": name, "transport": "stdio",
                "command": command, "args": args,
                "url": None, "headers": None, "env": env,
            })
        elif has_url:
            url = cfg.get("url")
            if not isinstance(url, str):
                raise ValidationError(f"server '{name}' 的 url 必须是字符串")
            transport = "sse" if cfg.get("transport") == "sse" else "http"
            headers = cfg.get("headers")
            if headers is not None and not isinstance(headers, dict):
                raise ValidationError(f"server '{name}' 的 headers 必须是对象")
            result.append({
                "name": name, "transport": transport,
                "command": None, "args": None,
                "url": url, "headers": headers, "env": None,
            })
        else:
            raise ValidationError(f"server '{name}' 缺少 command 或 url")
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_mcp_config_service.py -v`
Expected: 全部 passed（原 6 个 + 新 10 个 = 16 passed）。

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/services/mcp_config_service.py apps/api/tests/test_mcp_config_service.py
git commit -m "feat(mcp): parse_mcp_json 解析器（支持标准/裸字典 + 三形态自动识别）"
```

---

## Task 2: POST /admin/mcp/servers/import 端点 + 测试

**Files:**
- Modify: `apps/api/app/api/admin/mcp.py`
- Test: `apps/api/tests/test_admin_mcp_api.py`

- [ ] **Step 1: 写失败测试**

追加到 `apps/api/tests/test_admin_mcp_api.py` 末尾：

```python
def test_import_servers_success(client, registered_user, db_session):
    """粘 JSON 导入：成功创建多个 server，凭据 masking。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    resp = client.post("/api/v1/admin/mcp/servers/import", json={
        "mcpServers": {
            "feishu": {"command": "npx", "args": ["-y", "pkg"]},
            "weather": {"url": "https://x/mcp", "headers": {"Authorization": "Bearer t"}},
        }
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 2
    names = {s["name"] for s in data}
    assert names == {"feishu", "weather"}
    # 凭据 masking
    weather = next(s for s in data if s["name"] == "weather")
    assert weather["headers"]["Authorization"] == {"has_value": True}


def test_import_servers_conflict_rolls_back(client, registered_user, db_session):
    """同名冲突 → 整体回滚，一个都不导入，库里保持原状。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    # 先建一个 feishu
    client.post("/api/v1/admin/mcp/servers", json={
        "name": "feishu", "transport": "stdio", "command": "oldcmd", "args": [],
    })

    # 导入含 feishu（同名）+ 另一个新 server
    resp = client.post("/api/v1/admin/mcp/servers/import", json={
        "mcpServers": {
            "feishu": {"command": "newcmd", "args": []},
            "fresh": {"command": "npx", "args": []},
        }
    })
    assert resp.status_code == 409  # ConflictError
    assert "feishu" in resp.json()["message"]

    # 整体回滚：fresh 没被导入，feishu 仍是旧值
    listing = client.get("/api/v1/admin/mcp/servers").json()
    names = {s["name"] for s in listing}
    assert "fresh" not in names  # 回滚了
    feishu = next(s for s in listing if s["name"] == "feishu")
    assert feishu["command"] == "oldcmd"  # 未被覆盖


def test_import_servers_validation_error(client, registered_user, db_session):
    """非法 JSON 结构（缺 command/url）→ 422 + 错误信息含 name。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    resp = client.post("/api/v1/admin/mcp/servers/import", json={
        "mcpServers": {"bad": {"foo": "bar"}},
    })
    assert resp.status_code == 422
    assert "bad" in resp.json()["message"]


def test_import_servers_bare_dict_format(client, registered_user, db_session):
    """裸字典格式（省略 mcpServers 包裹）也能导入。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)

    resp = client.post("/api/v1/admin/mcp/servers/import", json={
        "feishu": {"command": "npx", "args": ["-y", "pkg"]},
    })
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "feishu"


def test_import_servers_non_admin_forbidden(client, registered_user):
    """普通用户 → 403。"""
    _login(client, registered_user)
    resp = client.post("/api/v1/admin/mcp/servers/import", json={"mcpServers": {}})
    assert resp.status_code == 403
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_admin_mcp_api.py -v -k import`
Expected: FAIL（404 路由不存在）。

- [ ] **Step 3: 实现导入端点**

在 `apps/api/app/api/admin/mcp.py` 的 CRUD 区块（`delete_server` 之后、全局开关区块之前）插入：

```python
@router.post("/admin/mcp/servers/import", response_model=list[McpServerOut])
def import_servers(
    payload: dict,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """粘贴 MCP 配置 JSON 批量导入。

    支持 {"mcpServers": {...}} 标准格式 + {name: {...}} 裸字典格式。
    同名/解析错 → 整体回滚，一个都不导入，错误信息指明 server name。
    """
    parsed = svc.parse_mcp_json(payload)
    created = []
    try:
        for cfg in parsed:
            s = svc.create_mcp_server(  # 内部做应用层同名检查，命中即抛 ConflictError
                db, name=cfg["name"], transport=cfg["transport"],
                command=cfg.get("command"), args=cfg.get("args"),
                url=cfg.get("url"), headers=cfg.get("headers"),
                env=cfg.get("env"), enabled=True, actor=admin,
            )
            created.append(s)
    except Exception:
        db.rollback()
        raise  # ConflictError(409) / ValidationError(422) 透传给前端
    admin_service._audit(
        db, actor=admin, action="import_mcp_servers", target_type="mcp_server",
        target_id=None,
        detail={"count": len(created), "names": [s.name for s in created]},
    )
    return [McpServerOut(**svc.to_out(s)) for s in created]
```

**注意路径顺序**：FastAPI 路由匹配按声明顺序。`/admin/mcp/servers/import` 必须在 `/admin/mcp/servers/{server_id}`（动态路径）**之前**声明，否则 `import` 会被当成 `server_id`。把它插在 `create_server`（POST `/servers`）之后、`get_server`（GET `/servers/{id}`）之前最安全。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_admin_mcp_api.py -v`
Expected: 全部 passed（原 4 + 新 5 = 9 passed）。

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/api/admin/mcp.py apps/api/tests/test_admin_mcp_api.py
git commit -m "feat(mcp): POST /admin/mcp/servers/import 批量导入端点（事务原子 + 审计）"
```

---

## Task 3: 前端 API 方法 + hook

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: 加 API 方法**

在 `apps/web/src/lib/api.ts` 的 MCP 方法块（`listMcpServers` 之前，或 `testMcpServer` 之后均可——紧跟在 MCP 块内）加：

```typescript
  importMcpServers: (json: object) =>
    request<import('@/types/api').McpServer[]>('/admin/mcp/servers/import', {
      method: 'POST', body: JSON.stringify(json),
    }),
```

- [ ] **Step 2: 加 hook**

在 `apps/web/src/lib/queries.ts` 的 MCP hooks 块（`useTestMcpServer` 之前或之后）加：

```typescript
export function useImportMcpServers() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (json: object) => api.importMcpServers(json),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpServers })
    },
  })
}
```

- [ ] **Step 3: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无新增类型错误。

- [ ] **Step 4: 提交**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/queries.ts
git commit -m "feat(mcp/web): importMcpServers API 方法 + useImportMcpServers hook"
```

---

## Task 4: 前端页面改造（表单换 textarea + 导入按钮）

**Files:**
- Modify: `apps/web/src/app/(app)/admin/console/mcp/page.tsx`

> 无单测（项目无前端测试框架）。验证靠 `tsc --noEmit`。

- [ ] **Step 1: 重写 page.tsx**

整个文件替换为以下内容（删除 Dialog/KVEditor/表单 state，换成 textarea + 导入按钮；列表保留测试/启停/删除；去掉编辑按钮）：

```tsx
'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Trash2, FlaskConical, Upload } from 'lucide-react'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  useMcpServers, useMcpEnabled, useToggleMcpGlobal,
  useUpdateMcpServer, useDeleteMcpServer, useTestMcpServer, useImportMcpServers,
} from '@/lib/queries'
import type { McpServer } from '@/types/api'

const SAMPLE_PLACEHOLDER = `{
  "mcpServers": {
    "server-name": {
      "command": "npx",
      "args": ["-y", "..."]
    }
  }
}`

export default function McpConfigPage() {
  const { data: servers, isLoading } = useMcpServers()
  const { data: enabledData } = useMcpEnabled()
  const toggleGlobal = useToggleMcpGlobal()
  const update = useUpdateMcpServer()
  const remove = useDeleteMcpServer()
  const test = useTestMcpServer()
  const importMcp = useImportMcpServers()

  const [jsonText, setJsonText] = useState('')

  function handleImport() {
    let parsed: unknown
    try {
      parsed = JSON.parse(jsonText)
    } catch {
      toast.error('JSON 格式错误，请检查')
      return
    }
    importMcp.mutate(parsed as object, {
      onSuccess: (res) => {
        toast.success(`已导入 ${res.length} 个 server`)
        setJsonText('')
      },
      onError: (err: { message?: string }) =>
        toast.error(err?.message ?? '导入失败'),
    })
  }

  function handleToggleGlobal(next: boolean) {
    toggleGlobal.mutate({ enabled: next }, {
      onSuccess: () => toast.success(next ? '已开启 MCP 工具加载' : '已关闭 MCP 工具加载'),
      onError: () => toast.error('切换失败'),
    })
  }

  function handleToggleRow(s: McpServer, next: boolean) {
    update.mutate({ id: s.id, payload: { enabled: next } }, {
      onSuccess: () => toast.success(next ? '已启用' : '已禁用'),
      onError: () => toast.error('切换失败'),
    })
  }

  function handleDelete(s: McpServer) {
    if (!confirm(`确认删除 MCP server「${s.name}」？`)) return
    remove.mutate(s.id, {
      onSuccess: () => toast.success('已删除'),
      onError: () => toast.error('删除失败'),
    })
  }

  function handleTest(s: McpServer) {
    test.mutate(s.id, {
      onSuccess: (res) => {
        if (res.ok) toast.success(`连接成功，共 ${res.tool_count} 个工具：${res.tool_names.join(', ')}`)
        else toast.error(`测试失败：${res.error}`)
      },
      onError: () => toast.error('测试请求失败'),
    })
  }

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="MCP 配置" description="MCP server 全局管理" />
        <Skeleton className="h-64" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader title="MCP 配置" description="粘贴 MCP 配置 JSON，agent 生成时自动加载其工具">
        <Button onClick={handleImport} disabled={importMcp.isPending || !jsonText.trim()}>
          <Upload className="mr-1 h-4 w-4" />
          {importMcp.isPending ? '导入中...' : '导入'}
        </Button>
      </PageHeader>

      <div className="space-y-4 py-6">
        {/* JSON 导入区 */}
        <div
          className="rounded-2xl border border-black/[0.07] bg-card p-4 dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div className="mb-2 text-sm font-medium">粘贴 MCP 配置 JSON</div>
          <div className="mb-2 text-xs text-muted-foreground">
            支持标准格式（含 mcpServers 包裹）或裸 server 字典。同名 server 会导致整体导入失败。
          </div>
          <textarea
            className="flex min-h-[200px] w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm"
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            placeholder={SAMPLE_PLACEHOLDER}
          />
        </div>

        {/* 全局开关 */}
        <div
          className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div>
            <div className="text-sm font-medium">启用 MCP 工具加载</div>
            <div className="text-xs text-muted-foreground">
              {enabledData?.enabled
                ? '已启用 server 的工具将被 agent 加载'
                : '关闭后，所有 MCP server 的工具都不会被 agent 加载'}
            </div>
          </div>
          <Switch
            checked={enabledData?.enabled ?? false}
            onCheckedChange={handleToggleGlobal}
            disabled={toggleGlobal.isPending}
          />
        </div>

        {/* server 列表 */}
        <div className="rounded-2xl border border-black/[0.07] bg-card dark:border-white/10" style={{ boxShadow: 'var(--shadow-card)' }}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>传输</TableHead>
                <TableHead>目标</TableHead>
                <TableHead>启用</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(servers ?? []).map((s: McpServer) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell>{s.transport}</TableCell>
                  <TableCell className="max-w-[280px] truncate text-xs text-muted-foreground">
                    {s.transport === 'stdio' ? `${s.command} ${(s.args ?? []).join(' ')}` : s.url}
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={s.enabled}
                      onCheckedChange={(v) => handleToggleRow(s, v)}
                      disabled={update.isPending}
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => handleTest(s)} disabled={test.isPending}>
                        <FlaskConical className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(s)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {(servers ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                    暂无 MCP server，粘贴 JSON 后点导入
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </PageShell>
  )
}
```

**关于 `Input` import**：新版页面不再使用 `Input` 组件（textarea 用原生 `<textarea>`），上面的代码已移除 `Input` 的 import，无需手动删。

- [ ] **Step 2: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无新增类型错误。

> 若报 `Upload` 图标不存在：lucide-react 有 `Upload` 图标，确认导入名正确。若 tsc 报某组件未用，按提示删掉对应 import。

- [ ] **Step 3: 提交**

```bash
git add "apps/web/src/app/(app)/admin/console/mcp/page.tsx"
git commit -m "feat(mcp/web): MCP 配置页改 JSON 导入（textarea + 按钮，删表单/Dialog）"
```

---

## Task 5: 全量回归 + 手动验证

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest`
Expected: 全部 PASS（含新增解析器 10 + 端点 5 测试，无回归）。

- [ ] **Step 2: 前端构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功，`/admin/console/mcp` 路由正常。

- [ ] **Step 3: 手动验证（启动后端 + 前端）**

```bash
cd apps/api && uv run uvicorn app.main:app --reload   # 终端1
cd apps/web && pnpm dev                                # 终端2
```

浏览器 `http://localhost:3000/admin/console/mcp`，验证：
1. 看到大文本框（粘 JSON 区）+ 全局开关 + 空列表
2. 粘标准格式 `{"mcpServers": {"feishu": {"command":"cmd","args":["/c","npx","-y","@mcp_hub_org/cli@latest","run","feishu-mcp"]}}}`，点导入 → toast「已导入 1 个」+ 列表出现 feishu（stdio，显示 command+args）
3. 再粘同名 → toast 报「MCP server 名「feishu」已存在」，列表不变
4. 粘裸字典格式 `{ "fs": {"command":"npx","args":[]} }` → 导入成功
5. 粘非法 JSON（如 `{bad}`）→ toast「JSON 格式错误」
6. 粘缺 command/url 的 `{"mcpServers":{"x":{"foo":1}}}` → toast 含 server name
7. 列表行的启停 Switch、删除、测试按钮正常
8. 全局开关切换正常

---

## Self-Review（plan 作者自检，执行者可忽略）

**Spec 覆盖：**
- §1 范围（只留 JSON / 自动识别三形态 / 同名回滚 / 列表保留 / 去编辑）→ Task 1,2,4 ✓
- §2 数据模型不动 → 无迁移任务 ✓（计划里确实无迁移）
- §3 后端解析器 + 端点（事务原子 + 审计 + 错误信息含 name）→ Task 1,2 ✓
- §4 前端 textarea + 删 Dialog/KVEditor + 列表保留 → Task 3,4 ✓
- §5 测试（解析器 9 类 + 端点 5 类）+ 错误处理 → Task 1,2 测试 ✓

**类型一致性：**
- `parse_mcp_json(raw: dict) -> list[dict[str, Any]]`，返回项含 `name/transport/command/args/url/headers/env` —— 与 Task 2 端点里 `cfg["name"]`, `cfg.get("command")` 等读取一致 ✓
- `importMcpServers(json: object)` 返回 `McpServer[]` —— 与 hook 和页面 `res.length` 一致 ✓
- 错误响应 `{message}` 形态 —— 测试 `resp.json()["message"]` 与项目全局异常处理器一致 ✓

**路由顺序风险：** Task 2 Step 3 明确要求 `/import` 在 `/{server_id}` 之前声明，避免 `import` 被当 server_id。已在计划里标红。
