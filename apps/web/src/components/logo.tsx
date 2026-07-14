import { cn } from '@/lib/utils'

/**
 * 天工 logo：墨色方印 + AI 紫星点。
 * 内联 SVG，无外部资源。星点是产品"AI 驱动"身份的唯一视觉锚点。
 */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <svg
        width="26"
        height="26"
        viewBox="0 0 26 26"
        fill="none"
        aria-hidden="true"
        className="shrink-0"
      >
        {/* 方印底 */}
        <rect
          x="1.5"
          y="1.5"
          width="23"
          height="23"
          rx="5"
          className="fill-primary"
        />
        {/* "工" 字笔画，亮色镂空 */}
        <path
          d="M7 8.5h12M13 8.5v9M9.5 17.5h7"
          stroke="oklch(0.985 0 0)"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight">
        天工
        <span className="ml-1 text-muted-foreground font-normal text-[13px]">
          TianGong
        </span>
      </span>
    </span>
  )
}
