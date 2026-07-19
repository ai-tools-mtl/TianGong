import { cn } from '@/lib/utils'

/**
 * Skeleton 占位（手写版，等价于 shadcn/ui skeleton）。
 *
 * 用 animate-pulse 做加载占位，是 shadcn skeleton 的标准实现。
 * 本项目 shadcn CLI 与已装的 MCP SDK 冲突无法正常 add，故手写。
 * 阶段 2 装 table/select/switch 时一并修复 CLI。
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-muted', className)}
      {...props}
    />
  )
}

export { Skeleton }
