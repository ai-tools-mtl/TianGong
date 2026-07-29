'use client'

import { useState } from 'react'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { MemoryCard } from '@/components/memory-card'
import { useCreateMemory, useMemories } from '@/lib/queries'
import type { Memory } from '@/types/api'

type Filter = 'all' | 'agent' | 'manual'

export default function MemoriesPage() {
  const [filter, setFilter] = useState<Filter>('all')
  const [draft, setDraft] = useState('')

  const query = useMemories(filter === 'all' ? undefined : filter)
  const createMut = useCreateMemory()

  const onAdd = () => {
    if (!draft.trim()) {
      toast.error('内容不能为空')
      return
    }
    createMut.mutate(
      { content: draft, source: 'manual' },
      {
        onSuccess: () => {
          toast.success('已添加')
          setDraft('')
        },
        onError: () => toast.error('添加失败'),
      },
    )
  }

  const memories: Memory[] = query.data ?? []

  return (
    <PageShell>
      <PageHeader
        title="我的记忆"
        description="Agent 会记住你告诉它的偏好和约定。你也可以在这里手动管理。"
      />

      {/* 新建区 */}
      <div className="my-6 rounded-2xl border border-black/[0.07] bg-card p-4 dark:border-white/10"
           style={{ boxShadow: 'var(--shadow-card)' }}>
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="添加一条记忆，例如「我偏好简洁的写作风格」"
          rows={2}
          maxLength={500}
        />
        <div className="mt-2 flex justify-end">
          <Button onClick={onAdd} disabled={createMut.isPending || !draft.trim()}>
            <Plus className="mr-1 size-4" /> 添加记忆
          </Button>
        </div>
      </div>

      {/* 筛选 Tab */}
      <div className="mb-4 flex gap-2">
        {(['all', 'agent', 'manual'] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1 text-sm transition-colors ${
              filter === f
                ? 'bg-foreground text-background'
                : 'bg-black/[0.04] text-muted-foreground hover:bg-black/[0.08] dark:bg-white/[0.06]'
            }`}
          >
            {f === 'all' ? '全部' : f === 'agent' ? 'AI 记录' : '手动添加'}
          </button>
        ))}
      </div>

      {/* 记忆列表 */}
      {query.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : memories.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          还没有记忆。和 Agent 对话时它会自动学习，或手动添加一条。
        </p>
      ) : (
        <div className="space-y-3">
          {memories.map((m) => (
            <MemoryCard key={m.id} memory={m} />
          ))}
        </div>
      )}
    </PageShell>
  )
}
