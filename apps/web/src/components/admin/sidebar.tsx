'use client'

import {
  CheckCircle,
  FileText,
  LayoutDashboard,
  Settings,
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
 * 设计参照 Linear：业务域在上（概览/用户/内容/审核），系统域在下（控制台），
 * 主轴「系统控制台」刻意排在业务项之下（低频配置沉底，主轴是产品立场而非排序）。
 * admin 强制使用全局 Key（无 BYOK），故无「我的设置」入口——admin 改 LLM 走控制台。
 *
 * 待审工单徽标：在所有 admin 子页都渲染（用户在 /admin/users 也能看到提示），
 * 故 sidebar 独立请求 pendingReviews，不依赖落地页的 query 缓存。
 *
 * admin 工作区完全闭环（纯管理）：顶部 Navbar 在 /admin/* 下隐藏 nav items，
 * sidebar 也不提供「返回主应用」出口——admin 是独立工作空间，要访问普通用户视角
 * （写交底书等）需手敲 /dashboard 等路径。责任交给用户，UI 保持纯净。
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
    items: [{ href: '/admin/console', label: '控制台', icon: Settings }],
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
    <aside className="sticky top-14 hidden h-[calc(100vh-3.5rem)] w-56 shrink-0 overflow-y-auto border-r bg-muted/30 px-3 py-4 md:block">
      {/* 主导航：业务域 + 系统域（admin 工作区完全闭环，无底部出口） */}
      {NAV_GROUPS.map((group, gi) => (
        <div key={gi} className={gi > 0 ? 'mt-4 space-y-0.5' : 'space-y-0.5'}>
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
    </aside>
  )
}
