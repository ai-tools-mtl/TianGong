'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useMineruConfig, useSaveMineruConfig, useTestMineruConfig } from '@/lib/queries'

/**
 * /admin/console/mineru — MinerU 全局配置页（PDF→Markdown 云端解析）。
 *
 * enabled 开关 + api_token + base_url + model_version 选项 + 测试连接按钮。
 * 配置后，PDF 上传走 MinerU（保留表格/标题的结构化 Markdown，含 OCR）；
 * 未配置或关闭时降级到 pypdf 纯文本提取。
 */
export default function MineruConfigPage() {
  const { data, isLoading } = useMineruConfig()
  const save = useSaveMineruConfig()
  const test = useTestMineruConfig()

  const [enabled, setEnabled] = useState(false)
  const [apiToken, setApiToken] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [modelVersion, setModelVersion] = useState('vlm')

  useEffect(() => {
    if (data) {
      setEnabled(data.enabled)
      setBaseUrl(data.base_url || '')
      setModelVersion(data.model_version || 'vlm')
    }
  }, [data])

  function handleSave() {
    save.mutate(
      {
        enabled,
        api_token: apiToken,
        base_url: baseUrl || null,
        model_version: modelVersion,
      },
      {
        onSuccess: () => {
          toast.success('MinerU 配置已更新')
          setApiToken('')
        },
        onError: (err: { message?: string }) =>
          toast.error(err?.message ?? '保存失败'),
      },
    )
  }

  function handleTest() {
    test.mutate(undefined, {
      onSuccess: (res) => {
        if (res.ok) toast.success(res.message)
        else toast.error(res.message)
      },
      onError: () => toast.error('测试请求失败'),
    })
  }

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="MinerU 配置" description="PDF 转 Markdown 解析服务凭据" />
        <Skeleton className="h-64" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader
        title="MinerU 配置"
        description="PDF 转 Markdown 解析服务（保留表格/标题，含 OCR 扫描件）"
      >
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleTest} disabled={test.isPending || !enabled}>
            {test.isPending ? '测试中...' : '测试连接'}
          </Button>
          <Button onClick={handleSave} disabled={save.isPending}>
            {save.isPending ? '保存中...' : '保存'}
          </Button>
        </div>
      </PageHeader>

      <div className="space-y-4 py-6">
        <div
          className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div>
            <div className="text-sm font-medium">启用 MinerU</div>
            <div className="text-xs text-muted-foreground">
              {enabled
                ? 'PDF 上传将走 MinerU 高质量解析（含表格/OCR）'
                : '关闭后 PDF 走 pypdf 纯文本（扫描件拒收）'}
            </div>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="mu-token">API Token</Label>
          {data?.api_token_masked && (
            <p className="text-xs text-muted-foreground">
              当前：{data.api_token_masked}（留空不修改）
            </p>
          )}
          <Input
            id="mu-token"
            type="password"
            placeholder="sk-...（mineru.net API 管理页创建）"
            value={apiToken}
            onChange={(e) => setApiToken(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            在 mineru.net → API 管理页面创建 token
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="mu-base-url">Base URL</Label>
          <Input
            id="mu-base-url"
            type="url"
            placeholder="https://mineru.net"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="mu-model">解析模型</Label>
          <select
            id="mu-model"
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            value={modelVersion}
            onChange={(e) => setModelVersion(e.target.value)}
          >
            <option value="vlm">vlm（高精度，推荐）</option>
            <option value="pipeline">pipeline（快速稳定）</option>
          </select>
          <p className="text-xs text-muted-foreground">
            vlm：VLM 模型，表格/公式识别最准；pipeline：传统流水线，速度快
          </p>
        </div>
      </div>
    </PageShell>
  )
}
