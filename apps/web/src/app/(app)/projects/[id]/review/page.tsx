'use client'

import { ArrowLeft, CheckCircle2, Play, TrendingDown, TrendingUp, TriangleAlert } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { DimensionScore, ReviewRecord } from '@/types/api'

export default function ReviewPage() {
  const params = useParams<{ id: string }>()
  const qc = useQueryClient()
  const [reviewing, setReviewing] = useState(false)

  const { data: reviews } = useQuery({
    queryKey: ['reviews', params.id],
    queryFn: () => api.listReviews(params.id),
  })

  const latest: ReviewRecord | undefined = reviews?.[0]

  const runReview = useMutation({
    mutationFn: () => api.runReview(params.id),
    onMutate: () => setReviewing(true),
    onSuccess: () => {
      toast.success('审查完成')
      qc.invalidateQueries({ queryKey: ['reviews', params.id] })
    },
    onError: () => toast.error('审查失败'),
    onSettled: () => setReviewing(false),
  })

  const improved =
    latest?.previous_score !== null &&
    latest !== undefined &&
    latest.total_score >= (latest.previous_score ?? 0)

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <Button variant="ghost" size="sm" className="mb-4 gap-1.5 px-2" asChild>
        <Link href={`/projects/${params.id}`}>
          <ArrowLeft className="size-3.5" />
          返回编辑
        </Link>
      </Button>

      <div className="flex items-center justify-between border-b pb-4">
        <h1 className="text-xl font-bold tracking-tight">交底书审查</h1>
        <Button onClick={() => runReview.mutate()} disabled={reviewing} className="gap-1.5">
          <Play className="size-3.5" />
          {reviewing ? '审查中...' : '执行审查'}
        </Button>
      </div>

      {latest ? (
        <div className="space-y-4 py-6">
          {/* 总分卡 */}
          <Card>
            <CardContent className="flex items-center justify-between py-6">
              <div>
                <div className="text-4xl font-bold tabular-nums">{latest.total_score}</div>
                <div className="text-sm text-muted-foreground">
                  总分 · 第 {latest.round} 轮
                </div>
              </div>
              {latest.previous_score !== null && (
                <Badge
                  variant="outline"
                  className={cn(
                    'gap-1 px-2.5 py-1 text-[13px]',
                    improved
                      ? 'border-success/40 text-success'
                      : 'border-destructive/40 text-destructive',
                  )}
                >
                  {improved ? (
                    <TrendingUp className="size-3.5" />
                  ) : (
                    <TrendingDown className="size-3.5" />
                  )}
                  {improved ? '+' : ''}
                  {latest.total_score - (latest.previous_score ?? 0)}
                </Badge>
              )}
            </CardContent>
          </Card>

          {/* 维度评分 */}
          <div className="grid gap-3 sm:grid-cols-2">
            {(latest.dimension_scores as DimensionScore[]).map((d) => (
              <Card key={d.key} className="apple-lift">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-[14px] tracking-tight">{d.name}</CardTitle>
                    <span className="text-lg font-bold tabular-nums">{d.score}</span>
                  </div>
                </CardHeader>
                <CardContent className="space-y-1.5 pt-0 text-[13px]">
                  <p className="text-xs text-muted-foreground">
                    权重 {Math.round(d.weight * 100)}%
                  </p>
                  {d.evidence && <p className="text-foreground">{d.evidence}</p>}
                  {d.suggestion && (
                    <p className="text-muted-foreground">{d.suggestion}</p>
                  )}
                  <p className="text-xs text-muted-foreground">
                    自一致性：{d.run_scores.join(' / ')}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* 问题清单：单一面板，细线分隔两组 */}
          {(latest.resolved_issues.length > 0 || latest.remaining_issues.length > 0) && (
            <div className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10" style={{ boxShadow: 'var(--shadow-card)' }}>
              {latest.resolved_issues.length > 0 && (
                <div className="px-5 py-4">
                  <div className="mb-2 flex items-center gap-1.5 text-[14px] font-semibold">
                    <CheckCircle2 className="size-4 text-muted-foreground" />
                    已解决的问题
                  </div>
                  <ul className="space-y-1 text-[13px] text-muted-foreground">
                    {latest.resolved_issues.map((issue, i) => (
                      <li key={i} className="flex gap-2">
                        <span>✓</span>
                        <span>{issue}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {latest.resolved_issues.length > 0 && latest.remaining_issues.length > 0 && (
                <div className="border-t border-black/[0.07] dark:border-white/10" />
              )}
              {latest.remaining_issues.length > 0 && (
                <div className="px-5 py-4">
                  <div className="mb-2 flex items-center gap-1.5 text-[14px] font-semibold">
                    <TriangleAlert className="size-4 text-muted-foreground" />
                    待改进
                  </div>
                  <ul className="space-y-1 text-[13px] text-muted-foreground">
                    {latest.remaining_issues.map((issue, i) => (
                      <li key={i} className="flex gap-2">
                        <span>→</span>
                        <span>{issue}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="grid place-items-center py-20 text-center">
          <p className="text-sm text-muted-foreground">
            尚未审查，点击「执行审查」开始
          </p>
        </div>
      )}
    </div>
  )
}
