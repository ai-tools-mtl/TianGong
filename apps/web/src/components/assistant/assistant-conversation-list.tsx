'use client'

import { Loader2, MessageSquare, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

interface AssistantConversationListProps {
  conversations: { id: string; title: string; updated_at: string }[]
  currentId: string | null
  loading: boolean
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}

export function AssistantConversationList({
  conversations, currentId, loading, onSelect, onNew, onDelete,
}: AssistantConversationListProps) {
  return (
    <div className="flex h-full w-64 shrink-0 flex-col border-r bg-muted/30">
      <div className="p-2">
        <Button variant="outline" size="sm" className="w-full justify-start gap-1.5" onClick={onNew}>
          <Plus className="size-3.5" /> 新对话
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className="space-y-0.5 p-2">
          {loading ? (
            <div className="flex justify-center p-4">
              <Loader2 className="size-4 animate-spin text-muted-foreground" />
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-2 py-4 text-center text-xs text-muted-foreground">暂无对话</p>
          ) : (
            conversations.map((c) => (
              <div
                key={c.id}
                className={cn(
                  'group flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[13px]',
                  c.id === currentId ? 'bg-background font-medium' : 'hover:bg-background/60',
                )}
                onClick={() => onSelect(c.id)}
              >
                <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="flex-1 truncate">{c.title || '新对话'}</span>
                <button
                  type="button"
                  className="shrink-0 text-muted-foreground opacity-0 hover:text-destructive group-hover:opacity-100"
                  onClick={(e) => { e.stopPropagation(); onDelete(c.id) }}
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
