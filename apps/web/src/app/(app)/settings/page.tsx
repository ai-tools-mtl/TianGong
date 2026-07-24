'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Plus, Wrench } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SectionLabel } from '@/components/ui/section-label'
import { api } from '@/lib/api'
import { clearDefaultSource, getDefaultSource, setDefaultSource } from '@/lib/llm-source'
import { cn } from '@/lib/utils'
import type { UserLLMConfig } from '@/types/api'

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data: configs = [], isLoading: configsLoading } = useQuery<UserLLMConfig[]>({
    queryKey: ['my-llm'],
    queryFn: () => api.listMyLLM(),
  })
  const { data: myGrant, isLoading: grantLoading } = useQuery({ queryKey: ['my-grant'], queryFn: () => api.getMyGrant() })

  // ── 选源器 ──
  // 初始化默认 source；若失效（配置被删/授权撤销）则清空提示重选。
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [sourceInitialized, setSourceInitialized] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)

  useEffect(() => {
    const saved = getDefaultSource()
    if (!saved) {
      setSelectedSource(null)
      setSourceInitialized(true)
      return
    }
    // 等待相关数据加载完成后再校验，避免把"加载中"误判为"已失效"
    // （强制刷新时 myGrant/configs 首次为 undefined/[]，不等待会清掉有效值）
    if (saved === 'global' && grantLoading) return
    if (saved.startsWith('custom:') && configsLoading) return
    // 校验 saved 是否仍有效
    if (saved === 'global') {
      // global 选项仅在授权时可见；未授权则失效
      if (!myGrant?.is_active) {
        clearDefaultSource()
        setSelectedSource(null)
        toast.info('全局 Key 授权已失效，请重新选择 LLM 源')
      } else {
        setSelectedSource(saved)
      }
    } else if (saved.startsWith('custom:')) {
      const configId = saved.slice(7)
      const exists = configs.some((c: UserLLMConfig) => c.id === configId)
      if (!exists) {
        clearDefaultSource()
        setSelectedSource(null)
        toast.info('所选自定义配置已被删除，请重新选择 LLM 源')
      } else {
        setSelectedSource(saved)
      }
    } else {
      // 未知格式，清空
      clearDefaultSource()
      setSelectedSource(null)
    }
    setSourceInitialized(true)
  }, [configs, myGrant, configsLoading, grantLoading])

  function handleSelectSource(source: string) {
    setSelectedSource(source)
    setDefaultSource(source)
    toast.success('已设为默认 LLM 源')
  }

  return (
    <PageShell width="narrow">
      <PageHeader title="设置" description="管理你的 LLM 接入">
        <Button onClick={() => setCreateOpen(true)} className="gap-1.5">
          <Plus className="size-3.5" />
          添加配置
        </Button>
      </PageHeader>

      <div className="space-y-6 py-6">
        {/* 选源器 */}
        <SourceSelector
          configs={configs}
          grantActive={!!myGrant?.is_active}
          selectedSource={sourceInitialized ? selectedSource : null}
          onSelect={handleSelectSource}
        />

        {/* 配置列表 */}
        <ConfigList configs={configs} />

        {/* 我的技能 — 入口卡片（普通用户从此进入技能管理） */}
        <Link
          href="/settings/skills"
          className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card p-5 transition-colors hover:bg-black/[0.02] dark:border-white/10 dark:hover:bg-white/[0.03]"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-xl bg-black/[0.04] dark:bg-white/[0.06]">
              <Wrench className="size-4.5" />
            </div>
            <div>
              <p className="text-[15px] font-medium">我的技能</p>
              <p className="text-[12px] text-muted-foreground">
                管理 Agent Skills（SKILL.md），支持导入 zip
              </p>
            </div>
          </div>
          <ChevronRight className="size-4.5 text-muted-foreground" />
        </Link>
      </div>

      {/* 新增配置 — Dialog（按需触发，和系统其他创建操作一致） */}
      <CreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => qc.invalidateQueries({ queryKey: ['my-llm'] })}
      />
    </PageShell>
  )
}

