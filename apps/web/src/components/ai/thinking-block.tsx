'use client'

import { useEffect, useRef, useState } from 'react'

import { Collapsible } from '@/components/ui/collapsible'
import { ThinkingIcon } from '@/components/ai/tool-meta'
import { cn } from '@/lib/utils'

/**
 * 可折叠的思考过程块（类 zcode 的 reasoning 展示）。
 *
 * 行为：
 * - 流式进行中（streaming=true）：默认展开，实时显示推理 token，标题显示呼吸点 +「思考中」。
 * - 完成（streaming=false）：自动折叠，标题变为「思考过程」，点击可展开回看。
 *
 * 视觉与正文区分：等宽偏灰的文本，气泡内置于助手消息上方。
 * thinking 文本由调用方拼接好后整段传入（流式时每片段累加）。
 */
export function ThinkingBlock({
  thinking,
  streaming,
  className,
}: {
  thinking: string
  streaming: boolean
  className?: string
}) {
  // 完成态默认折叠；流式态默认展开。用 state 控制 <details open>。
  const [open, setOpen] = useState(true)
  const bodyRef = useRef<HTMLDivElement>(null)

  // 流式结束（streaming 从 true→false）时自动折叠
  const prevStreaming = useRef(streaming)
  useEffect(() => {
    if (prevStreaming.current && !streaming) {
      setOpen(false)
    }
    prevStreaming.current = streaming
  }, [streaming])

  // 流式展开态下自动滚到底（追最新推理）
  useEffect(() => {
    if (streaming && open && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [thinking, streaming, open])

  if (!thinking) return null

  return (
    <div className={cn('rounded-lg border border-ai/15 bg-ai-muted/20', className)}>
      {/* 受控 details：用 summary onClick 主动切换 state，preventDefault 阻止浏览器
          自行切换——否则 onToggle 与受控 open 会互相覆盖，导致点击展开被「撤销」（点不开）。 */}
      <details open={open} className="group">
        <summary
          onClick={(e) => { e.preventDefault(); setOpen((o) => !o) }}
          className="flex cursor-pointer list-none items-center gap-1.5 px-2.5 py-1.5 text-[12px] text-muted-foreground [&::-webkit-details-marker]:hidden"
        >
          <ThinkingIcon className="size-3.5 text-ai/60" />
          <span className="font-medium">{streaming ? '思考中' : '思考过程'}</span>
          {streaming && (
            <span className="flex items-center">
              <span className="thinking-dot size-1 rounded-full bg-ai/50" style={{ animation: 'typing-dot 0.9s 0s ease-in-out infinite' }} />
              <span className="typing-dot size-1 rounded-full bg-ai/50" style={{ animation: 'typing-dot 0.9s 0.15s ease-in-out infinite' }} />
              <span className="typing-dot size-1 rounded-full bg-ai/50" style={{ animation: 'typing-dot 0.9s 0.3s ease-in-out infinite' }} />
            </span>
          )}
        </summary>
        <div
          ref={bodyRef}
          className="max-h-48 overflow-y-auto whitespace-pre-wrap px-2.5 pb-2 font-mono text-[11.5px] leading-relaxed text-muted-foreground/90"
        >
          {thinking}
        </div>
      </details>
    </div>
  )
}
