'use client'

import { cn } from '@/lib/utils'
import type { Section } from '@/types/api'

const STATUS_DOT: Record<string, string> = {
  empty: 'bg-muted-foreground',
  drafting: 'bg-blue-500',
  confirmed: 'bg-green-500',
}

interface SectionOutlineProps {
  sections: Section[]
  currentId: string | null
  onSelect: (id: string) => void
}

export function SectionOutline({ sections, currentId, onSelect }: SectionOutlineProps) {
  return (
    <nav className="space-y-1">
      {sections.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s.id)}
          className={cn(
            'flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors',
            currentId === s.id ? 'bg-accent' : 'hover:bg-accent/50',
          )}
        >
          <span className={cn('h-2 w-2 shrink-0 rounded-full', STATUS_DOT[s.status] || 'bg-muted-foreground')} />
          <span className="truncate">{s.title}</span>
        </button>
      ))}
    </nav>
  )
}
