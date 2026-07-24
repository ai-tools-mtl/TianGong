'use client'

import { ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ProviderTemplate } from '@/types/api'

/**
 * provider 模板 chip 条（横向滚动）。点选后回调填充 base_url/默认模型。
 * Apple 风格：灰阶 chip，选中用 accent（蓝色文字 + 淡蓝底）。
 */
export interface ProviderTemplatePickerProps {
  templates: ProviderTemplate[]
  selectedId: string | null
  onSelect: (t: ProviderTemplate) => void
}

export function ProviderTemplatePicker({ templates, selectedId, onSelect }: ProviderTemplatePickerProps) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {templates.map((t) => {
        const active = t.id === selectedId
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onSelect(t)}
            title={t.note || undefined}
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors',
              active
                ? 'bg-[rgba(0,113,227,0.08)] text-[#0071e3]'
                : 'bg-muted text-muted-foreground hover:bg-muted/70',
            )}
          >
            {t.name}
            {t.docs_url && active && (
              <a
                href={t.docs_url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="ml-0.5 inline-flex"
                aria-label="如何获取 API Key"
              >
                <ExternalLink className="size-3" />
              </a>
            )}
          </button>
        )
      })}
    </div>
  )
}
