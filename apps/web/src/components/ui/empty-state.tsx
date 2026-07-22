import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * 空状态/占位面板（统一原语）。
 *
 * 全站原本重复 7+ 次的手写空态卡片（rounded-2xl border-black/[0.07] + boxShadow），
 * 统一收口到此组件。遵循 apple-liquid-glass「统一白面 + 发丝线 + 双层柔影」结构。
 *
 * 按 GOTCHAS F8 手写（shadcn CLI 与 MCP SDK 冲突装不了组件）。
 */
function EmptyState({
  className,
  icon,
  title,
  description,
  action,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  /** 顶部图标（可选，Lucide 组件即可） */
  icon?: React.ReactNode
  /** 主标题 */
  title?: React.ReactNode
  /** 描述文字 */
  description?: React.ReactNode
  /** 底部操作（按钮等） */
  action?: React.ReactNode
}) {
  return (
    <div
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-2xl border border-black/[0.07] bg-card px-6 py-16 text-center dark:border-white/10",
        className,
      )}
      style={{ boxShadow: "var(--shadow-card)", ...props.style }}
      {...props}
    >
      {icon && (
        <div className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
          {icon}
        </div>
      )}
      {title && (
        <p className="text-sm font-medium text-foreground">{title}</p>
      )}
      {description && (
        <p className="max-w-sm text-[13px] leading-relaxed text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

export { EmptyState }
