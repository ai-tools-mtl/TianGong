'use client'

import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * 模型选择输入：下拉（来自拉取结果）+ 可手输（自由文本）。
 * 决策 D5：每个 config 仍只存一个 model 字符串；拉取结果只作建议项，不落库。
 *
 * - 下拉有数据时：点 ▾ 展开，选中填入；也可直接在输入框打字覆盖。
 * - 下拉空时：纯输入框。
 */
export interface ModelSelectInputProps {
  value: string
  onChange: (v: string) => void
  options: string[]               // 来自拉取结果
  placeholder?: string
  loading?: boolean               // 拉取中
  error?: string | null           // 拉取失败提示
  className?: string
}

export function ModelSelectInput({
  value, onChange, options, placeholder = '输入或选择模型名', loading, error, className,
}: ModelSelectInputProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className={cn('relative', className)}>
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="h-9 flex-1 rounded-lg border border-black/[0.1] bg-background px-3 text-[13px] outline-none focus:border-primary dark:border-white/15"
          autoComplete="off"
        />
        {options.length > 0 && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-black/[0.1] text-muted-foreground hover:bg-muted dark:border-white/15"
            aria-label="展开模型列表"
          >
            <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} />
          </button>
        )}
      </div>

      {loading && <p className="mt-1 text-[11px] text-muted-foreground">拉取中…</p>}
      {error && <p className="mt-1 text-[11px] text-destructive">{error}</p>}

      {open && options.length > 0 && (
        <div className="absolute z-20 mt-1 max-h-52 w-full overflow-auto rounded-lg border border-black/[0.07] bg-popover p-1 shadow-md dark:border-white/10">
          {options.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => { onChange(m); setOpen(false) }}
              className={cn(
                'block w-full rounded px-2.5 py-1.5 text-left font-mono text-[12px] hover:bg-muted',
                m === value && 'bg-muted font-medium',
              )}
            >
              {m}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
