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
