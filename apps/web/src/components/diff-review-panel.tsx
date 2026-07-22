'use client'

import { Check, CheckCheck, GitCompare, X, XCircle } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import type { Hunk, InlineDiffOp } from '@/types/api'

interface DiffReviewPanelProps {
  hunks: Hunk[]
  sectionTitle: string
  /** 应用被接受的 hunk（传入 accepted hunk id 列表） */
  onApply: (acceptedHunkIds: string[]) => Promise<void>
  onClose: () => void
  /** 应用按钮是否加载中（父组件控制） */
  applying?: boolean
}

type Decision = 'accept' | 'reject'

const HUNK_TYPE_LABEL: Record<Hunk['type'], string> = {
  replace: '替换',
  insert: '新增',
  delete: '删除',
}

/**
 * 渲染单个 replace hunk 的字符级 inline diff。
 * diff-match-patch 格式：op -1 删除（红删除线）/ 0 相等（默认）/ 1 插入（绿下划线）。
 */
function InlineDiffView({ ops }: { ops: InlineDiffOp[] }) {
  return (
    <div className="whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed">
      {ops.map(([op, text], i) => {
        if (op === -1) {
          return (
            <span key={i} className="bg-destructive/15 text-destructive line-through decoration-destructive/60">
              {text}
            </span>
          )
        }
        if (op === 1) {
          return (
            <span key={i} className="bg-success/15 text-success underline decoration-success/60 underline-offset-2">
              {text}
            </span>
          )
        }
        return <span key={i} className="text-muted-foreground">{text}</span>
      })}
    </div>
  )
}

/**
 * 渲染单个 insert/delete hunk 的整段文本。
 * insert：绿底 + 加号前缀；delete：红底 + 删除线 + 减号前缀。
 */
function BlockTextView({ text, kind }: { text: string; kind: 'insert' | 'delete' }) {
  return (
    <div
      className={cn(
        'whitespace-pre-wrap break-words rounded-lg border px-3 py-2 font-mono text-[13px] leading-relaxed',
        kind === 'insert'
          ? 'border-success/30 bg-success/10 text-success'
          : 'border-destructive/30 bg-destructive/10 text-destructive line-through decoration-destructive/40',
      )}
    >
      <span className="mr-1 font-bold">{kind === 'insert' ? '+' : '-'}</span>
      {text}
    </div>
  )
}

/**
 * Git-Diff 审查面板。
 *
 * - 每个 hunk 独立展示 + ✓接受 / ✗拒绝 按钮
 * - 状态：Record<hunkId, 'accept'|'reject'>，未决定默认视为拒绝（安全侧）
 * - 底部：全部接受 / 全部拒绝 / 应用 N 项更改（仅提交 accepted hunks）
 *
 * @see spec §4.3 审查 UI
 */
export function DiffReviewPanel({
  hunks,
  sectionTitle,
  onApply,
  onClose,
  applying = false,
}: DiffReviewPanelProps) {
  // 决策表：未出现的 key 视为未决定（默认拒绝）
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})

  const acceptedIds = useMemo(
    () => hunks.filter((h) => decisions[h.id] === 'accept').map((h) => h.id),
    [hunks, decisions],
  )

  function setHunk(id: string, d: Decision) {
    setDecisions((prev) => ({ ...prev, [id]: d }))
  }

  function acceptAll() {
    setDecisions(Object.fromEntries(hunks.map((h) => [h.id, 'accept'])))
  }

  function rejectAll() {
    setDecisions(Object.fromEntries(hunks.map((h) => [h.id, 'reject'])))
  }

  async function handleApply() {
    await onApply(acceptedIds)
  }

  return (
    <div className="flex h-full flex-col">
      {/* 头部 */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2">
          <GitCompare className="size-4 text-primary" />
          <h3 className="text-[15px] font-semibold tracking-tight">审查差异</h3>
          <span className="truncate text-[13px] text-muted-foreground">§{sectionTitle}</span>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="关闭">
          <X className="size-4" />
        </Button>
      </div>

      {/* hunk 列表 */}
      <ScrollArea className="flex-1">
        <div className="space-y-3 p-4">
          {hunks.length === 0 && (
            <div
              className="rounded-2xl border border-black/[0.07] bg-card px-4 py-8 text-center text-sm text-muted-foreground dark:border-white/10"
              style={{ boxShadow: 'var(--shadow-card)' }}
            >
              没有检测到变更
            </div>
          )}
          {hunks.map((hunk, idx) => {
            const decision = decisions[hunk.id]
            const decided = decision !== undefined
            return (
              <div
                key={hunk.id}
                className={cn(
                  'rounded-xl border bg-card transition-colors',
                  decision === 'accept' && 'border-success/50 ring-1 ring-success/20',
                  decision === 'reject' && 'border-destructive/50 opacity-70',
                )}
              >
                {/* hunk 头 */}
                <div className="flex items-center justify-between border-b px-3 py-2">
                  <div className="flex items-center gap-2 text-[12px]">
                    <span className="font-mono text-muted-foreground">Hunk {idx + 1}/{hunks.length}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5 font-medium">
                      {HUNK_TYPE_LABEL[hunk.type]}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      size="xs"
                      variant={decision === 'accept' ? 'default' : 'outline'}
                      onClick={() => setHunk(hunk.id, 'accept')}
                      className="gap-1"
                    >
                      <Check className="size-3" />
                      接受
                    </Button>
                    <Button
                      size="xs"
                      variant={decision === 'reject' ? 'destructive' : 'outline'}
                      onClick={() => setHunk(hunk.id, 'reject')}
                      className="gap-1"
                    >
                      <X className="size-3" />
                      拒绝
                    </Button>
                  </div>
                </div>
                {/* hunk 内容 */}
                <div className="space-y-2 px-3 py-3">
                  {hunk.type === 'replace' && hunk.inline && (
                    <InlineDiffView ops={hunk.inline} />
                  )}
                  {hunk.type === 'insert' && hunk.text != null && (
                    <BlockTextView text={hunk.text} kind="insert" />
                  )}
                  {hunk.type === 'delete' && hunk.original_para != null && (
                    <BlockTextView text={hunk.original_para} kind="delete" />
                  )}
                </div>
                {decided && (
                  <div className="border-t px-3 py-1.5 text-[11px] text-muted-foreground">
                    {decision === 'accept' ? '已标记接受' : '已标记拒绝'}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </ScrollArea>

      {/* 底部操作栏 */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-t px-4 py-3">
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="outline" onClick={acceptAll} disabled={applying} className="gap-1.5">
            <CheckCheck className="size-3.5" />
            全部接受
          </Button>
          <Button size="sm" variant="outline" onClick={rejectAll} disabled={applying} className="gap-1.5">
            <XCircle className="size-3.5" />
            全部拒绝
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[12px] text-muted-foreground">
            将应用 {acceptedIds.length}/{hunks.length} 项
          </span>
          <Button
            size="sm"
            onClick={handleApply}
            disabled={applying || acceptedIds.length === 0}
            className="gap-1.5"
          >
            {applying ? '应用中...' : `应用 ${acceptedIds.length} 项更改`}
          </Button>
        </div>
      </div>
    </div>
  )
}
