'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { LLMConfigRow } from '@/components/llm-config/LLMConfigRow'
import { LLMConfigEditPanel } from '@/components/llm-config/LLMConfigEditPanel'
import { api } from '@/lib/api'
import {
  clearDefaultSource,
  getDefaultSource,
  isGlobalDefault,
  setDefaultSource,
  setGlobalDefault,
} from '@/lib/llm-source'
import type { MyGrant, UserLLMConfig, UserLLMConfigUpdate } from '@/types/api'

export default function SettingsPage() {
  const qc = useQueryClient()
  // editingId: null=无；'new'=新增面板展开；uuid=编辑某条
  const [editingId, setEditingId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<UserLLMConfig | null>(null)
  // 强制重渲染用（localStorage 的默认 source 变化后，调一下让 isDefault 重算）
  const [, setDefaultTick] = useState(0)
  const refreshDefault = () => setDefaultTick((t) => t + 1)

  const configsQuery = useQuery<UserLLMConfig[]>({
    queryKey: ['my-llm'],
    queryFn: api.listMyLLM,
  })
  const grantQuery = useQuery<MyGrant>({
    queryKey: ['my-grant'],
    queryFn: api.getMyGrant,
  })

  const configs: UserLLMConfig[] = configsQuery.data ?? []
  const grantActive = !!grantQuery.data?.is_active
  const currentDefault = getDefaultSource()

  const invalidate = () => qc.invalidateQueries({ queryKey: ['my-llm'] })

  const createMut = useMutation({
    mutationFn: (d: {
      name: string
      base_url: string
      api_key: string
      model: string
      embedding_model: string | null
    }) => api.createMyLLM(d),
    onSuccess: () => {
      invalidate()
      toast.success('配置已添加')
      setEditingId(null)
    },
    onError: () => toast.error('添加失败'),
  })
  const updateMut = useMutation({
    mutationFn: ({ id, d }: { id: string; d: UserLLMConfigUpdate }) => api.updateMyLLM(id, d),
    onSuccess: () => {
      invalidate()
      toast.success('配置已更新')
      setEditingId(null)
    },
    onError: () => toast.error('更新失败'),
  })
  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteMyLLM(id),
    onSuccess: () => {
      invalidate()
      toast.success('配置已删除')
      if (deleting && getDefaultSource() === `custom:${deleting.id}`) clearDefaultSource()
      setDeleting(null)
      refreshDefault()
    },
    onError: () => toast.error('删除失败'),
  })

  return (
    <PageShell width="narrow">
      <PageHeader title="LLM 配置" description="管理你的自定义 LLM 配置，选择默认使用的来源">
        <Button size="sm" onClick={() => setEditingId('new')}>+ 添加配置</Button>
      </PageHeader>

      <div className="space-y-6 py-6">
        {/* 全局 Key toggle（仅被授权时显示） */}
        {grantActive && (
          <div
            className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
            style={{ boxShadow: 'var(--shadow-card)' }}
          >
            <div>
              <p className="text-[13px] font-medium">使用全局 Key 作为默认</p>
              <p className="text-[12px] text-muted-foreground">你已被授权使用管理员配置的全局 Key</p>
            </div>
            <Switch
              checked={isGlobalDefault()}
              onCheckedChange={(v) => {
                setGlobalDefault(v)
                refreshDefault()
              }}
            />
          </div>
        )}

        {/* 配置列表（unified panel） */}
        <div
          className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          {configs.length === 0 && editingId !== 'new' && (
            <p className="px-5 py-10 text-center text-[13px] text-muted-foreground">
              暂无配置，点击右上角「+ 添加配置」开始
            </p>
          )}

          {configs.map((c) => (
            <div key={c.id}>
              <LLMConfigRow
                config={c}
                isDefault={currentDefault === `custom:${c.id}`}
                isEditing={editingId === c.id}
                onSetDefault={() => {
                  setDefaultSource(`custom:${c.id}`)
                  refreshDefault()
                }}
                onEdit={() => setEditingId(c.id)}
                onDelete={() => setDeleting(c)}
              />
              {editingId === c.id && (
                <LLMConfigEditPanel
                  initial={{
                    name: c.name,
                    base_url: c.base_url,
                    api_key_masked: c.api_key_masked,
                    model: c.model,
                    embedding_model: c.embedding_model,
                  }}
                  onCancel={() => setEditingId(null)}
                  onSave={async (d) => {
                    await updateMut.mutateAsync({
                      id: c.id,
                      d: {
                        name: d.name,
                        base_url: d.base_url,
                        api_key: d.api_key || undefined, // 留空不传=不改
                        model: d.model,
                        embedding_model: d.embedding_model,
                      },
                    })
                  }}
                />
              )}
            </div>
          ))}

          {/* 新增面板（追加在列表底部） */}
          {editingId === 'new' && (
            <LLMConfigEditPanel
              initial={null}
              onCancel={() => setEditingId(null)}
              onSave={async (d) => {
                await createMut.mutateAsync({
                  name: d.name,
                  base_url: d.base_url,
                  api_key: d.api_key,
                  model: d.model,
                  embedding_model: d.embedding_model,
                })
              }}
            />
          )}
        </div>
      </div>

      {/* 删除确认（项目无通用 ConfirmDialog，用 Dialog 手写——与 delete-confirm-dialog.tsx 同构） */}
      {deleting && (
        <Dialog open onOpenChange={(o) => !o && setDeleting(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认删除</DialogTitle>
              <DialogDescription>
                确认删除配置「{deleting.name}」？此操作不可恢复。若它是当前默认，删除后需重新选择默认来源。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleting(null)}>取消</Button>
              <Button
                variant="destructive"
                disabled={deleteMut.isPending}
                onClick={() => deleteMut.mutate(deleting.id)}
              >
                {deleteMut.isPending ? '删除中…' : '确认删除'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </PageShell>
  )
}
