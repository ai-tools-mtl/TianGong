'use client'

import { useMemo } from 'react'

import { ThinkingBlock } from '@/components/ai/thinking-block'
import { ToolCallCard, pairToolEvents } from '@/components/ai/tool-call-card'
import type { MessageMeta, ToolEvent } from '@/types/api'
import { cn } from '@/lib/utils'

/**
 * Agent 透明化聚合视图（类 zcode）：在助手正文之前展示「思考过程」+「工具调用」。
 *
 * 两套面板（章节助手 / 初始化助手）共用本组件。数据来源：
 * - 流式期间：面板从 SSE 的 thinking/tool_call/tool_result 事件实时累积，传入
 * - 历史回灌：从后端 Message.meta（tool_events + thinking）恢复，传入
 *
 * 当 thinking 和 toolEvents 都为空时，本组件什么都不渲染（保持旧行为）。
 *
 * Props 用「展开」形式（thinking / toolEvents / streaming）而非整个 meta，
 * 让流式态（streaming=true）与历史态（streaming=false）用同一组件。
 */
export interface AgentStepsProps {
  thinking?: string
  toolEvents?: ToolEvent[]
  /** 是否处于流式生成中（影响思考块默认展开/折叠） */
  streaming?: boolean
  className?: string
}

export function AgentSteps({ thinking, toolEvents, streaming = false, className }: AgentStepsProps) {
  // 把 call/result 事件序列配对成卡片视图模型。useMemo 避免流式时重算开销。
  const pairedCalls = useMemo(
    () => (toolEvents?.length ? pairToolEvents(toolEvents) : []),
    [toolEvents],
  )

  if (!thinking && pairedCalls.length === 0) return null

  return (
    <div className={cn('mb-2 space-y-1.5', className)}>
      {thinking && <ThinkingBlock thinking={thinking} streaming={streaming} />}
      {pairedCalls.map((call, i) => (
        <ToolCallCard key={`${call.name}-${i}`} call={call} />
      ))}
    </div>
  )
}

/** 便捷构造：从后端 MessageMeta 直接渲染（历史回灌用，streaming 恒 false）。 */
export function AgentStepsFromMeta({ meta, className }: { meta?: MessageMeta | null; className?: string }) {
  return (
    <AgentSteps
      thinking={meta?.thinking}
      toolEvents={meta?.tool_events}
      streaming={false}
      className={className}
    />
  )
}
