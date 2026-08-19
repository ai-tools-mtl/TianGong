'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { useIMAConfig, useSaveIMAConfig } from '@/lib/queries'
import type { IMATestResult } from '@/types/api'

/**
 * /admin/console/ima — 腾讯 ima 检索源全局配置页。
 *
 * 镜像 firecrawl 配置页，多一个 Client ID 字段（ima 鉴权需 client_id + api_key）。
 * admin 配置后，所有用户的章节对话预检索会实时查 ima 知识库合并片段。
 */
export default function IMAConfigPage() {
  const { data, isLoading } = useIMAConfig()
  const save = useSaveIMAConfig()

  const [enabled, setEnabled] = useState(false)
  const [clientId, setClientId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<IMATestResult | null>(null)

  // 首次加载用 query 数据填表单
  useEffect(() => {
    if (data) {
      setEnabled(data.enabled)
    }
  }, [data])

  async function handleTest() {
    // 测试需凭据：编辑模式未改 key 时无法测（已存 key 不回显明文）
    if (!clientId || !apiKey) {
      if (data?.client_id_masked && !clientId && !apiKey) {
        toast.error('测试需重新填写 Client ID 和 API Key（已存凭据不回显明文）')
        return
      }
      toast.error('请先填写 Client ID 和 API Key')
      return
    }
    setTesting(true)
    try {
      const res = await api.testIMAConfig({ client_id: clientId, api_key: apiKey })
      setTestResult(res)
      if (res.ok) {
        toast.success(`连接成功${res.hit_count > 0 ? `，命中 ${res.hit_count} 条` : ''}`)
      } else {
        toast.error(`连接失败：${res.error ?? '未知错误'}`)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '测试失败')
    } finally {
      setTesting(false)
    }
  }

  function handleSave() {
    save.mutate(
      { enabled, client_id: clientId, api_key: apiKey },
      {
        onSuccess: () => {
          toast.success('ima 配置已更新')
          setClientId('')
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
        <PageHeader title="ima 检索源" description="腾讯 ima 知识库全局检索源凭据" />
        <Skeleton className="h-64" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader title="ima 检索源" description="腾讯 ima 知识库全局检索源凭据">
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
            <div className="text-sm font-medium">启用 ima 检索源</div>
            <div className="text-xs text-muted-foreground">
              {enabled ? '开启后，章节对话会实时查询 ima 知识库' : '关闭后不查询 ima'}
            </div>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>

        <div className="space-y-2">
          <Label htmlFor="ima-client-id">Client ID</Label>
          {data?.client_id_masked && (
            <p className="text-xs text-muted-foreground">
              当前：{data.client_id_masked}（留空不修改）
            </p>
          )}
          <Input
            id="ima-client-id"
            type="password"
            placeholder="留空不修改"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="font-mono"
            autoComplete="new-password"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="ima-api-key">API Key</Label>
          {data?.api_key_masked && (
            <p className="text-xs text-muted-foreground">
              当前：{data.api_key_masked}（留空不修改）
            </p>
          )}
          <Input
            id="ima-api-key"
            type="password"
            placeholder="留空不修改"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="font-mono"
            autoComplete="new-password"
          />
        </div>

        <p className="text-xs leading-relaxed text-muted-foreground">
          在 <a href="https://ima.qq.com/agent-interface" target="_blank" rel="noopener noreferrer" className="underline">ima.qq.com/agent-interface</a> 生成 Client ID 和 API Key。
          配置后，对话预检索会实时查询 ima 知识库并合并片段（不导入文件）。
        </p>

        {/* 测试结果 */}
        {testResult && (
          <div
            className={`rounded-md p-2.5 text-[12px] ${
              testResult.ok
                ? 'bg-success/10 text-success'
                : 'bg-destructive/10 text-destructive'
            }`}
          >
            {testResult.ok
              ? `✓ 连接成功${testResult.hit_count > 0 ? `，命中 ${testResult.hit_count} 条` : '（鉴权通过）'}`
              : `✗ 连接失败：${testResult.error ?? '请检查凭据或网络'}`}
          </div>
        )}

        <div className="flex items-center justify-between border-t border-black/[0.07] pt-4 dark:border-white/10">
          <Button type="button" variant="outline" size="sm" disabled={testing} onClick={handleTest}>
            {testing ? '测试中…' : '↻ 测试连接'}
          </Button>
        </div>
      </div>
    </PageShell>
  )
}
