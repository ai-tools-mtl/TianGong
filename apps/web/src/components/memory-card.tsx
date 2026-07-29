'use client'

import { useState } from 'react'
import { Check, Pencil, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useDeleteMemory, useUpdateMemory } from '@/lib/queries'
import type { Memory } from '@/types/api'

export function MemoryCard({ memory }: { memory: Memory }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(memory.content)

  const updateMut = useUpdateMemory(memory.id)
  const deleteMut = useDeleteMemory()

  const onSave = () => {
    if (!draft.trim()) {
      toast.error('内容不能为空')
      return
    }
    updateMut.mutate(draft, {
      onSuccess: () => {
        toast.success('已更新')
        setEditing(false)
      },
      onError: () => toast.error('更新失败'),
    })
  }

  const onDelete = () => {
    if (!confirm('确定删除这条记忆？')) return
    deleteMut.mutate(memory.id, {
      onSuccess: () => toast.success('已删除'),
      onError: () => toast.error('删除失败'),
    })
  }

  return (
    <div className="rounded-2xl border border-black/[0.07] bg-card p-4 dark:border-white/10"
         style={{ boxShadow: 'var(--shadow-card)' }}>
      <div className="mb-2 flex items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[11px] ${
          memory.source === 'agent'
            ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400'
            : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
        }`}>
          {memory.source === 'agent' ? 'AI 记录' : '手动添加'}
        </span>
        <span className="text-[11px] text-muted-foreground">
          {memory.updated_at ? new Date(memory.updated_at).toLocaleDateString() : ''}
        </span>
      </div>

      {editing ? (
        <div className="space-y-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            maxLength={500}
          />
          <div className="flex gap-2">
            <Button size="sm" onClick={onSave} disabled={updateMut.isPending}>
              <Check className="mr-1 size-3.5" /> 保存
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setDraft(memory.content) }}>
              <X className="mr-1 size-3.5" /> 取消
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-start justify-between gap-3">
          <p className="text-sm leading-relaxed">{memory.content}</p>
          <div className="flex shrink-0 gap-1">
            <Button size="icon" variant="ghost" className="size-7" aria-label="编辑"
                    onClick={() => { setDraft(memory.content); setEditing(true) }}>
              <Pencil className="size-3.5" />
            </Button>
            <Button size="icon" variant="ghost" className="size-7" aria-label="删除"
                    onClick={onDelete} disabled={deleteMut.isPending}>
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
