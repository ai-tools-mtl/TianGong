'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Wrench } from 'lucide-react'
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
  clearChatDefaultSource,
  getChatDefaultSource,
  isChatGlobalDefault,
  setChatDefaultSource,
  setChatGlobalDefault,
} from '@/lib/llm-source'
import type {
  MyGrant,
  UserLLMConfig,
  UserLLMConfigUpdate,
} from '@/types/api'

export default function SettingsPage() {
  const qc = useQueryClient()
  // chat 编辑/删除态。editingChatId: null=无；'new'=新增面板展开；uuid=编辑某条
  const [editingChatId, setEditingChatId] = useState<string | null>(null)
  const [deletingChat, setDeletingChat] = useState<UserLLMConfig | null>(null)
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
  const currentChatDefault = getChatDefaultSource()

  const invalidateChat = () => qc.invalidateQueries({ queryKey: ['my-llm'] })

  // ── chat mutations ──
  const createChatMut = useMutation({
    mutationFn: (d: {
      name: string
      base_url: string
      api_key: string
      model: string
    }) => api.createMyLLM(d),
    onSuccess: () => {
      invalidateChat()
      toast.success('配置已添加')
      setEditingChatId(null)
    },
    onError: () => toast.error('添加失败'),
  })
  const updateChatMut = useMutation({
    mutationFn: ({ id, d }: { id: string; d: UserLLMConfigUpdate }) => api.updateMyLLM(id, d),
    onSuccess: () => {
      invalidateChat()
      toast.success('配置已更新')
      setEditingChatId(null)
    },
    onError: () => toast.error('更新失败'),
  })
  const deleteChatMut = useMutation({
    mutationFn: (id: string) => api.deleteMyLLM(id),
    onSuccess: () => {
      invalidateChat()
      toast.success('配置已删除')
      if (deletingChat && getChatDefaultSource() === `custom-chat:${deletingChat.id}`) clearChatDefaultSource()
      setDeletingChat(null)
      refreshDefault()
    },
    onError: () => toast.error('删除失败'),
  })

  return (
    <PageShell width="narrow">
      <PageHeader title="LLM 配置" description="管理你的自定义对话模型配置，选择默认来源" />

      <div className="space-y-8 py-6">
        {/* ── 对话模型配置 ── */}
        <section className="space-y-4">
          <div className="flex items-center justify-between px-1">
            <h2 className="text-[15px] font-semibold">对话模型配置</h2>
            <Button size="sm" onClick={() => setEditingChatId('new')}>+ 添加配置</Button>
          </div>

          {/* chat 全局 Key toggle（仅被授权时显示） */}
          {grantActive && (
            <div
              className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
              style={{ boxShadow: 'var(--shadow-card)' }}
            >
              <div>
                <p className="text-[13px] font-medium">使用全局 Key 作为对话默认</p>
                <p className="text-[12px] text-muted-foreground">你已被授权使用管理员配置的全局 Key</p>
              </div>
              <Switch
                checked={isChatGlobalDefault()}
                onCheckedChange={(v) => {
                  setChatGlobalDefault(v)
                  refreshDefault()
                }}
              />
            </div>
          )}

          {/* chat 配置列表（unified panel） */}
          <div
            className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
            style={{ boxShadow: 'var(--shadow-card)' }}
          >
            {configs.length === 0 && editingChatId !== 'new' && (
              <p className="px-5 py-10 text-center text-[13px] text-muted-foreground">
                暂无配置，点击右上角「+ 添加配置」开始
              </p>
            )}

            {configs.map((c) => (
              <div key={c.id}>
                <LLMConfigRow
                  config={c}
                  isDefault={currentChatDefault === `custom-chat:${c.id}`}
                  isEditing={editingChatId === c.id}
                  onSetDefault={() => {
                    setChatDefaultSource(`custom-chat:${c.id}`)
                    refreshDefault()
                  }}
                  onEdit={() => setEditingChatId(c.id)}
                  onDelete={() => setDeletingChat(c)}
                />
                {editingChatId === c.id && (
                  <LLMConfigEditPanel
                    initial={{
                      name: c.name,
                      base_url: c.base_url,
                      api_key_masked: c.api_key_masked,
                      model: c.model,
                    }}
                    onCancel={() => setEditingChatId(null)}
                    onSave={async (d) => {
                      await updateChatMut.mutateAsync({
                        id: c.id,
                        d: {
                          name: d.name,
                          base_url: d.base_url,
                          api_key: d.api_key || undefined, // 留空不传=不改
                          model: d.model,
                        },
                      })
                    }}
                  />
                )}
              </div>
            ))}

            {/* chat 新增面板（追加在列表底部） */}
            {editingChatId === 'new' && (
              <LLMConfigEditPanel
                initial={null}
                onCancel={() => setEditingChatId(null)}
                onSave={async (d) => {
                  await createChatMut.mutateAsync({
                    name: d.name,
                    base_url: d.base_url,
                    api_key: d.api_key,
                    model: d.model,
                  })
                }}
              />
            )}
          </div>
        </section>

        {/* 嵌入模型：统一走 bge-m3 微服务，无需用户配置 */}

        {/* 我的技能 — 入口卡片（普通用户从此进入技能管理） */}
        <Link
          href="/settings/skills"
          className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card p-5 transition-colors hover:bg-black/[0.02] dark:border-white/10 dark:hover:bg-white/[0.03]"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-xl bg-black/[0.04] dark:bg-white/[0.06]">
              <Wrench className="size-[18px]" />
            </div>
            <div>
              <p className="text-[15px] font-medium">我的技能</p>
              <p className="text-[12px] text-muted-foreground">
                管理 Agent Skills（SKILL.md），支持导入 zip
              </p>
            </div>
          </div>
          <ChevronRight className="size-[18px] text-muted-foreground" />
        </Link>
      </div>

      {/* chat 删除确认（项目无通用 ConfirmDialog，用 Dialog 手写——与 delete-confirm-dialog.tsx 同构） */}
      {deletingChat && (
        <Dialog open onOpenChange={(o) => !o && setDeletingChat(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认删除</DialogTitle>
              <DialogDescription>
                确认删除配置「{deletingChat.name}」？此操作不可恢复。若它是当前默认，删除后需重新选择默认来源。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeletingChat(null)}>取消</Button>
              <Button
                variant="destructive"
                disabled={deleteChatMut.isPending}
                onClick={() => deleteChatMut.mutate(deletingChat.id)}
              >
                {deleteChatMut.isPending ? '删除中…' : '确认删除'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </PageShell>
  )
}
