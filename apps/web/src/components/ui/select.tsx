import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * 原生 select 封装（统一原语）。
 *
 * 全站原本 2+ 处手写 <select> 重复 focus-ring 逻辑（create-project / share-dialog / settings）。
 * 封装原生 select 保持轻量——这些场景都是简单下拉，不需要 Radix Popover 组合的复杂度。
 *
 * 视觉与 Input 对齐：同样的高度/圆角/border/focus-ring。
 * 按 GOTCHAS F8 手写（shadcn CLI 与 MCP SDK 冲突装不了组件）。
 */
function Select({
  className,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      data-slot="select"
      className={cn(
        "h-9 w-full min-w-0 rounded-lg border border-input bg-transparent px-3 py-1 text-sm transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30",
        className,
      )}
      {...props}
    />
  )
}

export { Select }
