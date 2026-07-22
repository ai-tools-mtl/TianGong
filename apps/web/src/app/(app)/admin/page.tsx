'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { AlertTriangle, ArrowRight, CheckCircle2 } from 'lucide-react'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { LLMHealth, LLMStats, RecentUser } from '@/types/api'

/**
 * Admin 落地页（refactor/admin-ia-phase1 重写）。
 *
 * 原 572 行胖单页把「只读仪表盘 + 用户运营操作台 + 全局 LLM 配置台 + 监控明细 + 审计日志」
 * 全挤在一页。本阶段砍掉所有操作 Section（用户列表/封禁/重置密码/授权/LLM 配置表单/统计明细/
 * 审计日志全量），主页只保留聚合视图：
 *
 *   ① 待办聚合：待审工单 + LLM 健康（失败率>5% 标黄）
 *   ② 用户活动：最近登录 5 + 最近创建 5
 *   ③ 关键指标：4 个数字一行（总用户/7d 新增/LLM 调用/已授权数）
 *
 * 被砍掉的能力阶段 2 会迁到对应子页（Users/Console/Content），API 契约不变。
 */

export default function AdminPage() {
  // ── 聚合数据 ──
  const { data: userStats } = useQuery({
    queryKey: ['user-stats'],
    queryFn: () => api.listUserStats(),
  })
  const { data: stats } = useQuery({
    queryKey: ['llm-stats', 7],
    queryFn: () => api.listLLMStats(7),
  })
  const { data: health } = useQuery({
    queryKey: ['llm-health', 7],
    queryFn: () => api.getLLMHealth(7),
  })
  const { data: recentLogins } = useQuery({
    queryKey: ['admin-recent-logins'],
    queryFn: () => api.listRecentLogins(),
  })
  const { data: recentCreations } = useQuery({
    queryKey: ['admin-recent-creations'],
    queryFn: () => api.listRecentCreations(),
  })
  const { data: pendingReviews } = useQuery({
    queryKey: ['admin-pending-reviews'],
    queryFn: () => api.listPendingReviews(),
  })

  const pendingCount = pendingReviews?.length ?? 0
  const statsData = stats
  const userStatsData = userStats

  return (
    <PageShell>
      <PageHeader title="管理后台" description="系统概览" />

      <div className="space-y-6 py-6">
        {/* ① 待办聚合：待审工单 + LLM 健康，合并为单一面板 */}
        <section
          className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div className="flex items-center justify-between px-5 py-4">
            <div>
              <div className="text-[13px] text-muted-foreground">待审工单</div>
              <div className="mt-1 text-[28px] font-semibold leading-none">
                {pendingReviews ? pendingCount : <Skeleton className="mt-1 h-7 w-10" />}
              </div>
              <div className="mt-2 text-[12px] text-muted-foreground">
                知识库审核队列
              </div>
            </div>
            <Button asChild variant="outline" size="sm">
              <Link href="/admin/review">
                {pendingCount > 0 ? '去审核' : '查看'}
                <ArrowRight className="ml-1.5 size-3.5" />
              </Link>
            </Button>
          </div>
          <div className="border-t border-black/[0.07] dark:border-white/10" />
          <LLMHealthRow health={health} stats={statsData} />
        </section>

        {/* ② 用户活动：最近登录 + 最近注册，合并为单一面板 */}
        <section
          className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <UserActivitySection
            title="最近登录"
            users={recentLogins}
            emptyText="暂无登录记录"
          />
          <div className="border-t border-black/[0.07] dark:border-white/10" />
          <UserActivitySection
            title="最近注册"
            users={recentCreations}
            emptyText="暂无新用户"
          />
        </section>

        {/* ③ 关键指标：4 个数字合并为一条统计条带 */}
        <section
          className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div className="grid grid-cols-2 lg:grid-cols-4">
            <MetricCell label="总用户" value={userStatsData?.total} />
            <MetricCell label="7d 新增" value={userStatsData?.new_7d} />
            <MetricCell label="LLM 调用（7d）" value={statsData?.total_calls} />
            <MetricCell label="已授权数" value={userStatsData?.granted_count} />
          </div>
        </section>
      </div>
    </PageShell>
  )
}

