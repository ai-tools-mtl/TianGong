'use client'

import { cn } from '@/lib/utils'
import type { TestConnectionResult } from '@/types/api'

/**
 * 测试连接结果展示（Apple Liquid Glass：灰阶为主，状态点用单色 accent）。
 * 只测 chat（embedding 走固定 bge-m3 微服务，不再经测试连接）。
 */
export function TestResultBadge({ result }: { result: TestConnectionResult | null }) {
  if (!result) return null

  return (
    <div className="space-y-1.5 rounded-lg border border-black/[0.07] bg-muted/30 p-3 text-[12px] dark:border-white/10">
      {/* chat */}
      {result.chat ? <ResultLine label="对话模型" r={result.chat} /> : null}
      {/* 顶层错误兜底 */}
      {!result.ok && result.error && !result.chat?.error && (
        <p className="text-destructive">{result.error}</p>
      )}
    </div>
  )
}

function ResultLine({
  label, r,
}: {
  label: string
  r: { ok: boolean; latency_ms: number | null; sample?: string | null; error: string | null }
}) {
  const dot = r.ok ? 'bg-[#30d158]' : 'bg-[#ff3b30]'
  const text = r.ok
    ? `已连通${r.latency_ms != null ? ` · ${r.latency_ms}ms` : ''}${r.sample ? ` · ${r.sample.slice(0, 30)}` : ''}`
    : r.error || '失败'
  return (
    <div className="flex items-center gap-2">
      <span className={cn('size-[7px] shrink-0 rounded-full', dot)} />
      <span className="font-medium text-foreground/70">{label}</span>
      <span className={cn(r.ok ? 'text-muted-foreground' : 'text-destructive')}>{text}</span>
    </div>
  )
}
