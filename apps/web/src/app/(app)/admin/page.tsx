'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import Link from 'next/link'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import type { AdminUser, AuditLogItem, GlobalLLMSettings, LLMStats, UserStats } from '@/types/api'

export default function AdminPage() {
  const qc = useQueryClient()

  // ── Queries ──
  const { data: users } = useQuery({ queryKey: ['admin-users'], queryFn: () => api.listUsers() })
  const { data: userStats } = useQuery({ queryKey: ['user-stats'], queryFn: () => api.listUserStats() })
  const { data: llmSettings } = useQuery({ queryKey: ['global-llm'], queryFn: () => api.getGlobalLLM() })
  const [statsDays, setStatsDays] = useState(7)
  const { data: stats } = useQuery({
    queryKey: ['llm-stats', statsDays],
    queryFn: () => api.listLLMStats(statsDays),
  })
  const [auditPage, setAuditPage] = useState(1)
  const [auditSize] = useState(20)
  const { data: auditData } = useQuery({
    queryKey: ['audit-logs', auditPage, auditSize],
    queryFn: () => api.listAuditLogs(auditPage, auditSize),
  })

  // ── 全局 LLM 配置表单状态 ──
  const [enabled, setEnabled] = useState(true)
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [embeddingModel, setEmbeddingModel] = useState('')
  const [allowedModelsStr, setAllowedModelsStr] = useState('')
  const [resetTarget, setResetTarget] = useState<{ id: string; name: string } | null>(null)
  const [newPassword, setNewPassword] = useState('')

  // 同步加载的配置到表单（one-shot init：baseUrl 为空才填充，避免覆盖用户编辑）。
  // 使用独立 initialized flag 避免清空 baseUrl 时重复触发。
  const [initialized, setInitialized] = useState(false)
  if (llmSettings && !initialized) {
    setInitialized(true)
    setEnabled(llmSettings.llm_global_enabled)
    if (llmSettings.global_config) {
      setBaseUrl(llmSettings.global_config.base_url)
      setModel(llmSettings.global_config.model)
      setEmbeddingModel(llmSettings.global_config.embedding_model ?? '')
      setAllowedModelsStr((llmSettings.global_config.allowed_models ?? []).join(', '))
    }
  }

  // ── Mutations ──
  const saveLLM = useMutation({
    mutationFn: () =>
      api.setGlobalLLM({
        enabled,
        base_url: baseUrl || undefined,
        api_key: apiKey || undefined,
        model: model || undefined,
        embedding_model: embeddingModel,
        allowed_models: allowedModelsStr
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
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

  const grantMutation = useMutation({
    mutationFn: (userId: string) => api.grantGlobalLLM(userId),
    onSuccess: () => {
      toast.success('已授权使用全局 Key')
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      qc.invalidateQueries({ queryKey: ['user-stats'] })
      qc.invalidateQueries({ queryKey: ['audit-logs'] })
    },
    onError: () => toast.error('授权失败（可能受自我保护约束）'),
  })

  const revokeMutation = useMutation({
    mutationFn: (userId: string) => api.revokeGlobalLLM(userId),
    onSuccess: () => {
      toast.success('已撤销全局 Key 授权')
      qc.invalidateQueries({ queryKey: ['admin-users'] })
      qc.invalidateQueries({ queryKey: ['user-stats'] })
      qc.invalidateQueries({ queryKey: ['audit-logs'] })
    },
    onError: () => toast.error('撤销失败'),
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
  const auditItems: AuditLogItem[] = auditData?.items ?? []
  const statsData: LLMStats | undefined = stats
  const userStatsData: UserStats | undefined = userStats
  const recentAudit: AuditLogItem[] = auditData?.items.slice(0, 3) ?? []

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

        {/* Section A — 仪表盘卡片（顶部，4 个） */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {/* Card 1: 用户 */}
          <Card>
            <CardContent className="py-4 text-[13px]">
              <div className="text-muted-foreground">用户 · 总数</div>
              <div className="text-[22px] font-semibold">{userStatsData?.total ?? '—'}</div>
              <div className="mt-1 text-[12px] text-muted-foreground">
                {userStatsData ? (
                  <>
                    {userStatsData.active} 活跃 · {userStatsData.disabled} 禁用 · 新增 7d {userStatsData.new_7d}
                  </>
                ) : (
                  '加载中...'
                )}
              </div>
            </CardContent>
          </Card>

          {/* Card 2: LLM 调用（近 N 天） */}
          <Card>
            <CardContent className="py-4 text-[13px]">
              <div className="text-muted-foreground">LLM 调用（近 {statsDays} 天）</div>
              <div className="text-[22px] font-semibold">{statsData?.total_calls ?? '—'}</div>
              <div className="mt-1 text-[12px] text-muted-foreground">
                {statsData ? (
                  <>
                    成功 <span className="text-green-600">{statsData.total_success}</span> · 失败{' '}
                    <span className="text-red-600">{statsData.total_failed}</span>
                  </>
                ) : (
                  '加载中...'
                )}
              </div>
              {statsData && (
                <div className="mt-0.5 text-[12px] text-muted-foreground">
                  ↑{formatTokens(statsData.total_prompt_tokens)} ↓
                  {formatTokens(statsData.total_completion_tokens)}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Card 3: 全局 Key 授权 */}
          <Card>
            <CardContent className="py-4 text-[13px]">
              <div className="text-muted-foreground">全局 Key 授权</div>
              <div className="text-[22px] font-semibold">{userStatsData?.granted_count ?? '—'}</div>
              <div className="mt-1 text-[12px] text-muted-foreground">
                {userStatsData ? `共 ${userStatsData.total} 用户` : '加载中...'}
              </div>
            </CardContent>
          </Card>

          {/* Card 4: 近期操作（审计摘要） */}
          <Card>
            <CardContent className="py-4 text-[13px]">
              <div className="text-muted-foreground">近期操作</div>
              {recentAudit.length > 0 ? (
                <ul className="mt-1 space-y-0.5 text-[12px]">
                  {recentAudit.map((a) => (
                    <li key={a.id} className="truncate">
                      <span className="font-medium">{a.action}</span>{' '}
                      <span className="text-muted-foreground">@{a.actor_username}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-1 text-[12px] text-muted-foreground">暂无记录，查看下方完整日志</div>
              )}
            </CardContent>
          </Card>
        </section>

        {/* Section B — 用户管理（增强） */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">
            用户管理<span className="ml-2 text-[13px] font-normal text-muted-foreground">{usersList.length}</span>
          </h2>
          <Card className="overflow-hidden">
            <div className="divide-y">
              {usersList.map((u) => (
                <div key={u.id} className="flex items-center justify-between px-4 py-3">
                  <div className="space-y-0.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[14px] font-medium">{u.name}</span>
                      <span className="text-[13px] text-muted-foreground">@{u.username}</span>
                      {u.role === 'admin' && <Badge>管理员</Badge>}
                      {u.status === 'disabled' && <Badge variant="destructive">已封禁</Badge>}
                      {u.has_global_grant && (
                        <Badge variant="secondary" className="bg-emerald-100 text-emerald-700">
                          已授权
                        </Badge>
                      )}
                    </div>
                    <p className="text-[12px] text-muted-foreground">
                      {u.email || '—'} · {u.project_count} 个项目 ·{' '}
                      {u.has_own_llm_key ? '自配 Key' : '用全局 Key'} · {u.status}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {/* admin 免授权，不显示 grant/revoke */}
                    {u.role !== 'admin' &&
                      (u.has_global_grant ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={revokeMutation.isPending}
                          onClick={() => revokeMutation.mutate(u.id)}
                        >
                          撤销授权
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          disabled={grantMutation.isPending}
                          onClick={() => grantMutation.mutate(u.id)}
                        >
                          授权
                        </Button>
                      ))}
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

        {/* Section C — LLM 调用统计（增强 token 显示 + 天数选择） */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-[15px] font-semibold">LLM 调用统计（近 {statsDays} 天）</h2>
            <div className="flex items-center gap-1">
              {[7, 30].map((d) => (
                <Button
                  key={d}
                  size="sm"
                  variant={statsDays === d ? 'default' : 'outline'}
                  onClick={() => setStatsDays(d)}
                >
                  {d} 天
                </Button>
              ))}
            </div>
          </div>
          {statsData ? (
            <>
              <Card>
                <CardContent className="grid grid-cols-2 gap-4 py-4 text-[13px] md:grid-cols-3 xl:grid-cols-6">
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
                  <div>
                    <div className="text-muted-foreground">输入 tokens ↑</div>
                    <div className="text-[16px] font-semibold">{formatTokens(statsData.total_prompt_tokens)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">输出 tokens ↓</div>
                    <div className="text-[16px] font-semibold">{formatTokens(statsData.total_completion_tokens)}</div>
                  </div>
                </CardContent>
              </Card>

              {statsData.by_model.length > 0 && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-[14px]">按模型</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="divide-y text-[13px]">
                      {statsData.by_model.map((m) => (
                        <div key={m.model} className="flex flex-wrap items-center justify-between gap-2 py-2">
                          <span className="font-medium">{m.model}</span>
                          <span className="text-muted-foreground">
                            {m.calls} 次 · 失败 {m.failed} · ↑{formatTokens(m.prompt_tokens)} ↓
                            {formatTokens(m.completion_tokens)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          ) : (
            <p className="text-[13px] text-muted-foreground">加载中...</p>
          )}
        </section>

        {/* Section D — 全局 LLM 配置（增强 allowed_models + embedding_model） */}
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
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="model">对话模型</Label>
                  <Input
                    id="model"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="glm-4-flash"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="embeddingModel">Embedding 模型</Label>
                  <Input
                    id="embeddingModel"
                    value={embeddingModel}
                    onChange={(e) => setEmbeddingModel(e.target.value)}
                    placeholder="embedding-3"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="allowedModels">允许的模型（逗号分隔）</Label>
                <Input
                  id="allowedModels"
                  value={allowedModelsStr}
                  onChange={(e) => setAllowedModelsStr(e.target.value)}
                  placeholder="glm-4-flash, glm-4-air, glm-4-plus"
                />
                <p className="text-[12px] text-muted-foreground">
                  保存时按英文逗号拆分为列表。当前配置：
                  {llmSettings?.global_config?.allowed_models?.length ? (
                    <span className="ml-1 text-foreground">
                      {llmSettings.global_config.allowed_models.join('、')}
                    </span>
                  ) : (
                    <span className="ml-1">未配置</span>
                  )}
                </p>
              </div>
              <Button onClick={() => saveLLM.mutate()} disabled={saveLLM.isPending}>
                {saveLLM.isPending ? '保存中...' : '保存'}
              </Button>
            </CardContent>
          </Card>
        </section>

        {/* Section E — 审计日志（加分页） */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-[15px] font-semibold">
              审计日志
              {auditData && (
                <span className="ml-2 text-[13px] font-normal text-muted-foreground">
                  共 {auditData.total} 条
                </span>
              )}
            </h2>
            {auditData && (
              <span className="text-[12px] text-muted-foreground">
                第 {auditData.page} 页（每页 {auditData.size}）
              </span>
            )}
          </div>
          <Card>
            <div className="divide-y text-[13px]">
              {auditItems.length === 0 && (
                <div className="px-4 py-3 text-muted-foreground">暂无记录</div>
              )}
              {auditItems.map((a) => (
                <div key={a.id} className="space-y-0.5 px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
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
          {auditData && (
            <div className="flex items-center justify-end gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={auditPage <= 1}
                onClick={() => setAuditPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={auditItems.length < auditSize}
                onClick={() => setAuditPage((p) => p + 1)}
              >
                下一页
              </Button>
            </div>
          )}
        </section>
      </div>
    </PageShell>
  )
}

/** Token 数量格式化（≥1k 显示为 1.2k）。 */
function formatTokens(n: number): string {
  if (n >= 1000) {
    const k = n / 1000
    return `${k >= 100 ? Math.round(k) : k.toFixed(1)}k`
  }
  return String(n)
}
