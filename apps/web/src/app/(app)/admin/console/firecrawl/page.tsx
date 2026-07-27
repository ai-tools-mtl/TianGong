'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useFirecrawlConfig, useSaveFirecrawlConfig } from '@/lib/queries'

/**
 * /admin/console/firecrawl — Firecrawl 全局配置页。
 *
 * 镜像 /admin/console/llm 但更简单（无 chat/embedding 拆分、无 model、无模板）。
 * 一个 enabled Switch 卡片 + api_key Input + base_url Input + 保存按钮。
 */
export default function FirecrawlConfigPage() {
  const { data, isLoading } = useFirecrawlConfig()
  const save = useSaveFirecrawlConfig()

  const [enabled, setEnabled] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')

  // 首次加载用 query 数据填表单（用 useEffect，不在 render 里 setState）
  useEffect(() => {
    if (data) {
      setEnabled(data.enabled)
      setBaseUrl(data.base_url || '')
    }
  }, [data])

  function handleSave() {
    save.mutate(
      {
        enabled,
        api_key: apiKey,
        base_url: baseUrl || null,
      },
      {
        onSuccess: () => {
          toast.success('Firecrawl 配置已更新')
          setApiKey('')
        },
        onError: (err: { message?: string }) =>
          toast.error(err?.message ?? '保存失败'),
      },
    )
  }

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="Firecrawl 配置" description="网页摄入的 API 凭据" />
        <Skeleton className="h-64" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader title="Firecrawl 配置" description="网页摄入的 API 凭据">
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
            <div className="text-sm font-medium">启用 Firecrawl</div>
            <div className="text-xs text-muted-foreground">
              {enabled ? '用户可使用网页摄入功能' : '关闭后用户无法抓取网页'}
            </div>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="fc-api-key">API Key</Label>
          {data?.api_key_masked && (
            <p className="text-xs text-muted-foreground">
              当前：{data.api_key_masked}（留空不修改）
            </p>
          )}
          <Input
            id="fc-api-key"
            type="password"
            placeholder="留空不修改"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="fc-base-url">Base URL</Label>
          <Input
            id="fc-base-url"
            type="url"
            placeholder="https://api.firecrawl.dev"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            默认使用 Firecrawl 云服务，如需自部署可填自定义地址
          </p>
        </div>
      </div>
    </PageShell>
  )
}
