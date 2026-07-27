'use client'

import { ChevronDown } from 'lucide-react'

import { cn } from '@/lib/utils'

interface CollapsibleProps {
  /** 触发器内容(显示在箭头后) */
  trigger: React.ReactNode
  /** 展开内容 */
  children: React.ReactNode
  className?: string
}

/**
 * 折叠组件(用原生 <details>,最轻量,无 Radix 依赖)。
 * 箭头展开时旋转 90°(group-open:rotate-90)。
 */
export function Collapsible({ trigger, children, className }: CollapsibleProps) {
  return (
    <details className={cn('group', className)}>
      <summary className="flex cursor-pointer list-none items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
        <ChevronDown className="size-3.5 transition-transform group-open:rotate-90" />
        {trigger}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  )
}
