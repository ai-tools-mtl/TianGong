'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useRerankConfig, useSaveRerankConfig, useTestRerankConfig } from '@/lib/queries'

/**
 * /admin/console/rerank — G3 混合检索精排（rerank）配置页。
 *
 * 镜像 /admin/console/firecrawl 的结构：PageShell + PageHeader + 本地 state +
 * useEffect 填表 + mutation + toast。
 * 一个 enabled Switch + base_url / api_key / model 三个 Input + 保存 / 测试连通按钮。
 * 后端端点：GET/PUT /admin/rag/rerank-config + POST /admin/rag/rerank-config/test。
 * 失败时检索链路自动降级返回 RRF 结果（后端兜底，前端无需处理）。
 */
export default function RerankConfigPage() {
  const { data, isLoading } = useRerankConfig()
  const save = useSaveRerankConfig()
  const test = useTestRerankConfig()

  const [enabled, setEnabled] = useState(false)
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')

  // 首次加载用 query 数据填表单（用 useEffect，不在 render 里 setState）。
  // 注意：GET 不返回明文 api_key（has_api_key 标记是否已配置），故不回填 apiKey。
  useEffect(() => {
    if (data) {
      setEnabled(data.enabled)
      setBaseUrl(data.base_url || '')
      setModel(data.model || '')
    }
  }, [data])

  function handleSave() {
    save.mutate(
      { enabled, base_url: baseUrl, api_key: apiKey, model },
      {
        onSuccess: () => {
          toast.success('Rerank 配置已保存')
          // api_key 留空后端保留旧 key，前端清空输入框避免明文驻留
          setApiKey('')
        },
        onError: (err: { message?: string }) =>
          toast.error(err?.message ?? '保存失败'),
      },
    )
  }

  function handleTest() {
    test.mutate(
      { enabled: true, base_url: baseUrl, api_key: apiKey, model },
      {
        onSuccess: (r) =>
          r.ok ? toast.success(r.message) : toast.error(r.message),
        onError: (err: { message?: string }) =>
          toast.error(err?.message ?? '测试失败'),
      },
    )
  }

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="Rerank 配置" description="混合检索的精排模型配置" />
        <Skeleton className="h-64" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader
        title="Rerank 配置"
        description="混合检索的精排模型配置。失败时自动降级返回 RRF 结果。"
      >
        <Button onClick={handleSave} disabled={save.isPending}>
          {save.isPending ? '保存中...' : '保存'}
        </Button>
      </PageHeader>

      <div className="space-y-4 py-6">
        <div
          className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div>
            <div className="text-sm font-medium">启用 rerank</div>
            <div className="text-xs text-muted-foreground">
              {enabled ? '混合检索结果会经过精排模型重排' : '关闭后仅返回 RRF 融合结果'}
            </div>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="rr-base-url">Base URL</Label>
          <Input
            id="rr-base-url"
            type="url"
            placeholder="https://open.bigmodel.cn/api/paas/v4"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="rr-api-key">API Key</Label>
          {data?.has_api_key && (
            <p className="text-xs text-muted-foreground">
              已配置（留空保留原 key）
            </p>
          )}
          <Input
            id="rr-api-key"
            type="password"
            placeholder={data?.has_api_key ? '留空保留原 key' : '输入 API key'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="rr-model">模型名</Label>
          <Input
            id="rr-model"
            placeholder="rerank"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </div>

        <div>
          <Button variant="outline" onClick={handleTest} disabled={test.isPending}>
            {test.isPending ? '测试中...' : '测试连通'}
          </Button>
        </div>
      </div>
    </PageShell>
  )
}
