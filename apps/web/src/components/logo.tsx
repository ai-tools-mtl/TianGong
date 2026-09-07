import { cn } from '@/lib/utils'

/**
 * 天工 logo：印章式「天工」合文字形（米白纸面 / 墨字）。
 * 内联 SVG，无外部资源。fill-current 跟随文字色，
 * 深色底（登录品牌栏）由调用方用 text-* 覆写即可反白。
 */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <svg
        width="26"
        height="26"
        viewBox="364 364 524 524"
        fill="none"
        aria-hidden="true"
        className="shrink-0 fill-current"
      >
        <path d="M364 484H547V547L480 579V697H544V768L472 771V888H364Z" />
        <path d="M705 484H888V888H779L780 771L708 769V699L772 697V579L705 547Z" />
        <path d="M364 364H888V444H669V567H584V445H364Z" />
        <path d="M516 602H736V662H668V805H744V888H508V806H584V663H517Z" />
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
