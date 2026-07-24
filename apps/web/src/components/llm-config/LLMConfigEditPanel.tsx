'use client'

import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ModelSelectInput } from './ModelSelectInput'
import { ProviderTemplatePicker } from './ProviderTemplatePicker'
import { TestResultBadge } from './TestResultBadge'
import {
  useListProviderModels, useProviderTemplates, useTestLLMConnection,
} from '@/lib/queries'
import type { ProviderTemplate, TestConnectionResult } from '@/types/api'

export interface LLMConfigEditPanelProps {
  /** 初始值（编辑模式传入；新增模式传 null/undefined）。 */
  initial?: {
    name?: string
    base_url?: string
    api_key_masked?: string
    model?: string
    embedding_model?: string | null
    provider_template_id?: string | null
  } | null
  /** 保存回调。返回 Promise。apiKey 留空串 = 不改。 */
  onSave: (data: {
    name: string
    base_url: string
    api_key: string            // 留空 = 不改（由调用方判断）
    model: string
    embedding_model: string | null
    provider_template_id?: string | null
    allowed_models?: string    // admin 模式下逗号分隔的白名单字符串
  }) => Promise<void>
  onCancel: () => void
  /** admin 模式：额外渲染 allowed_models 编辑框。 */
  adminMode?: boolean
  initialAllowedModels?: string[]
  saveLabel?: string
}

