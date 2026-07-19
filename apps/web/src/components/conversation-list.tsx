'use client'

import { ChevronDown, ChevronUp, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { formatConversationTime, groupConversations } from '@/lib/conversation-grouping'
import { cn } from '@/lib/utils'
import type { Conversation } from '@/types/api'

interface ConversationListProps {
  conversations: Conversation[]
  currentConvId: string | null
  loading: boolean
  createPending: boolean
  deletePending: boolean
  onSelect: (convId: string) => void
  onNew: () => void
  onDelete: (convId: string) => void
}

export function ConversationList({
  conversations,
  currentConvId,
  loading,
  createPending,
  deletePending,
  onSelect,
  onNew,
  onDelete,
}: ConversationListProps) {
  // 折叠态：默认折叠（浮层模式，不自动展开）。点击标题行才展开浮层。
  const [expanded, setExpanded] = useState(false)
  const groups = groupConversations(conversations)
  const current = conversations.find((c) => c.id === currentConvId)
  const hasConvs = conversations.length > 0

  const handleSelect = (convId: string) => {
    onSelect(convId)
    // 选中后自动收起浮层（回到聊天）
    setExpanded(false)
  }

  // 根容器 relative：让浮层 absolute 锚定在标题行下方
  return (
    <div className="relative shrink-0">
      {/* 标题行（始终占位 h-8，不挤压聊天区） */}
      <div className="flex h-8 items-center gap-1 border-b bg-muted/30 px-2">
        <button
          type="button"
          onClick={() => hasConvs && setExpanded((e) => !e)}
          disabled={loading || !hasConvs}
          className="flex h-6 flex-1 items-center gap-1 truncate rounded px-1 text-left text-[12px] outline-none hover:bg-muted disabled:cursor-default disabled:hover:bg-transparent"
          title={current?.title ?? '新会话'}
        >
          {loading ? (
            <span className="text-muted-foreground">加载中...</span>
          ) : hasConvs ? (
            <>
              <span className="flex-1 truncate">{current?.title ?? '选择会话'}</span>
              {expanded ? (
                <ChevronUp className="size-3 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
              )}
            </>
          ) : (
            <span className="text-muted-foreground">新会话</span>
          )}
        </button>
        <Button
          variant="ghost"
          size="icon-xs"
          onClick={onNew}
          disabled={createPending}
          title="新建会话"
        >
          <Plus className="size-3.5" />
        </Button>
      </div>

      {/* 浮层：absolute 锚定标题行下方，覆盖聊天区，不挤压文档流 */}
      {expanded && hasConvs && (
        <div className="absolute left-0 right-0 top-full z-30 max-h-80 overflow-y-auto border-b border-x bg-background py-1 shadow-lg">
          {groups.map((g) => (
            <div key={g.key}>
              <div className="sticky top-0 z-10 bg-background px-3 py-1 text-[11px] font-medium text-muted-foreground">
                {g.label}
              </div>
              {g.items.map((c) => {
                const selected = c.id === currentConvId
                return (
                  <div
                    key={c.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => handleSelect(c.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        handleSelect(c.id)
                      }
                    }}
                    className={cn(
                      'group flex h-8 items-center gap-2 px-3 hover:bg-muted cursor-pointer',
                      selected && 'bg-primary/10',
                    )}
                  >
                    <span className={cn('size-1.5 shrink-0 rounded-full', selected ? 'bg-primary' : '')} />
                    {c.status === 'draft' ? (
                      <span className="flex flex-1 items-center gap-1 truncate text-[12px] italic text-muted-foreground">
                        <Sparkles className="size-3 shrink-0 text-ai" />
                        <span className="truncate">{c.title}</span>
                      </span>
                    ) : (
                      <span className="flex-1 truncate text-[12px]">{c.title}</span>
                    )}
                    <span className="text-[11px] tabular-nums text-muted-foreground">
                      {formatConversationTime(c.updated_at)}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      onClick={(e) => {
                        e.stopPropagation()
                        onDelete(c.id)
                      }}
                      disabled={deletePending}
                      title="删除会话"
                      className="text-muted-foreground opacity-0 hover:text-destructive group-hover:opacity-100"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
