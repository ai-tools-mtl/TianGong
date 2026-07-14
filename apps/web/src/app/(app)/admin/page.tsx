'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import type { AdminUser, GlobalLLMSettings } from '@/types/api'

export default function AdminPage() {
  const qc = useQueryClient()
  const { data: users } = useQuery({ queryKey: ['admin-users'], queryFn: () => api.listUsers() })
  const { data: llmSettings } = useQuery({ queryKey: ['global-llm'], queryFn: () => api.getGlobalLLM() })

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
    mutationFn: () => api.setGlobalLLM({ enabled, base_url: baseUrl || undefined, api_key: apiKey || undefined, model: model || undefined }),
    onSuccess: () => {
      toast.success('全局 LLM 配置已更新')
      qc.invalidateQueries({ queryKey: ['global-llm'] })
      setApiKey('')
    },
    onError: () => toast.error('保存失败'),
  })

  const usersList: AdminUser[] = users ?? []

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <h1 className="text-xl font-bold">管理后台</h1>

      {/* 用户列表 */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">用户（{usersList.length}）</h2>
        <div className="space-y-2">
          {usersList.map((u) => (
            <div key={u.id} className="flex items-center justify-between rounded-lg border p-3">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{u.name}</span>
                  <span className="text-sm text-muted-foreground">{u.email}</span>
                  {u.role === 'admin' && <Badge>管理员</Badge>}
                </div>
                <p className="text-xs text-muted-foreground">
                  {u.project_count} 个项目 · {u.has_own_llm_key ? '自配Key' : '用全局Key'} · {u.status}
                </p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 全局 LLM 配置 */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">全局 LLM 配置</h2>
        <div className="space-y-4 rounded-lg border p-4">
          <div className="flex items-center gap-2">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} id="enabled" />
            <Label htmlFor="enabled">提供全局 Key（关闭则强制用户自配）</Label>
          </div>
          <div className="space-y-2">
            <Label htmlFor="baseUrl">API Base URL</Label>
            <Input id="baseUrl" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://open.bigmodel.cn/api/paas/v4" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="apiKey">API Key（留空不修改）</Label>
            <Input id="apiKey" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={llmSettings?.global_config?.api_key_masked || '输入新 Key'} type="password" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="model">模型</Label>
            <Input id="model" value={model} onChange={(e) => setModel(e.target.value)} placeholder="glm-4-flash" />
          </div>
          <Button onClick={() => saveLLM.mutate()} disabled={saveLLM.isPending}>
            {saveLLM.isPending ? '保存中...' : '保存'}
          </Button>
        </div>
      </section>
    </div>
  )
}