export function LLMConfigEditPanel({
  initial, onSave, onCancel, adminMode, initialAllowedModels, saveLabel = '保存',
}: LLMConfigEditPanelProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')   // 始终空起步；留空=不改（编辑）或必填（新增由调用方校验）
  const [model, setModel] = useState(initial?.model ?? '')
  const [embeddingModel, setEmbeddingModel] = useState(initial?.embedding_model ?? '')
  const [selectedTplId, setSelectedTplId] = useState<string | null>(initial?.provider_template_id ?? null)
  const [showKey, setShowKey] = useState(false)
  const [allowedModelsStr, setAllowedModelsStr] = useState(
    (initialAllowedModels ?? []).join(', '),
  )

  // 拉取的模型列表（本地 state，不持久化）
  const [chatModels, setChatModels] = useState<string[]>([])
  const [embedModels, setEmbedModels] = useState<string[]>([])

  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null)
  const [saving, setSaving] = useState(false)

  const listModels = useListProviderModels()
  const testConn = useTestLLMConnection()

  function pickTemplate(t: ProviderTemplate) {
    setSelectedTplId(t.id)
    // 自动填（仅在字段为空时填，避免覆盖用户已输入）
    if (!baseUrl) setBaseUrl(t.base_url)
    if (!model) setModel(t.default_model)
    if (!embeddingModel && t.default_embedding_model) setEmbeddingModel(t.default_embedding_model)
  }

  async function handleFetchModels(target: 'chat' | 'embed') {
    if (!baseUrl || !apiKey) {
      toast.error('请先填写 Base URL 和 API Key')
      return
    }
    const res = await listModels.mutateAsync({
      base_url: baseUrl, api_key: apiKey, provider_template_id: selectedTplId ?? undefined,
    })
    if (res.error) {
      toast.error(`拉取失败：${res.error}`)
      return
    }
    if (target === 'chat') setChatModels(res.models)
    else setEmbedModels(res.models)
    toast.success(`已拉取 ${res.models.length} 个模型${res.truncated ? '（已截断前 100）' : ''}`)
  }

  async function handleTest() {
    if (!baseUrl || !model) {
      toast.error('请先填写 Base URL 和 对话模型')
      return
    }
    // 新增模式下 apiKey 必填；编辑模式下若留空则无法测（已存 Key 不回显明文）
    if (!apiKey && !initial?.api_key_masked) {
      toast.error('请填写 API Key')
      return
    }
    if (!apiKey && initial?.api_key_masked) {
      toast.error('编辑模式下测试需重新填写 API Key（已存 Key 不回显明文）')
      return
    }
    const res = await testConn.mutateAsync({
      base_url: baseUrl, api_key: apiKey, model,
      embedding_model: embeddingModel || null,
    })
    setTestResult(res)
  }

  async function handleSave() {
    if (!name.trim() || !baseUrl.trim() || !model.trim()) {
      toast.error('名称、Base URL、对话模型不能为空')
      return
    }
    // 新增模式 apiKey 必填
    if (!initial && !apiKey) {
      toast.error('请填写 API Key')
      return
    }
    setSaving(true)
    try {
      await onSave({
        name: name.trim(),
        base_url: baseUrl.trim(),
        api_key: apiKey,   // 留空=不改（编辑）或已校验非空（新增）
        model: model.trim(),
        embedding_model: embeddingModel.trim() || null,
        provider_template_id: selectedTplId,
        ...(adminMode ? { allowed_models: allowedModelsStr } : {}),
      })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      toast.error(`保存失败：${msg}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 bg-muted/20 p-5">
      {/* 模板 */}
      <div className="space-y-2">
        <Label className="text-[12px] text-muted-foreground">从模板开始（可选）</Label>
        <TemplateSection selectedId={selectedTplId} onPick={pickTemplate} />
      </div>

      {/* 名称 + base_url */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-[12px]">名称</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：公司主 Key" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-[12px]">API Base URL</Label>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://..." />
        </div>
      </div>

      {/* api_key */}
      <div className="space-y-1.5">
        <Label className="text-[12px]">
          API Key
          {initial?.api_key_masked && (
            <span className="ml-2 text-[11px] text-muted-foreground">
              当前：{initial.api_key_masked}（留空不修改）
            </span>
          )}
        </Label>
        <div className="relative">
          <Input
            type={showKey ? 'text' : 'password'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={initial?.api_key_masked ? '输入新 Key（留空不改）' : '输入 API Key'}
            className="pr-10 font-mono"
          />
          <button
            type="button"
            onClick={() => setShowKey((s) => !s)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showKey ? '隐藏' : '显示'}
          >
            {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </div>

      {/* 对话模型 + 拉取 */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="text-[12px]">对话模型</Label>
          <Button
            type="button" size="xs" variant="outline"
            disabled={listModels.isPending}
            onClick={() => handleFetchModels('chat')}
          >
            {listModels.isPending ? '拉取中…' : '⤓ 拉取模型'}
          </Button>
        </div>
        <ModelSelectInput
          value={model}
          onChange={setModel}
          options={chatModels}
          placeholder="如 glm-4-plus"
        />
      </div>

      {/* embedding 模型 + 拉取 */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="text-[12px]">嵌入模型（可选，知识库 RAG 用）</Label>
          <Button
            type="button" size="xs" variant="outline"
            disabled={listModels.isPending}
            onClick={() => handleFetchModels('embed')}
          >
            ⤓ 拉取
          </Button>
        </div>
        <ModelSelectInput
          value={embeddingModel}
          onChange={setEmbeddingModel}
          options={embedModels}
          placeholder="如 embedding-3（留空则不测）"
        />
      </div>

      {/* admin: allowed_models */}
      {adminMode && (
        <div className="space-y-1.5">
          <Label className="text-[12px]">允许的模型（逗号分隔，留空不限制）</Label>
          <Input
            value={allowedModelsStr}
            onChange={(e) => setAllowedModelsStr(e.target.value)}
            placeholder="glm-4-plus, glm-4-flash"
          />
          <p className="text-[11px] text-muted-foreground">保存时按英文逗号拆分为列表。</p>
        </div>
      )}

      {/* 测试结果 */}
      {testResult && <TestResultBadge result={testResult} />}

      {/* 操作 */}
      <div className="flex items-center justify-between border-t border-black/[0.07] pt-4 dark:border-white/10">
        <Button
          type="button" variant="outline" size="sm"
          disabled={testConn.isPending}
          onClick={handleTest}
        >
          {testConn.isPending ? '测试中…' : '↻ 测试连接'}
        </Button>
        <div className="flex gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>取消</Button>
          <Button type="button" size="sm" disabled={saving} onClick={handleSave}>
            {saving ? '保存中…' : saveLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}

// 模板区子组件（隔离 React Query 的加载态，避免主组件因模板加载重渲染影响表单输入）
function TemplateSection({
  selectedId, onPick,
}: {
  selectedId: string | null
  onPick: (t: ProviderTemplate) => void
}) {
  const { data: templates, isLoading } = useProviderTemplates()
  if (isLoading || !templates) return <p className="text-[11px] text-muted-foreground">加载模板…</p>
  return <ProviderTemplatePicker templates={templates} selectedId={selectedId} onSelect={onPick} />
}
