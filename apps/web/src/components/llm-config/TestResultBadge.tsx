'use client'

import { cn } from '@/lib/utils'
import type { TestConnectionResult } from '@/types/api'

/**
 * 测试连接结果展示（Apple Liquid Glass：灰阶为主，状态点用单色 accent）。
 * 四态：成功（live 绿点）/ 失败（红）。分别展示 chat 与 embedding 两路结果。
 */
export function TestResultBadge({ result }: { result: TestConnectionResult | null }) {
  if (!result) return null

  return (
    <div className="space-y-1.5 rounded-lg border border-black/[0.07] bg-muted/30 p-3 text-[12px] dark:border-white/10">
      {/* chat */}
      {result.chat ? <ResultLine label="对话模型" r={result.chat} /> : null}
      {/* embedding */}
      {result.embedding ? (
        <ResultLine label="嵌入模型" r={result.embedding} suffix={result.embedding.dim ? `${result.embedding.dim}维` : undefined} />
      ) : null}
      {/* 顶层错误兜底 */}
      {!result.ok && result.error && !result.chat?.error && !result.embedding?.error && (
        <p className="text-destructive">{result.error}</p>
      )}
    </div>
  )
}

function ResultLine({
  label, r, suffix,
}: {
  label: string
  r: { ok: boolean; latency_ms: number | null; sample?: string | null; dim?: number | null; error: string | null }
  suffix?: string
}) {
  const dot = r.ok ? 'bg-[#30d158]' : 'bg-[#ff3b30]'
  const text = r.ok
    ? `已连通${r.latency_ms != null ? ` · ${r.latency_ms}ms` : ''}${suffix ? ` · ${suffix}` : ''}${r.sample ? ` · ${r.sample.slice(0, 30)}` : ''}`
    : r.error || '失败'
  return (
    <div className="flex items-center gap-2">
      <span className={cn('size-[7px] shrink-0 rounded-full', dot)} />
      <span className="font-medium text-foreground/70">{label}</span>
      <span className={cn(r.ok ? 'text-muted-foreground' : 'text-destructive')}>{text}</span>
    </div>
  )
}