// ── 选源器 ───────────────────────────────────────────────

interface SourceSelectorProps {
  configs: UserLLMConfig[]
  grantActive: boolean
  selectedSource: string | null
  onSelect: (source: string) => void
}

function SourceSelector({ configs, grantActive, selectedSource, onSelect }: SourceSelectorProps) {
  const hasAnyOption = grantActive || configs.length > 0

  return (
    <div className="space-y-3">
      <SectionLabel size="md">默认 LLM 源</SectionLabel>
      {!hasAnyOption ? (
        <EmptyState description="暂无可选项。点击右上角「添加配置」新增，或联系管理员授权全局 Key。" />
      ) : (
        <>
          <div
            className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
            style={{ boxShadow: 'var(--shadow-card)' }}
          >
            {grantActive && (
              <SourceOption
                value="global"
                label="全局 Key"
                description="使用管理员配置的全局 Key（需被授权）"
                selected={selectedSource === 'global'}
                onSelect={onSelect}
              />
            )}
            {configs.map((c) => (
              <SourceOption
                key={c.id}
                value={`custom:${c.id}`}
                label={c.name}
                description={`${c.model} · ${c.api_key_masked}`}
                selected={selectedSource === `custom:${c.id}`}
                onSelect={onSelect}
              />
            ))}
          </div>
          {selectedSource === null && (
            <p className="px-1 text-[12px] text-warning">
              尚未选择默认源，AI 助手将无法调用。请选择一项。
            </p>
          )}
        </>
      )}
    </div>
  )
}

interface SourceOptionProps {
  value: string
  label: string
  description: string
  selected: boolean
  onSelect: (value: string) => void
}

function SourceOption({ value, label, description, selected, onSelect }: SourceOptionProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(value)}
      className={cn(
        'flex w-full items-center gap-3 border-t border-black/[0.07] px-4 py-3 text-left transition-colors first:border-t-0 dark:border-white/10',
        selected ? 'bg-accent' : 'hover:bg-muted/50',
      )}
    >
      <span
        className={cn(
          'flex size-4 shrink-0 items-center justify-center rounded-full border',
          selected ? 'border-primary' : 'border-muted-foreground/40',
        )}
      >
        {selected && <span className="size-2 rounded-full bg-primary" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{label}</span>
        <span className="block truncate text-[12px] text-muted-foreground">{description}</span>
      </span>
    </button>
  )
}

// ── 配置列表 ─────────────────────────────────────────────

interface ConfigListProps {
  configs: UserLLMConfig[]
}