// ── 子组件 ──

function LLMHealthRow({
  health,
  stats,
}: {
  health: LLMHealth | undefined
  stats: LLMStats | undefined
}) {
  const isWarning = health?.status === 'warning'
  const ok = health?.status === 'ok'

  return (
    <div className="flex items-center justify-between px-5 py-4">
      <div>
        <div className="text-[13px] text-muted-foreground">LLM 健康</div>
        <div className="mt-1 flex items-baseline gap-2">
          {health ? (
            <>
              <span
                className={cn(
                  'text-[28px] font-semibold leading-none',
                  isWarning ? 'text-warning' : 'text-success',
                )}
              >
                {(health.failure_rate * 100).toFixed(1)}%
              </span>
              <span className="text-[12px] text-muted-foreground">失败率（7d）</span>
            </>
          ) : (
            <Skeleton className="h-7 w-20" />
          )}
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-[12px]">
          {ok ? (
            <>
              <CheckCircle2 className="size-3.5 text-success" />
              <span className="text-muted-foreground">
                健康 · {stats?.total_calls ?? 0} 次调用
              </span>
            </>
          ) : isWarning ? (
            <>
              <AlertTriangle className="size-3.5 text-warning" />
              <span className="text-warning">
                失败率超阈值（{health?.failed ?? 0} 次失败）
              </span>
            </>
          ) : (
            <Skeleton className="h-3.5 w-28" />
          )}
        </div>
      </div>
      <Button asChild variant="outline" size="sm">
        <Link href="/admin/console/stats">
          查看
          <ArrowRight className="ml-1.5 size-3.5" />
        </Link>
      </Button>
    </div>
  )
}

function UserActivitySection({
  title,
  users,
  emptyText,
}: {
  title: string
  users: RecentUser[] | undefined
  emptyText: string
}) {
  return (
    <div className="px-5 py-4">
      <div className="mb-3 text-[13px] text-muted-foreground">{title}</div>
      {!users ? (
        <div className="space-y-2.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center justify-between">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-3.5 w-16" />
            </div>
          ))}
        </div>
      ) : users.length === 0 ? (
        <div className="py-4 text-center text-[12px] text-muted-foreground">
          {emptyText}
        </div>
      ) : (
        <ul className="space-y-2">
          {users.map((u) => (
            <li
              key={u.id}
              className="flex items-center justify-between gap-3 text-[13px]"
            >
              <div className="min-w-0">
                <span className="font-medium">{u.username}</span>
                {u.email && (
                  <span className="ml-1.5 truncate text-[12px] text-muted-foreground">
                    {u.email}
                  </span>
                )}
              </div>
              {u.ts && (
                <span className="shrink-0 text-[12px] text-muted-foreground">
                  {formatRelativeTime(u.ts)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function MetricCell({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="border-b border-r border-black/[0.07] px-5 py-4 last:border-r-0 dark:border-white/10">
      <div className="text-[12px] text-muted-foreground">{label}</div>
      <div className="mt-1 text-[22px] font-semibold leading-none tabular-nums">
        {value ?? <Skeleton className="mt-1 h-6 w-10" />}
      </div>
    </div>
  )
}

// ── 工具 ──

/** ISO 时间 → 相对时间（如 "3 小时前" / "2 天前"）。1 周外回退到日期。 */
function formatRelativeTime(iso: string): string {
  const then = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - then.getTime()
  const diffMin = Math.floor(diffMs / 60_000)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  if (diffHour < 24) return `${diffHour} 小时前`
  if (diffDay < 7) return `${diffDay} 天前`
  // 1 周外回退到日期，避免「30 天前」这种没信息量的表达。
  return then.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}
