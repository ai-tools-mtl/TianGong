'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import type { AdminUser, GlobalLLMSettings } from '@/types/api'

export default function AdminPage() {
  const qc = useQueryClient()
  const { data: users } = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => api.listUsers(),
  })
  const { data: llmSettings } = useQuery({
    queryKey: ['global-llm'],
    queryFn: () => api.getGlobalLLM(),
  })

  const [enabled, setEnabled] = useState(true)
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')

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
      setApiKey('')
    },
    onError: () => toast.error('保存失败'),
  })

  const usersList: AdminUser[] = users ?? []

  return (
    <PageShell>
      <PageHeader title="管理后台" description="用户与全局 LLM 配置" />

      <div className="py-6 space-y-8">
        {/* 用户列表 */}
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold">
            用户<span className="ml-2 text-[13px] font-normal text-muted-foreground">{usersList.length}</span>
          </h2>
          <Card className="overflow-hidden">
            <div className="divide-y">
              {usersList.map((u) => (
                <div
                  key={u.id}
                  className="flex items-center justify-between px-4 py-3"
                >
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-medium">{u.name}</span>
                      <span className="text-[13px] text-muted-foreground">{u.email}</span>
                      {u.role === 'admin' && <Badge>管理员</Badge>}
                    </div>
                    <p className="text-[12px] text-muted-foreground">
                      {u.project_count} 个项目 · {u.has_own_llm_key ? '自配 Key' : '用全局 Key'} · {u.status}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </Card>
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
      </div>
    </PageShell>
  )
}
