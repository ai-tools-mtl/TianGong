'use client'

import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useGlobalLLMConfig, useSaveGlobalLLM } from '@/lib/queries'

/**
 * /admin/console/llm 全局 LLM 配置（refactor/admin-ia-phase2 切片 2）。
 *
 * 直接搬运阶段 1 主页砍掉的 Section D。配置包括：
 *   - enabled（是否提供全局 Key，关闭则强制用户自配）
 *   - base_url / api_key / model / embedding_model / allowed_models
 *
 * 表单初始化采用 one-shot init 模式（baseUrl 为空才填充，避免覆盖用户编辑），
 * 这是原 Section D 的实现，本切片直接搬运不重构（用户决策：直接搬运）。
 *
 * 安全：api_key 留空表示不修改（后端只在前端传值时更新）。审计只记非敏感字段。
 */
export default function ConsoleLLMConfigPage() {
  const { data: llmSettings } = useGlobalLLMConfig()
  const saveLLM = useSaveGlobalLLM()

  // 表单状态
  const [enabled, setEnabled] = useState(true)
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [embeddingModel, setEmbeddingModel] = useState('')
  const [allowedModelsStr, setAllowedModelsStr] = useState('')

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

  function handleSave() {
    saveLLM.mutate(
      {
        enabled,
        base_url: baseUrl || undefined,
        api_key: apiKey || undefined,
        model: model || undefined,
        embedding_model: embeddingModel,
        allowed_models: allowedModelsStr
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
      },
      {
        onSuccess: () => {
          toast.success('全局 LLM 配置已更新')
          setApiKey('')
        },
        onError: () => toast.error('保存失败'),
      },
    )
  }

  return (
    <PageShell>
      <PageHeader title="LLM 配置" description="全局 Key 与默认模型" />
      <div className="py-6">
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

            <Button onClick={handleSave} disabled={saveLLM.isPending}>
              {saveLLM.isPending ? '保存中...' : '保存'}
            </Button>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  )
}
