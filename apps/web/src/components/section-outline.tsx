'use client'

import { cn } from '@/lib/utils'
import type { Section } from '@/types/api'

/** 章节状态色点（大纲与连续模式章头共用，spec 2026-08-18 §3.3）。 */
export const STATUS_DOT: Record<string, string> = {
  empty: 'bg-muted-foreground',
  drafting: 'bg-info',
  confirmed: 'bg-success',
}

/** 章节状态文案（连续模式章头徽标用）。 */
export const SECTION_STATUS_LABEL: Record<string, string> = {
  empty: '待填写',
  drafting: '草稿中',
  confirmed: '已确认',
}

interface SectionOutlineProps {
  sections: Section[]
  currentId: string | null
  onSelect: (id: string) => void
  /** 折叠态：只显示状态点竖条 */
  collapsed?: boolean
}

export function SectionOutline({
  sections,
  currentId,
  onSelect,
  collapsed,
}: SectionOutlineProps) {
  if (collapsed) {
    return (
      <nav className="flex flex-col items-center gap-1.5 py-2">
        {sections.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            title={s.title}
            aria-label={s.title}
            className={cn(
              'grid size-7 place-items-center rounded-full border transition-colors',
              currentId === s.id
                ? 'border-black/[0.07] bg-accent dark:border-white/10'
                : 'border-transparent hover:bg-accent/60',
            )}
          >
            <span
              className={cn(
                'size-2 rounded-full',
                STATUS_DOT[s.status] || 'bg-muted-foreground',
              )}
            />
          </button>
        ))}
      </nav>
    )
  }

  return (
    <nav className="space-y-0.5">
      {sections.map((s, i) => (
        <button
          key={s.id}
          onClick={() => onSelect(s.id)}
          className={cn(
            'flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors',
            currentId === s.id
              ? 'bg-accent text-accent-foreground font-medium'
              : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
          )}
        >
          <span className="w-4 shrink-0 text-center text-[11px] text-muted-foreground/70">
            {i + 1}
          </span>
          <span
            className={cn(
              'size-1.5 shrink-0 rounded-full',
              STATUS_DOT[s.status] || 'bg-muted-foreground',
            )}
          />
          <span className="truncate">{s.title}</span>
        </button>
      ))}
    </nav>
  )
}
