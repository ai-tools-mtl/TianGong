'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data: myLLM } = useQuery({ queryKey: ['my-llm'], queryFn: () => api.getMyLLM() })

  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [testing, setTesting] = useState(false)

  // 同步已存配置
  if (myLLM && !baseUrl && myLLM.base_url) {
    setBaseUrl(myLLM.base_url)
    setModel(myLLM.model)
  }

  const saveLLM = useMutation({
    mutationFn: () => api.setMyLLM({ base_url: baseUrl, api_key: apiKey, model }),
    onSuccess: () => {
      toast.success('LLM 配置已更新')
      qc.invalidateQueries({ queryKey: ['my-llm'] })
      setApiKey('')
    },
    onError: () => toast.error('保存失败'),
  })

  const deleteLLM = useMutation({
    mutationFn: () => api.deleteMyLLM(),
    onSuccess: () => {
      toast.success('已清除，将使用全局配置')
      qc.invalidateQueries({ queryKey: ['my-llm'] })
    },
  })

  async function handleTest() {
    setTesting(true)
    try {
      const res = await api.testMyLLM({ base_url: baseUrl, api_key: apiKey, model })
      if (res.ok) {
        toast.success(`连通成功：${res.response}`)
      } else {
        toast.error(`连通失败：${res.error}`)
      }
    } catch {
      toast.error('测试失败')
    } finally {
      setTesting(false)
    }
  }

  return (
    <PageShell width="narrow">
      <PageHeader title="设置" description="配置你的 LLM 接入（BYOK）" />

      <div className="py-6 space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-[15px]">当前状态</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-[13px] text-muted-foreground">
              {myLLM
                ? `使用自配 Key（${myLLM.api_key_masked}，模型 ${myLLM.model}）`
                : '使用全局配置（如有）'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-[15px]">LLM 配置</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
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
              <Label htmlFor="apiKey">API Key</Label>
              <Input
                id="apiKey"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={myLLM?.api_key_masked || '输入你的 API Key'}
                type="password"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="model">模型名</Label>
              <Input
                id="model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="glm-4-flash"
              />
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button onClick={handleTest} variant="outline" disabled={testing || !apiKey}>
                {testing ? '测试中...' : '测试连通'}
              </Button>
              <Button onClick={() => saveLLM.mutate()} disabled={saveLLM.isPending || !apiKey}>
                {saveLLM.isPending ? '保存中...' : '保存'}
              </Button>
              {myLLM && (
                <Button
                  onClick={() => deleteLLM.mutate()}
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                >
                  清除（用全局）
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        <p className="px-1 text-[12px] text-muted-foreground">
          支持 OpenAI 兼容 Provider（智谱 GLM / OpenAI / DeepSeek / 本地 Ollama 等）。Key 加密存储，不明文返回。
        </p>
      </div>
    </PageShell>
  )
}
