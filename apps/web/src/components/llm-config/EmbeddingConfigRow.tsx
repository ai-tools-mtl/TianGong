'use client'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import type { UserEmbeddingConfig } from '@/types/api'

/**
 * embedding 配置列表中的一行（unified panel 内的一行，带 hairline）。
 * 与 LLMConfigRow 同构（视觉/交互一致），仅 config 类型不同：
 * UserEmbeddingConfig 无 provider 字段，`model` 即嵌入模型。
 *
 * 默认态：accent 圆点 + 蓝色「默认」徽章；非默认：右侧「设为默认」ghost 按钮。
 */
export interface EmbeddingConfigRowProps {
  config: UserEmbeddingConfig
  isDefault: boolean
  onSetDefault: () => void
  onEdit: () => void
  onDelete: () => void
  /** 该行是否处于编辑展开态（展开时不显示操作按钮，由面板接管）。 */
  isEditing?: boolean
}

export function EmbeddingConfigRow({
  config, isDefault, onSetDefault, onEdit, onDelete, isEditing,
}: EmbeddingConfigRowProps) {
  return (
    <div
      className={cn(
        'flex items-center justify-between gap-3 px-5 py-4 transition-colors',
        'border-t border-black/[0.07] first:border-t-0 dark:border-white/10',
        isEditing && 'bg-transparent',
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {isDefault && <span className="size-[7px] shrink-0 rounded-full bg-[#0071e3]" />}
          <span className="truncate text-[14px] font-semibold">{config.name}</span>
          {isDefault && (
            <span className="shrink-0 rounded-full bg-[rgba(0,113,227,0.08)] px-2 py-0.5 text-[11px] font-semibold text-[#0071e3]">
              默认
            </span>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-muted-foreground">
          <span className="font-mono">{config.model}</span>
          <span>·</span>
          <span className="font-mono">{config.api_key_masked}</span>
        </div>
      </div>

      {!isEditing && (
        <div className="flex shrink-0 gap-1.5">
          {!isDefault && (
            <Button size="xs" variant="outline" onClick={onSetDefault}>设为默认</Button>
          )}
          <Button size="xs" variant="outline" onClick={onEdit}>编辑</Button>
          <Button size="xs" variant="ghost" className="text-destructive hover:text-destructive" onClick={onDelete}>
            删除
          </Button>
        </div>
      )}
    </div>
  )
}
