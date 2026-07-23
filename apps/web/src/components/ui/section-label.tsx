import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * 分组小标题（统一原语）。
 *
 * 统一收口全站重复的分组标签。Apple 风格的 eyebrow / section header。
 * - size="sm"（默认）：紧凑场景（对话框内 section），text-[10px] uppercase
 * - size="md"：宽疏内容页（设置页等），text-[13px] 正常大小
 */
function SectionLabel({
  className,
  size = "sm",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  size?: "sm" | "md"
}) {
  return (
    <span
      data-slot="section-label"
      className={cn(
        "font-semibold text-muted-foreground",
        size === "sm"
          ? "text-[10px] uppercase tracking-[0.12em] text-muted-foreground/80"
          : "text-[13px] tracking-tight",
        className,
      )}
      {...props}
    />
  )
}

export { SectionLabel }
