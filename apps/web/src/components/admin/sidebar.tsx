'use client'

import {
  ArrowLeft,
  CheckCircle,
  FileText,
  LayoutDashboard,
  Settings,
  Settings2,
  Users,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useQuery } from '@tanstack/react-query'

/**
 * Admin 区域左侧导航（refactor/admin-ia-phase1）。
 *
 * 设计参照 Linear：业务域在上（概览/用户/内容/审核），系统域在下（控制台/我的设置），
 * 主轴「系统控制台」刻意排在业务项之下（低频配置沉底，主轴是产品立场而非排序）。
 *
 * 待审工单徽标：在所有 admin 子页都渲染（用户在 /admin/users 也能看到提示），
 * 故 sidebar 独立请求 pendingReviews，不依赖落地页的 query 缓存。
 *
 * 底部「返回主应用」：admin 工作区与普通用户区隔离——顶部 Navbar 在 /admin/* 下
 * 隐藏 nav items，故退出 admin 工作区的入口放这里。
 */
type NavItem = {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  /** 渲染待审工单徽标（仅审核项）。 */
  showPendingBadge?: boolean
}

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: '',
    items: [
      { href: '/admin', label: '概览', icon: LayoutDashboard },
      { href: '/admin/users', label: '用户', icon: Users },
      { href: '/admin/content', label: '内容', icon: FileText },
      { href: '/admin/review', label: '审核', icon: CheckCircle, showPendingBadge: true },
    ],
  },
  {
    label: '系统',
    items: [
      { href: '/admin/console', label: '控制台', icon: Settings },
      { href: '/admin/settings', label: '我的设置', icon: Settings2 },
    ],
  },
]

function isActive(pathname: string, href: string): boolean {
  // /admin 必须精确匹配，否则任何 /admin/* 都会被点亮。
  if (href === '/admin') return pathname === '/admin'
  return pathname === href || pathname.startsWith(`${href}/`)
}

export function AdminSidebar() {
  const pathname = usePathname()

  // 待审工单数：失败/加载中不阻塞渲染（徽标位用 skeleton 占位）。
  const { data: pending, isLoading: pendingLoading } = useQuery({
    queryKey: ['admin-pending-reviews-sidebar'],
    queryFn: () => api.listPendingReviews(),
    // 仅用于显示数字，staleTime 拉长避免每个子页都重查。
    staleTime: 30_000,
  })
  const pendingCount = pending?.length ?? 0

  return (
    <aside className="sticky top-14 hidden h-[calc(100vh-3.5rem)] w-56 shrink-0 border-r bg-muted/30 md:flex md:flex-col">
      {/* 主导航：业务域 + 系统域 */}
      <nav className="flex-1 space-y-4 overflow-y-auto px-3 py-4">
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi} className="space-y-0.5">
            {group.label && (
              <div className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                {group.label}
              </div>
            )}
            {group.items.map((item) => {
              const active = isActive(pathname, item.href)
              const Icon = item.icon
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-colors',
                    active
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                  )}
                >
                  <span className="flex items-center gap-2">
                    <Icon className="size-3.5" />
                    {item.label}
                  </span>
                  {item.showPendingBadge &&
                    (pendingLoading ? (
                      <Skeleton className="h-4 w-5" />
                    ) : pendingCount > 0 ? (
                      <Badge
                        variant="secondary"
                        className="h-4 min-w-[1.25rem] px-1 text-[10px]"
                      >
                        {pendingCount}
                      </Badge>
                    ) : null)}
                </Link>
              )
            })}
          </div>
        ))}
      </nav>

      {/* 底部：返回主应用（退出 admin 工作区） */}
      <div className="border-t px-3 py-3">
        <Link
          href="/dashboard"
          className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          返回主应用
        </Link>
      </div>
    </aside>
  )
}
