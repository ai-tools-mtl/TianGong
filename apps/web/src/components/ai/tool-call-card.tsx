'use client'

import { Check, Loader2 } from 'lucide-react'

import { Collapsible } from '@/components/ui/collapsible'
import { getToolMeta } from '@/components/ai/tool-meta'
import type { ToolEvent } from '@/types/api'
import { cn } from '@/lib/utils'

/**
 * 单次工具调用的展示卡片（类 zcode 工具调用提示）。
 *
 * 一个工具调用由「call」事件发起，对应的「result」事件返回。本组件接收
 * 已配对的视图模型 PairedToolCall（由 AgentSteps 把流式事件配对后传入）：
 * - 仅 call 到达（result 未到）：显示 spinner + 「检索中…」进行态
 * - result 到达：切换为 ✓ + 命中摘要，可折叠查看完整结果
 *
 * 配色复用 --ai / --ai-muted token，与助手气泡风格一致。
 */
export interface PairedToolCall {
  name: string
  args?: Record<string, unknown>
  result?: string
  /** 是否已收到 result（决定 spinner vs ✓） */
  done: boolean
}

export function ToolCallCard({ call }: { call: PairedToolCall }) {
  const meta = getToolMeta(call.name)
  const Icon = meta.icon
  const argSummary = call.args ? meta.summarizeArgs?.(call.args) : undefined
  const resultSummary = call.result ? meta.summarizeResult?.(call.result) : undefined

  return (
    <div
      className="flex items-start gap-2 rounded-lg border border-ai/15 bg-ai-muted/30 px-2.5 py-1.5 text-[12px]"
      style={{ boxShadow: 'var(--shadow-card)' }}
    >
      <Icon className="mt-0.5 size-3.5 shrink-0 text-ai/70" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="font-medium text-foreground/80">{meta.label}</span>
          {argSummary && <span className="truncate text-muted-foreground">{argSummary}</span>}
          {call.done ? (
            <Check className="ml-auto size-3.5 shrink-0 text-emerald-600 dark:text-emerald-500" />
          ) : (
            <Loader2 className="ml-auto size-3.5 shrink-0 animate-spin text-ai/60" />
          )}
        </div>
        {/* 结果摘要（单行），无摘要时不占位 */}
        {call.done && resultSummary && (
          <div className="mt-0.5 text-muted-foreground">{resultSummary}</div>
        )}
        {/* 可折叠查看完整结果（仅 done 且结果非空时显示触发器） */}
        {call.done && call.result && (
          <Collapsible trigger={<span className="text-ai/70 underline-offset-2 hover:underline">查看结果</span>}>
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-background/60 p-2 text-[11px] text-muted-foreground">
              {call.result}
            </pre>
          </Collapsible>
        )}
      </div>
    </div>
  )
}

/** 从有序事件列表配对出视图模型（call 与同名 result 配对）。
 *  后端事件顺序：call→result，但同工具可能被多次调用，故按「先进先出」配对
 *  （每个 call 匹配其后最近的同名 result）。供 AgentSteps 使用。 */
export function pairToolEvents(events: ToolEvent[]): PairedToolCall[] {
  const calls: PairedToolCall[] = []
  // result 按名字排队，等待配对
  const pendingResults: Record<string, string[]> = {}
  for (const e of events) {
    if (e.kind === 'call') {
      // 优先消费已到的同名 result（乱序兜底，正常情况 result 晚于 call）
      const queued = pendingResults[e.name]?.shift()
      calls.push({ name: e.name, args: e.args, result: queued, done: queued !== undefined })
    } else {
      // result：找最早的未完成同名 call 配对
      const target = calls.find((c) => c.name === e.name && !c.done)
      if (target) {
        target.result = e.result
        target.done = true
      } else {
        // result 先于 call 到达（异常），入队等后续 call
        ;(pendingResults[e.name] ??= []).push(e.result ?? '')
      }
    }
  }
  return calls
}

export type { ToolEvent }
