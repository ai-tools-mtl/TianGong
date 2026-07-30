'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Plus, Trash2, Pencil, FlaskConical } from 'lucide-react'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { useMcpServers, useMcpEnabled, useToggleMcpGlobal,
  useSaveMcpServer, useUpdateMcpServer, useDeleteMcpServer, useTestMcpServer } from '@/lib/queries'
import type { McpServer } from '@/types/api'

type Transport = 'stdio' | 'http' | 'sse'

interface FormState {
  name: string
  transport: Transport
  command: string
  argsText: string  // 每行一个参数
  url: string
  headers: Record<string, string>
  env: Record<string, string>
  enabled: boolean
}

const EMPTY_FORM: FormState = {
  name: '', transport: 'stdio', command: '', argsText: '', url: '',
  headers: {}, env: {}, enabled: true,
}

export default function McpConfigPage() {
  const { data: servers, isLoading } = useMcpServers()
  const { data: enabledData } = useMcpEnabled()
  const toggleGlobal = useToggleMcpGlobal()
  const save = useSaveMcpServer()
  const update = useUpdateMcpServer()
  const remove = useDeleteMcpServer()
  const test = useTestMcpServer()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)

  function openCreate() {
    setForm(EMPTY_FORM)
    setEditingId(null)
    setDialogOpen(true)
  }

  function openEdit(s: McpServer) {
    setForm({
      name: s.name,
      transport: s.transport,
      command: s.command ?? '',
      argsText: (s.args ?? []).join('\n'),
      url: s.url ?? '',
      headers: {},
      env: {},
      enabled: s.enabled,
    })
    setEditingId(s.id)
    setDialogOpen(true)
  }

  function handleSubmit() {
    const args = form.argsText.split('\n').map((x) => x.trim()).filter(Boolean)
    const payload = {
      name: form.name,
      transport: form.transport,
      command: form.transport === 'stdio' ? form.command || null : null,
      args: form.transport === 'stdio' ? args : null,
      url: form.transport !== 'stdio' ? form.url || null : null,
      headers: form.transport !== 'stdio' && Object.keys(form.headers).length ? form.headers : null,
      env: form.transport === 'stdio' && Object.keys(form.env).length ? form.env : null,
      enabled: form.enabled,
    }
    const onSuccess = () => {
      toast.success(editingId ? '已更新' : '已创建')
      setDialogOpen(false)
    }
    const onError = (err: { message?: string }) => toast.error(err?.message ?? '操作失败')
    if (editingId) {
      update.mutate({ id: editingId, payload }, { onSuccess, onError })
    } else {
      save.mutate(payload, { onSuccess, onError })
    }
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
      <PageHeader title="MCP 配置" description="配置 MCP server，agent 生成时自动加载其工具">
        <Button onClick={openCreate}>
          <Plus className="mr-1 h-4 w-4" /> 添加 Server
        </Button>
      </PageHeader>

      <div className="space-y-4 py-6">
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
                      <Button variant="ghost" size="sm" onClick={() => openEdit(s)}>
                        <Pencil className="h-4 w-4" />
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
                    暂无 MCP server，点击右上角添加
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* 添加/编辑 Dialog */}
      {dialogOpen && (
        <McpServerDialog
          form={form}
          setForm={setForm}
          editing={!!editingId}
          onClose={() => setDialogOpen(false)}
          onSubmit={handleSubmit}
          submitting={save.isPending || update.isPending}
        />
      )}
    </PageShell>
  )
}

// ── 表单 Dialog（手写，shadcn Dialog CLI 不可用）──
function McpServerDialog(props: {
  form: FormState
  setForm: (f: FormState) => void
  editing: boolean
  onClose: () => void
  onSubmit: () => void
  submitting: boolean
}) {
  const { form, setForm, editing, onClose, onSubmit, submitting } = props
  const isStdio = form.transport === 'stdio'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl border border-black/[0.07] bg-card p-6 dark:border-white/10"
        style={{ boxShadow: 'var(--shadow-card)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-lg font-semibold">{editing ? '编辑 Server' : '添加 Server'}</h2>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="mcp-name">名称</Label>
            <Input id="mcp-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="web-search" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="mcp-transport">传输方式</Label>
            <select
              id="mcp-transport"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
              value={form.transport}
              onChange={(e) => setForm({ ...form, transport: e.target.value as Transport })}
            >
              <option value="stdio">stdio（本地命令）</option>
              <option value="http">http（远程）</option>
              <option value="sse">sse（远程流式）</option>
            </select>
          </div>

          {isStdio ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-command">命令</Label>
                <Input id="mcp-command" value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} placeholder="npx" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-args">参数（每行一个）</Label>
                <textarea
                  id="mcp-args"
                  className="flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
                  value={form.argsText}
                  onChange={(e) => setForm({ ...form, argsText: e.target.value })}
                  placeholder={'-y\n@modelcontextprotocol/server-filesystem\n.'}
                />
              </div>
              <KVEditor label="环境变量 (env)" kv={form.env} onChange={(env) => setForm({ ...form, env })} />
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="mcp-url">URL</Label>
                <Input id="mcp-url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://example.com/sse" />
              </div>
              <KVEditor label="请求头 (headers)" kv={form.headers} onChange={(headers) => setForm({ ...form, headers })} />
            </>
          )}

          <div className="flex items-center gap-2">
            <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} />
            <Label>启用</Label>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={onSubmit} disabled={submitting || !form.name}>
            {submitting ? '保存中...' : '保存'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ── 键值对动态编辑器（headers / env 通用）──
function KVEditor(props: { label: string; kv: Record<string, string>; onChange: (kv: Record<string, string>) => void }) {
  const { label, kv, onChange } = props
  const keys = Object.keys(kv)
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {keys.map((k) => (
        <div key={k} className="flex gap-2">
          <Input
            className="flex-1"
            value={k}
            onChange={(e) => {
              const newKv = { ...kv }
              const val = newKv[k]; delete newKv[k]; newKv[e.target.value] = val
              onChange(newKv)
            }}
            placeholder="key"
          />
          <Input
            className="flex-1"
            type="password"
            value={kv[k]}
            onChange={(e) => onChange({ ...kv, [k]: e.target.value })}
            placeholder="value（留空则不变）"
          />
          <Button variant="ghost" size="sm" onClick={() => { const n = { ...kv }; delete n[k]; onChange(n) }}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button variant="outline" size="sm" onClick={() => onChange({ ...kv, '': '' })}>
        <Plus className="mr-1 h-4 w-4" /> 添加
      </Button>
    </div>
  )
}
