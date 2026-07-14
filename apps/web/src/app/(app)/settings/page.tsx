'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
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
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-xl font-bold">LLM 配置</h1>

      <div className="space-y-1">
        <p className="text-sm text-muted-foreground">
          {myLLM
            ? `当前使用：自配 Key（${myLLM.api_key_masked}，模型 ${myLLM.model}）`
            : '当前使用：全局配置（如有）'}
        </p>
      </div>

      <div className="space-y-4 rounded-lg border p-4">
        <div className="space-y-2">
          <Label htmlFor="baseUrl">API Base URL</Label>
          <Input id="baseUrl" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://open.bigmodel.cn/api/paas/v4" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="apiKey">API Key</Label>
          <Input id="apiKey" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={myLLM?.api_key_masked || '输入你的 API Key'} type="password" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="model">模型名</Label>
          <Input id="model" value={model} onChange={(e) => setModel(e.target.value)} placeholder="glm-4-flash" />
        </div>
        <div className="flex gap-2">
          <Button onClick={handleTest} variant="outline" disabled={testing || !apiKey}>
            {testing ? '测试中...' : '测试连通'}
          </Button>
          <Button onClick={() => saveLLM.mutate()} disabled={saveLLM.isPending || !apiKey}>
            {saveLLM.isPending ? '保存中...' : '保存'}
          </Button>
          {myLLM && (
            <Button onClick={() => deleteLLM.mutate()} variant="ghost" className="text-destructive">
              清除（用全局）
            </Button>
          )}
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        支持 OpenAI 兼容 Provider（智谱 GLM / OpenAI / DeepSeek / 本地 Ollama 等）。
        Key 加密存储，不明文返回。
      </p>
    </div>
  )
}
