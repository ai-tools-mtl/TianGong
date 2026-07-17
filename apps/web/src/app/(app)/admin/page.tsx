'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import type { AdminUser, AuditLogItem, GlobalLLMSettings, LLMStats } from '@/types/api'

export default function AdminPage() {
  const qc = useQueryClient()
  const { data: users } = useQuery({ queryKey: ['admin-users'], queryFn: () => api.listUsers() })
  const { data: llmSettings } = useQuery({ queryKey: ['global-llm'], queryFn: () => api.getGlobalLLM() })
  const { data: stats } = useQuery({ queryKey: ['llm-stats'], queryFn: () => api.listLLMStats(7) })
  const { data: auditPage } = useQuery({ queryKey: ['audit-logs'], queryFn: () => api.listAuditLogs(1, 50) })

  const [enabled, setEnabled] = useState(true)
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [resetTarget, setResetTarget] = useState<{ id: string; name: string } | null>(null)
  const [newPassword, setNewPassword] = useState('')

  // 同步加载的配置到表单
  if (llmSettings && !baseUrl && llmSettings.global_config) {
    setEnabled(llmSettings.llm_global_enabled)
    setBaseUrl(llmSettings.global_config.base_url)
    setModel(llmSettings.global_config.model)
  }

  const saveLLM = useMutation({
    mutationFn: () =>
      api.setGlobalLLM({
        enabled,
        base_url: baseUrl || undefined,
        api_key: apiKey || undefined,
        model: model || undefined,
      }),
    onSuccess: () => {
      toast.success('全局 LLM 配置已更新')
      qc.invalidateQueries({ queryKey: ['global-llm'] })
      qc.invalidateQueries({ queryKey: ['audit-logs'] })
      setApiKey('')
    },
    onError: () => toast.error('保存失败'),
  })

  const banMutation = useMutation({
    mutationFn: ({ userId, status }: { userId: string; status: 'active' | 'disabled' }) =>
      api.banUser(userId, status),
    onSuccess: (_d, vars) => {
      toast.success(vars.status === 'disabled' ? '已封禁' : '已解禁')
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      qc.invalidateQueries({ queryKey: ['audit-logs'] })
    },
    onError: () => toast.error('操作失败（可能受自我保护约束）'),
  })

  const resetMutation = useMutation({
    mutationFn: () => api.resetUserPassword(resetTarget!.id, newPassword),
    onSuccess: () => {
      toast.success('密码已重置，请线下告知用户')
      qc.invalidateQueries({ queryKey: ['audit-logs'] })
      setResetTarget(null)
      setNewPassword('')
    },
    onError: () => toast.error('重置失败'),
  })

  const usersList: AdminUser[] = users ?? []
  const auditItems: AuditLogItem[] = auditPage?.items ?? []
  const statsData: LLMStats | undefined = stats

  return (
    <PageShell>
      <PageHeader title="管理后台" description="用户运营 · 监控 · 审计" />

      <div className="py-6 space-y-8">
        {/* 知识库审核入口 */}
        <section>
          <Link
            href="/admin/review"
            className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-sm hover:bg-accent"
          >
            知识库审核 →
          </Link>
        </section>
        {/* 用户列表 + 封禁/重置 */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">
            用户<span className="ml-2 text-[13px] font-normal text-muted-foreground">{usersList.length}</span>
          </h2>
          <Card className="overflow-hidden">
            <div className="divide-y">
              {usersList.map((u) => (
                <div key={u.id} className="flex items-center justify-between px-4 py-3">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-medium">{u.name}</span>
                      <span className="text-[13px] text-muted-foreground">@{u.username}</span>
                      {u.role === 'admin' && <Badge>管理员</Badge>}
                      {u.status === 'disabled' && <Badge variant="destructive">已封禁</Badge>}
                    </div>
                    <p className="text-[12px] text-muted-foreground">
                      {u.email || '—'} · {u.project_count} 个项目 · {u.has_own_llm_key ? '自配 Key' : '用全局 Key'} · {u.status}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {u.status === 'active' ? (
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={banMutation.isPending}
                        onClick={() => banMutation.mutate({ userId: u.id, status: 'disabled' })}
                      >
                        封禁
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        disabled={banMutation.isPending}
                        onClick={() => banMutation.mutate({ userId: u.id, status: 'active' })}
                      >
                        解禁
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setResetTarget({ id: u.id, name: u.name })
                        setNewPassword('')
                      }}
                    >
                      重置密码
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </section>

        {/* 重置密码弹层（简易内联） */}
        {resetTarget && (
          <section className="space-y-3">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-[14px]">重置 {resetTarget.name} 的密码</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="newPwd">新密码</Label>
                  <Input
                    id="newPwd"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    type="password"
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    onClick={() => resetMutation.mutate()}
                    disabled={resetMutation.isPending || !newPassword}
                  >
                    {resetMutation.isPending ? '重置中...' : '确认重置'}
                  </Button>
                  <Button variant="outline" onClick={() => setResetTarget(null)}>
                    取消
                  </Button>
                </div>
              </CardContent>
            </Card>
          </section>
        )}

        {/* LLM 调用统计 */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">LLM 调用统计（近 7 天）</h2>
          {statsData ? (
            <Card>
              <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4 py-4 text-[13px]">
                <div>
                  <div className="text-muted-foreground">总调用</div>
                  <div className="text-[16px] font-semibold">{statsData.total_calls}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">成功</div>
                  <div className="text-[16px] font-semibold text-green-600">{statsData.total_success}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">失败</div>
                  <div className="text-[16px] font-semibold text-red-600">{statsData.total_failed}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">平均耗时</div>
                  <div className="text-[16px] font-semibold">
                    {statsData.avg_duration_ms ? Math.round(statsData.avg_duration_ms) : 0} ms
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : (
            <p className="text-[13px] text-muted-foreground">加载中...</p>
          )}
          {statsData && statsData.by_model.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-[14px]">按模型</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="divide-y text-[13px]">
                  {statsData.by_model.map((m) => (
                    <div key={m.model} className="flex justify-between py-2">
                      <span>{m.model}</span>
                      <span className="text-muted-foreground">
                        {m.calls} 次 · 失败 {m.failed}
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </section>

        {/* 全局 LLM 配置 */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">全局 LLM 配置</h2>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px]">Provider</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <label className="flex items-center gap-2 text-[13px]">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  id="enabled"
                  className="size-4 accent-primary"
                />
                <span>提供全局 Key（关闭则强制用户自配）</span>
              </label>
              <div className="space-y-2">
                <Label htmlFor="baseUrl">API Base URL</Label>
                <Input
                  id="baseUrl"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://open.bigmodel.cn/api/paas/v4"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="apiKey">API Key（留空不修改）</Label>
                <Input
                  id="apiKey"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={llmSettings?.global_config?.api_key_masked || '输入新 Key'}
                  type="password"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="model">模型</Label>
                <Input
                  id="model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="glm-4-flash"
                />
              </div>
              <Button onClick={() => saveLLM.mutate()} disabled={saveLLM.isPending}>
                {saveLLM.isPending ? '保存中...' : '保存'}
              </Button>
            </CardContent>
          </Card>
        </section>

        {/* 审计日志 */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">审计日志</h2>
          <Card>
            <div className="divide-y text-[13px]">
              {auditItems.length === 0 && (
                <div className="px-4 py-3 text-muted-foreground">暂无记录</div>
              )}
              {auditItems.map((a) => (
                <div key={a.id} className="px-4 py-3 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{a.action}</span>
                    <span className="text-muted-foreground">@{a.actor_username}</span>
                    <span className="text-muted-foreground">
                      → {a.target_type}
                      {a.target_id ? `:${a.target_id}` : ''}
                    </span>
                  </div>
                  {a.detail && (
                    <p className="text-[12px] text-muted-foreground">{JSON.stringify(a.detail)}</p>
                  )}
                  <p className="text-[11px] text-muted-foreground">
                    {a.created_at ? new Date(a.created_at).toLocaleString() : ''}
                  </p>
                </div>
              ))}
            </div>
          </Card>
        </section>
      </div>
    </PageShell>
  )
}
