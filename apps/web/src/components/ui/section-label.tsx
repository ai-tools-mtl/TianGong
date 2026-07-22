import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * 分组小标题（统一原语）。
 *
 * 全站原本重复的分组标签（text-[10px] uppercase tracking-[0.12em] text-muted-foreground），
 * 统一收口到此组件。Apple 风格的 eyebrow / section header。
 */
function SectionLabel({
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      data-slot="section-label"
      className={cn(
        "text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/80",
        className,
      )}
      {...props}
    />
  )
}

export { SectionLabel }
