'use client'

import { useState } from 'react'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useLLMStats } from '@/lib/queries'
import type { LLMStatsByModel, LLMStatsByUser } from '@/types/api'

/**
 * /admin/console/stats LLM 调用统计明细（refactor/admin-ia-phase2 切片 2）。
 *
 * 把阶段 1 主页砍掉的 Section C 填回。结构：
 *   - 7d/30d 切换按钮
 *   - 6 张汇总卡片：总调用 / 成功 / 失败 / 平均耗时 / 输入 tokens / 输出 tokens
 *   - by_model Table：模型维度明细（模型 / 调用 / 失败 / 耗时 / 输入 / 输出）
 *   - by_user Table：用户维度明细（用户 / 调用 / 失败）
 *
 * 相比原 Section C 把 by_model 从 divide-y 列表升级为 Table（更清晰），
 * 新增 by_user Table（原 Section C 里数据有但只展示在 by_model 里）。
 */
export default function ConsoleStatsPage() {
  const [days, setDays] = useState(7)
  const { data: stats, isLoading } = useLLMStats(days)

  return (
    <PageShell>
      <PageHeader title="调用统计" description={`近 ${days} 天 LLM 调用聚合`}>
        <div className="flex items-center gap-1">
          {[7, 30].map((d) => (
            <Button
              key={d}
              size="sm"
              variant={days === d ? 'default' : 'outline'}
              onClick={() => setDays(d)}
            >
              {d} 天
            </Button>
          ))}
        </div>
      </PageHeader>

      <div className="space-y-6 py-6">
        {/* 汇总卡片 */}
        {isLoading || !stats ? (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            <MetricCard label="总调用" value={String(stats.total_calls)} />
            <MetricCard
              label="成功"
              value={String(stats.total_success)}
              className="text-green-600"
            />
            <MetricCard
              label="失败"
              value={String(stats.total_failed)}
              className="text-red-600"
            />
            <MetricCard
              label="平均耗时"
              value={`${stats.avg_duration_ms ? Math.round(stats.avg_duration_ms) : 0} ms`}
            />
            <MetricCard
              label="输入 tokens ↑"
              value={formatTokens(stats.total_prompt_tokens)}
            />
            <MetricCard
              label="输出 tokens ↓"
              value={formatTokens(stats.total_completion_tokens)}
            />
          </div>
        )}

        {/* 按模型 */}
        <Card>
          <CardContent className="py-4">
            <h2 className="mb-3 text-[14px] font-semibold">按模型</h2>
            {stats && stats.by_model.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>模型</TableHead>
                    <TableHead className="text-right">调用</TableHead>
                    <TableHead className="text-right">失败</TableHead>
                    <TableHead className="text-right">平均耗时</TableHead>
                    <TableHead className="text-right">输入 tokens</TableHead>
                    <TableHead className="text-right">输出 tokens</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.by_model.map((m: LLMStatsByModel) => (
                    <TableRow key={m.model}>
                      <TableCell className="font-medium">{m.model}</TableCell>
                      <TableCell className="text-right tabular-nums">{m.calls}</TableCell>
                      <TableCell className="text-right tabular-nums text-red-600">
                        {m.failed}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {m.avg_duration_ms ? Math.round(m.avg_duration_ms) : 0} ms
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatTokens(m.prompt_tokens)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatTokens(m.completion_tokens)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="rounded-md border border-dashed p-8 text-center text-[13px] text-muted-foreground">
                {isLoading ? '加载中...' : '暂无数据'}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 按用户 */}
        <Card>
          <CardContent className="py-4">
            <h2 className="mb-3 text-[14px] font-semibold">按用户</h2>
            {stats && stats.by_user.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>用户</TableHead>
                    <TableHead className="text-right">调用</TableHead>
                    <TableHead className="text-right">失败</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.by_user.map((u: LLMStatsByUser) => (
                    <TableRow key={u.user_id ?? 'anonymous'}>
                      <TableCell className="font-medium">{u.email}</TableCell>
                      <TableCell className="text-right tabular-nums">{u.calls}</TableCell>
                      <TableCell className="text-right tabular-nums text-red-600">
                        {u.failed}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="rounded-md border border-dashed p-8 text-center text-[13px] text-muted-foreground">
                {isLoading ? '加载中...' : '暂无数据'}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </PageShell>
  )
}

function MetricCard({
  label,
  value,
  className,
}: {
  label: string
  value: string
  className?: string
}) {
  return (
    <Card>
      <CardContent className="py-3">
        <div className="text-[12px] text-muted-foreground">{label}</div>
        <div className={`mt-1 text-[18px] font-semibold leading-none ${className ?? ''}`}>
          {value}
        </div>
      </CardContent>
    </Card>
  )
}

/** Token 数量格式化（≥1k 显示为 1.2k）。 */
function formatTokens(n: number): string {
  if (n >= 1000) {
    const k = n / 1000
    return `${k >= 100 ? Math.round(k) : k.toFixed(1)}k`
  }
  return String(n)
}
