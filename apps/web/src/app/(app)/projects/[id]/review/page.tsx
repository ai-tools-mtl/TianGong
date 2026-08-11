'use client'

import { ArrowLeft, CheckCircle2, Download, FileText, Layers, Play, TrendingDown, TrendingUp, TriangleAlert } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { CrossSectionIssue, DimensionScore, ReviewRecord, ReviewTrendPoint } from '@/types/api'

const ISSUE_TYPE_LABELS: Record<string, string> = {
  terminology: '术语不一致',
  reference: '引用错位',
  contradiction: '逻辑矛盾',
  other: '其他',
}

export default function ReviewPage() {
  const params = useParams<{ id: string }>()
  const qc = useQueryClient()
  const [reviewing, setReviewing] = useState(false)
  const [issueView, setIssueView] = useState<'dimension' | 'section'>('dimension')

  const { data: reviews } = useQuery({
    queryKey: ['reviews', params.id],
    queryFn: () => api.listReviews(params.id),
  })

  const { data: trend } = useQuery({
    queryKey: ['review-trend', params.id],
    queryFn: () => api.getReviewTrend(params.id),
  })

  const latest: ReviewRecord | undefined = reviews?.[0]

  const runReview = useMutation({
    mutationFn: () => api.runReview(params.id),
    onMutate: () => setReviewing(true),
    onSuccess: () => {
      toast.success('审查完成')
      qc.invalidateQueries({ queryKey: ['reviews', params.id] })
      qc.invalidateQueries({ queryKey: ['review-trend', params.id] })
    },
    onError: () => toast.error('审查失败'),
    onSettled: () => setReviewing(false),
  })

  const improved =
    latest?.previous_score !== null &&
    latest !== undefined &&
    latest.total_score >= (latest.previous_score ?? 0)

  // 趋势图数据：≥2 轮才展示
  const showTrend = (trend?.length ?? 0) >= 2
  const trendData = (trend ?? []).map((t: ReviewTrendPoint) => ({
    round: `第${t.round}轮`,
    总分: t.total_score,
    ...t.dimension_scores,
  }))
  // 趋势图线条：总分 + 各维度 key
  const dimensionKeys = latest?.dimension_scores?.map((d) => d.key) ?? []
  const dimensionNames = latest?.dimension_scores ?? []

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
        <div className="flex items-center gap-2">
          {latest && (
            <Button variant="ghost" size="sm" className="gap-1.5" asChild>
              <a href={api.exportReviewReportUrl(params.id, latest.id)} target="_blank" rel="noopener noreferrer">
                <Download className="size-3.5" />
                导出报告
              </a>
            </Button>
          )}
          <Button onClick={() => runReview.mutate()} disabled={reviewing} className="gap-1.5">
            <Play className="size-3.5" />
            {reviewing ? '审查中...' : '执行审查'}
          </Button>
        </div>
      </div>

      {latest ? (
        <div className="space-y-4 py-6">
          {/* 趋势图（≥2 轮展示） */}
          {showTrend && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-1.5 text-[14px] tracking-tight">
                  <TrendingUp className="size-4" />
                  分数趋势
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={trendData} margin={{ top: 5, right: 10, bottom: 5, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
                    <XAxis dataKey="round" tick={{ fontSize: 12 }} />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} />
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line type="monotone" dataKey="总分" stroke="#1a1a1a" strokeWidth={2} />
                    {dimensionKeys.map((key, i) => {
                      const dim = dimensionNames[i]
                      return (
                        <Line
                          key={key}
                          type="monotone"
                          dataKey={key}
                          name={dim?.name ?? key}
                          stroke={_CHART_COLORS[i % _CHART_COLORS.length]}
                          strokeWidth={1.5}
                          dot={{ r: 3 }}
                        />
                      )
                    })}
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

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
                  {improved ? <TrendingUp className="size-3.5" /> : <TrendingDown className="size-3.5" />}
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
                  <p className="text-xs text-muted-foreground">权重 {Math.round(d.weight * 100)}%</p>
                  {d.evidence && <p className="text-foreground">{d.evidence}</p>}
                  {d.suggestion && <p className="text-muted-foreground">{d.suggestion}</p>}
                  <p className="text-xs text-muted-foreground">自一致性：{d.run_scores.join(' / ')}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* 跨章节一致性问题 */}
          {latest.cross_section_issues.length > 0 && (
            <div className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10" style={{ boxShadow: 'var(--shadow-card)' }}>
              <div className="px-5 py-4">
                <div className="mb-3 flex items-center gap-1.5 text-[14px] font-semibold">
                  <Layers className="size-4 text-muted-foreground" />
                  跨章节一致性问题
                </div>
                <div className="space-y-3">
                  {latest.cross_section_issues.map((issue: CrossSectionIssue, i) => (
                    <div key={i} className="rounded-lg bg-black/[0.02] p-3 dark:bg-white/[0.03]">
                      <div className="mb-1 flex items-center gap-2">
                        <Badge variant="outline" className="text-[11px]">
                          {ISSUE_TYPE_LABELS[issue.type] ?? issue.type}
                        </Badge>
                        {issue.location_sections.length > 0 && (
                          <span className="text-[12px] text-muted-foreground">
                            涉及：{issue.location_sections.join('、')}
                          </span>
                        )}
                      </div>
                      <p className="text-[13px] text-foreground">{issue.description}</p>
                      {issue.suggestion && (
                        <p className="mt-1 text-[12px] text-muted-foreground">建议：{issue.suggestion}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 问题清单：Tab 切换「按维度」/「按章节」 */}
          {(latest.remaining_issues.length > 0 || latest.section_issues.length > 0) && (
            <div className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10" style={{ boxShadow: 'var(--shadow-card)' }}>
              {/* Tab 切换 */}
              <div className="flex border-b border-black/[0.07] dark:border-white/10">
                <button
                  onClick={() => setIssueView('dimension')}
                  className={cn(
                    'flex items-center gap-1.5 px-5 py-3 text-[13px] font-medium transition-colors',
                    issueView === 'dimension'
                      ? 'border-b-2 border-foreground text-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <TriangleAlert className="size-3.5" />
                  按维度
                </button>
                <button
                  onClick={() => setIssueView('section')}
                  className={cn(
                    'flex items-center gap-1.5 px-5 py-3 text-[13px] font-medium transition-colors',
                    issueView === 'section'
                      ? 'border-b-2 border-foreground text-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <FileText className="size-3.5" />
                  按章节
                </button>
              </div>

              {/* 按维度视图 */}
              {issueView === 'dimension' && (
                <div className="px-5 py-4">
                  {latest.resolved_issues.length > 0 && (
                    <div className="mb-4">
                      <div className="mb-2 flex items-center gap-1.5 text-[14px] font-semibold">
                        <CheckCircle2 className="size-4 text-muted-foreground" />
                        已解决的问题
                      </div>
                      <ul className="space-y-1 text-[13px] text-muted-foreground">
                        {latest.resolved_issues.map((issue, i) => (
                          <li key={i} className="flex gap-2"><span>✓</span><span>{issue}</span></li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {latest.remaining_issues.length > 0 && (
                    <div>
                      <div className="mb-2 flex items-center gap-1.5 text-[14px] font-semibold">
                        <TriangleAlert className="size-4 text-muted-foreground" />
                        待改进
                      </div>
                      <ul className="space-y-1 text-[13px] text-muted-foreground">
                        {latest.remaining_issues.map((issue, i) => (
                          <li key={i} className="flex gap-2"><span>→</span><span>{issue}</span></li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* 按章节视图 */}
              {issueView === 'section' && (
                <div className="px-5 py-4">
                  {latest.section_issues.length > 0 ? (
                    <div className="space-y-4">
                      {latest.section_issues.map((sec, i) => (
                        <div key={i}>
                          <p className="mb-1.5 text-[14px] font-medium">{sec.section_title}</p>
                          <ul className="space-y-1 text-[13px] text-muted-foreground">
                            {sec.issues.map((issue, j) => (
                              <li key={j} className="flex gap-2"><span>→</span><span>{issue}</span></li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[13px] text-muted-foreground">暂无按章节定位的问题</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="grid place-items-center py-20 text-center">
          <p className="text-sm text-muted-foreground">尚未审查，点击「执行审查」开始</p>
        </div>
      )}
    </div>
  )
}

// 趋势图配色（与 globals.css chart-1..5 对齐，近黑系）
const _CHART_COLORS = [
  'oklch(0.5 0.15 250)',  // 蓝
  'oklch(0.5 0.15 160)',  // 绿
  'oklch(0.5 0.15 60)',   // 黄
  'oklch(0.5 0.15 300)',  // 紫
  'oklch(0.5 0.15 20)',   // 橙
]
