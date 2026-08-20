'use client'

import { ArrowLeft, CheckCircle2, Download, FileText, Layers, Play, TrendingDown, TrendingUp, TriangleAlert, Wand2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api, authFetch } from '@/lib/api'
import { useSections } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { launchRevision, launchRevisionQueue } from '@/stores/revision-store'
import type { CrossSectionIssue, DimensionScore, ReviewRecord, ReviewTrendPoint, Section } from '@/types/api'

const ISSUE_TYPE_LABELS: Record<string, string> = {
  terminology: '术语不一致',
  reference: '引用错位',
  contradiction: '逻辑矛盾',
  other: '其他',
}

export default function ReviewPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const qc = useQueryClient()
  const [reviewing, setReviewing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [issueView, setIssueView] = useState<'dimension' | 'section'>('dimension')
  // T2「按维度」修订入口的各维度目标章节（key），默认第一个未确认章节（D12）
  const [dimTargets, setDimTargets] = useState<Record<string, string>>({})

  const { data: reviews } = useQuery({
    queryKey: ['reviews', params.id],
    queryFn: () => api.listReviews(params.id),
  })

  // 后台审查状态：进行中每 3s 轮询（重进页面也能恢复「审查中」展示，防重复触发）
  const { data: reviewStatus } = useQuery({
    queryKey: ['review-status', params.id],
    queryFn: () => api.getReviewStatus(params.id),
    refetchInterval: (query) => (query.state.data?.running ? 3000 : false),
  })

  // 他处（本页发起后离开再回来 / 后台线程）完成的审查 → 刷新报告列表
  const wasRunningRef = useRef(false)
  useEffect(() => {
    const running = reviewStatus?.running ?? false
    if (wasRunningRef.current && !running) {
      qc.invalidateQueries({ queryKey: ['reviews', params.id] })
      qc.invalidateQueries({ queryKey: ['review-trend', params.id] })
    }
    wasRunningRef.current = running
  }, [reviewStatus?.running, qc, params.id])

  const { data: trend } = useQuery({
    queryKey: ['review-trend', params.id],
    queryFn: () => api.getReviewTrend(params.id),
  })

  // T2：sections 供修订入口定位（章节存在性校验 + key→对象映射）与时效提示
  const { data: sectionsData } = useSections(params.id)
  const sections: Section[] = sectionsData ?? []

  const latest: ReviewRecord | undefined = reviews?.[0]

  // T2 报告时效提示（spec §3.2.2，近似判断宁可多提示）：任何章节在本轮审查后
  // 被修改过（含确认章节等 touch updated_at 的操作——确认本身也改变后续 AI 输入，
  // 「重新审查」提示依然合理）。
  const staleReport =
    sections.length > 0 &&
    sections.some((s) => new Date(s.updated_at).getTime() > new Date(latest?.created_at ?? 0).getTime())

  // T2：按章节组发起 AI 修订（spec §3.2.3-1）——跳编辑器目标章节弹确认卡片
  function handleReviseSection(sectionKey: string, directives: string[]) {
    const ok = launchRevision(sections, sectionKey, directives, 'review', router, params.id)
    if (!ok) toast.error('目标章节不存在（可能已被调整），请手动前往该章节修订')
  }

  // 一键修订（顺序队列）：按章节问题清单逐章「确认卡片→diff 人工审核→应用→自动下一章」。
  // 跨章节一致性问题不进队列（跨章协调拆开各改各的会引入新不一致，单独规划）。
  function handleReviseAll() {
    if (!latest) return
    const items = latest.section_issues
      .filter((sec) => keyTitleMap.has(sec.section_key))
      .map((sec) => ({ sectionKey: sec.section_key, directives: sec.issues, origin: 'review' as const }))
    const n = launchRevisionQueue(sections, items, router, params.id)
    if (n === 0) toast.error('没有可修订的章节（章节可能已被调整）')
    else toast.success(`已发起批量修订：共 ${n} 章，逐章审核应用`)
  }

  // key→章节标题映射（chip 渲染用；不在 sections 中的 key 跳过）
  const keyTitleMap = new Map(sections.map((s) => [s.key, s.title]))
  // 「按维度」入口的默认落点章节：第一个未确认章节，否则第一个章节（D12）
  const defaultDimTarget =
    sections.find((s) => s.status !== 'confirmed')?.key ?? sections[0]?.key ?? ''

  // inProgress 兼两种来源：本页点击（optimistic）与他处/后台进行中（status 轮询）
  const inProgress = reviewing || (reviewStatus?.running ?? false)

  const runReview = useMutation({
    mutationFn: () => api.runReview(params.id),
    onMutate: () => setReviewing(true),
    onSuccess: () => {
      toast.success('审查完成')
      qc.invalidateQueries({ queryKey: ['reviews', params.id] })
      qc.invalidateQueries({ queryKey: ['review-trend', params.id] })
      qc.invalidateQueries({ queryKey: ['review-status', params.id] })
    },
    // 后端 message 已是友好文案（如「LLM 账户余额不足…」「审查正在进行中…」），别用写死文案把它吞了
    onError: (e) => toast.error((e as { message?: string })?.message || '审查失败'),
    onSettled: () => setReviewing(false),
  })

  // 导出走 fetch+blob 而非 <a> 直开：渲染依赖缺失（503）时 <a> 只能展示一页 JSON，
  // 这里能 toast 出后端友好文案（同「执行审查」错误透出策略）
  async function handleExport() {
    if (!latest) return
    setExporting(true)
    try {
      const res = await authFetch(`/projects/${params.id}/reviews/${latest.id}/export-pdf`)
      if (!res.ok) {
        let msg = `导出失败（HTTP ${res.status}）`
        try {
          msg = ((await res.json()) as { message?: string }).message || msg
        } catch {
          // 非 JSON 响应体，保留默认 msg
        }
        toast.error(msg)
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `审查报告-第${latest.round}轮.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setExporting(false)
    }
  }

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
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5"
              onClick={handleExport}
              disabled={exporting}
            >
              <Download className="size-3.5" />
              {exporting ? '导出中...' : '导出报告'}
            </Button>
          )}
          <Button onClick={() => runReview.mutate()} disabled={inProgress} className="gap-1.5">
            <Play className="size-3.5" />
            {inProgress ? '审查中...' : '执行审查'}
          </Button>
        </div>
      </div>

      {/* 后台审查进行中提示（含离开页面再回来的场景） */}
      {inProgress && !reviewing && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-blue-300/60 bg-blue-50 px-4 py-2.5 text-[13px] text-blue-900 dark:border-blue-700/50 dark:bg-blue-950/30 dark:text-blue-200">
          <Play className="size-4 shrink-0 animate-pulse" />
          审查正在后台进行中，完成后此处将展示最新报告
        </div>
      )}

      {latest ? (
        <div className="space-y-4 py-6">
          {/* T2 报告时效提示（spec §3.2.2）：修订应用/编辑后旧报告无标记易误判「已处理」 */}
          {staleReport && (
            <div className="flex items-center gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-4 py-2.5 text-[13px] text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/30 dark:text-amber-200">
              <TriangleAlert className="size-4 shrink-0" />
              交底书在本轮审查后有修改，建议重新审查以获得最新评估
            </div>
          )}
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
                  {/* T2 维度级修订入口（D12）：补齐「suggestion 未提章节标题 → 按章节
                      视图不可见」的聚合缺口；用户选落点章节，directives=[suggestion] */}
                  {d.suggestion && d.suggestion !== '已达标' && (
                    <div className="flex items-center gap-1.5 pt-1.5">
                      <select
                        value={dimTargets[d.key] ?? defaultDimTarget}
                        onChange={(e) => setDimTargets((m) => ({ ...m, [d.key]: e.target.value }))}
                        className="h-7 max-w-[9rem] rounded-md border border-input bg-background px-1.5 text-xs"
                        aria-label="修订目标章节"
                      >
                        {sections.map((s) => (
                          <option key={s.key} value={s.key}>{s.title}</option>
                        ))}
                      </select>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 gap-1 px-2 text-xs"
                        onClick={() =>
                          handleReviseSection(dimTargets[d.key] ?? defaultDimTarget, [d.suggestion])
                        }
                      >
                        <Wand2 className="size-3" />
                        按建议修订
                      </Button>
                    </div>
                  )}
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
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className="text-[11px]">
                          {ISSUE_TYPE_LABELS[issue.type] ?? issue.type}
                        </Badge>
                        {/* location_sections ?? []：存量 round=3 记录走文本 fallback 缺过此字段
                            （后端已单点规范化根治，这里兜存量数据防崩，同 268 行 keys 防御） */}
                        {(issue.location_sections ?? []).length > 0 && (
                          <span className="text-[12px] text-muted-foreground">
                            涉及：{(issue.location_sections ?? []).join('、')}
                          </span>
                        )}
                        {/* T2 chip 入口（spec §3.2.3-2）：点任一涉及章节 → 单章节修订。
                            keys 为空（旧数据/无匹配）仅展示不提供入口（D14：前端不做二次匹配） */}
                        {(issue.location_section_keys ?? [])
                          .filter((k) => keyTitleMap.has(k))
                          .map((k) => (
                            <button
                              key={k}
                              onClick={() => handleReviseSection(k, [issue.suggestion])}
                              className="inline-flex items-center gap-1 rounded-full border border-amber-300/70 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-900 transition-colors hover:bg-amber-100 dark:border-amber-700/50 dark:bg-amber-950/30 dark:text-amber-200"
                              title={`按建议修订「${keyTitleMap.get(k)}」章节`}
                            >
                              <Wand2 className="size-3" />
                              {keyTitleMap.get(k)}
                            </button>
                          ))}
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
                  {latest.section_issues.length > 0 && (
                    <div className="mb-4 flex items-center justify-between">
                      <p className="text-[12px] text-muted-foreground">
                        共 {latest.section_issues.length} 章有待改进问题
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 gap-1 px-2 text-xs"
                        onClick={handleReviseAll}
                      >
                        <Wand2 className="size-3" />
                        一键修订（{latest.section_issues.length} 章）
                      </Button>
                    </div>
                  )}
                  {latest.section_issues.length > 0 ? (
                    <div className="space-y-4">
                      {latest.section_issues.map((sec, i) => (
                        <div key={i}>
                          <div className="mb-1.5 flex items-center justify-between">
                            <p className="text-[14px] font-medium">
                              {/* T2 标题 Link：跳编辑器并定位该章节（?section= 深链） */}
                              <Link
                                href={`/projects/${params.id}?section=${encodeURIComponent(sec.section_key)}`}
                                className="hover:underline"
                              >
                                {sec.section_title}
                              </Link>
                            </p>
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 gap-1.5 px-2 text-xs"
                              onClick={() => handleReviseSection(sec.section_key, sec.issues)}
                            >
                              <Wand2 className="size-3.5" />
                              AI 修订本章
                            </Button>
                          </div>
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