function ConfigList({ configs }: ConfigListProps) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<UserLLMConfig | null>(null)

  const invalidate = () => qc.invalidateQueries({ queryKey: ['my-llm'] })

  const deleteMutation = useMutation({
    mutationFn: (configId: string) => api.deleteMyLLM(configId),
    onSuccess: () => {
      toast.success('配置已删除')
      invalidate()
      // 删除的若是默认源，清掉（外层 useEffect 会兜底校正，这里即时清更稳）
      const saved = getDefaultSource()
      if (saved && saved === `custom:${editing?.id}`) clearDefaultSource()
    },
    onError: () => toast.error('删除失败'),
  })

  if (configs.length === 0) {
    return (
      <div className="space-y-3">
        <SectionLabel size="md">我的自定义配置</SectionLabel>
        <EmptyState description="暂无配置，点击右上角「添加配置」开始" />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <SectionLabel size="md">我的自定义配置（{configs.length}）</SectionLabel>
      <div
        className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
        style={{ boxShadow: 'var(--shadow-card)' }}
      >
        {configs.map((c) => (
          <div
            key={c.id}
            className="flex items-center justify-between gap-3 border-t border-black/[0.07] px-4 py-3 transition-colors first:border-t-0 hover:bg-muted/40 dark:border-white/10"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium">{c.name}</p>
              <p className="truncate text-[12px] text-muted-foreground">
                {c.model} · {c.api_key_masked}
              </p>
              {c.embedding_model && (
                <p className="truncate text-[11px] text-muted-foreground">
                  embed: {c.embedding_model}
                </p>
              )}
            </div>
            <div className="flex shrink-0 gap-1">
              <Button size="xs" variant="outline" onClick={() => setEditing(c)}>
                编辑
              </Button>
              <Button
                size="xs"
                variant="ghost"
                className="text-destructive hover:text-destructive"
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(c.id)}
              >
                删除
              </Button>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <EditDialog
          config={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            invalidate()
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}

// ── 新增配置弹窗 ─────────────────────────────────────────

interface CreateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
}

function CreateDialog({ open, onOpenChange, onCreated }: CreateDialogProps) {
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [embeddingModel, setEmbeddingModel] = useState('')

  const createMutation = useMutation({
    mutationFn: () =>
      api.createMyLLM({
        name: name.trim(),
        base_url: baseUrl.trim(),
        api_key: apiKey,
        model: model.trim(),
        embedding_model: embeddingModel.trim() || null,
      }),
    onSuccess: () => {
      toast.success('配置已添加')
      onCreated()
      onOpenChange(false)
      setName('')
      setBaseUrl('')
      setApiKey('')
      setModel('')
      setEmbeddingModel('')
    },
    onError: () => toast.error('保存失败'),
  })

  const [testing, setTesting] = useState(false)

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

  const canSubmit = !!name.trim() && !!baseUrl.trim() && !!apiKey && !!model.trim()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加 LLM 配置</DialogTitle>
          <DialogDescription>
            支持 OpenAI 兼容 Provider（智谱 GLM / OpenAI / DeepSeek / 本地 Ollama 等）。Key 加密存储，不明文返回。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="name">配置名</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：公司Key"
            />
          </div>
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
              placeholder="输入你的 API Key"
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
          <div className="space-y-2">
            <Label htmlFor="embeddingModel">Embedding 模型（可选）</Label>
            <Input
              id="embeddingModel"
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
              placeholder="embedding-3"
            />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={handleTest} variant="outline" disabled={testing || !apiKey || !baseUrl}>
            {testing ? '测试中...' : '测试连通'}
          </Button>
          <Button
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending || !canSubmit}
          >
            {createMutation.isPending ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── 编辑弹窗 ─────────────────────────────────────────────

interface EditDialogProps {
  config: UserLLMConfig
  onClose: () => void
  onSaved: () => void
}

function EditDialog({ config, onClose, onSaved }: EditDialogProps) {
  const [name, setName] = useState(config.name)
  const [baseUrl, setBaseUrl] = useState(config.base_url)
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(config.model)
  const [embeddingModel, setEmbeddingModel] = useState(config.embedding_model ?? '')

  const updateMutation = useMutation({
    mutationFn: () =>
      api.updateMyLLM(config.id, {
        name: name.trim(),
        base_url: baseUrl.trim(),
        api_key: apiKey || undefined, // 留空则不变
        model: model.trim(),
        embedding_model: embeddingModel.trim() || null,
      }),
    onSuccess: () => {
      toast.success('配置已更新')
      onSaved()
    },
    onError: () => toast.error('更新失败'),
  })

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>编辑配置</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label>配置名</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>API Base URL</Label>
            <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>API Key</Label>
            <Input
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={config.api_key_masked}
              type="password"
            />
            <p className="text-[11px] text-muted-foreground">留空则保持原 Key 不变。</p>
          </div>
          <div className="space-y-2">
            <Label>模型名</Label>
            <Input value={model} onChange={(e) => setModel(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Embedding 模型（可选）</Label>
            <Input
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
              placeholder="留空清除"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            onClick={() => updateMutation.mutate()}
            disabled={updateMutation.isPending || !name.trim() || !baseUrl.trim() || !model.trim()}
          >
            {updateMutation.isPending ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
