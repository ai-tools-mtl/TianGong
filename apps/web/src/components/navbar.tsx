'use client'

import {
  BookOpen,
  CheckCircle,
  ChevronDown,
  FileText,
  LayoutDashboard,
  LogOut,
  Settings,
  Shield,
  Tags,
  Users,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Logo } from '@/components/logo'
import { ThemeToggle } from '@/components/theme-toggle'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'

type NavItem = {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  adminOnly?: boolean
  userOnly?: boolean
  /** 渲染待审工单徽标（仅审核项）。 */
  showPendingBadge?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: '工作台', icon: LayoutDashboard, userOnly: true },
  { href: '/templates', label: '模板', icon: FileText, userOnly: true },
  { href: '/knowledge', label: '知识库', icon: BookOpen, userOnly: true },
  { href: '/tags', label: '标签', icon: Tags, userOnly: true },
  { href: '/admin', label: '管理', icon: Shield, adminOnly: true },
  { href: '/settings', label: '设置', icon: Settings },
]

/**
 * Admin 区域顶栏导航项（从 sidebar.tsx 迁移）。
 * admin 是纯管理角色，进入 /admin/* 后顶栏整组切换为这些功能项。
 */
const ADMIN_NAV_ITEMS: NavItem[] = [
  { href: '/admin', label: '概览', icon: LayoutDashboard },
  { href: '/admin/users', label: '用户', icon: Users },
  { href: '/admin/content', label: '内容', icon: FileText },
  { href: '/admin/review', label: '审核', icon: CheckCircle, showPendingBadge: true },
  { href: '/admin/console', label: '控制台', icon: Settings },
]

export function Navbar() {
  const router = useRouter()
  const pathname = usePathname()
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)
  const navRef = useRef<HTMLElement>(null)

  // 滚动边缘渐显：内容真正滚到 nav 下方时才出现发丝线（Apple scroll-edge grammar）
  useEffect(() => {
    const onScroll = () => {
      if (navRef.current) {
        navRef.current.classList.toggle('nav-scrolled', window.scrollY > 8)
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  async function handleLogout() {
    try {
      await api.logout()
      setUser(null)
      toast.success('已登出')
      router.push('/login')
    } catch {
      toast.error('登出失败')
    }
  }

  // admin 区域：顶栏整组切换为 admin 功能项（替代原 sidebar）。
  // 普通用户区域：显示过滤后的普通导航项。
  const isAdminArea = pathname === '/admin' || pathname.startsWith('/admin/')
  const userItems = NAV_ITEMS.filter(
    (i) => (!i.adminOnly || user?.role === 'admin') && (!i.userOnly || user?.role !== 'admin'),
  )
  const navItems = isAdminArea ? ADMIN_NAV_ITEMS : userItems

  return (
    <header
      className="glass-nav sticky top-0 z-40"
      ref={navRef}
    >
      <div className="flex h-14 items-center justify-between px-6">
        {/* 左：logo + 全局导航 */}
        <div className="flex items-center gap-6">
          <Link href={isAdminArea ? '/admin' : '/dashboard'} className="flex items-center">
            <Logo />
          </Link>
          <nav className="flex items-center gap-0.5">
            {navItems.map((item) => {
              const active = isAdminActive(pathname, item.href)
              const Icon = item.icon
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[13px] font-medium transition-colors',
                    active
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                  )}
                >
                  <Icon className="size-3.5" />
                  {item.label}
                  {item.showPendingBadge && <PendingBadge />}
                </Link>
              )
            })}
          </nav>
        </div>

        {/* 右：主题 + 用户 */}
        <div className="flex items-center gap-2">
          <ThemeToggle />
          {user && <UserMenu username={user.username} email={user.email} onLogout={handleLogout} />}
        </div>
      </div>
    </header>
  )
}

/**
 * 待审工单徽标（从 sidebar.tsx 迁移）。
 * 仅用于显示数字，staleTime 拉长避免每个子页都重查。
 */
function PendingBadge() {
  const { data: pending, isLoading } = useQuery({
    queryKey: ['admin-pending-reviews-nav'],
    queryFn: () => api.listPendingReviews(),
    staleTime: 30_000,
  })
  const count = pending?.length ?? 0
  if (isLoading) return <Skeleton className="h-4 w-5 rounded-full" />
  if (count === 0) return null
  return (
    <Badge variant="secondary" className="h-4 min-w-[1.25rem] px-1 text-[10px]">
      {count}
    </Badge>
  )
}

/**
 * admin 激活态判定：/admin 必须精确匹配，否则任何 /admin/* 都会被点亮。
 */
function isAdminActive(pathname: string, href: string): boolean {
  if (href === '/admin') return pathname === '/admin'
  return pathname === href || pathname.startsWith(`${href}/`)
}

function UserMenu({
  username,
  email,
  onLogout,
}: {
  username: string
  email?: string | null
  onLogout: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { setTheme, theme } = useTheme()

  useEffect(() => {
    if (!open) return
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full py-1.5 pl-2 pr-1.5 text-[13px] hover:bg-accent/60 transition-colors"
      >
        <span className="grid size-6 place-items-center rounded-full bg-primary text-[11px] font-medium text-primary-foreground">
          {username[0]?.toUpperCase()}
        </span>
        <span className="hidden text-muted-foreground sm:inline max-w-[180px] truncate">
          {username}
        </span>
        <ChevronDown className="size-3.5 text-muted-foreground" />
      </button>
      {open && (
        <div className="glass-overlay absolute right-0 top-full mt-1 w-56 overflow-hidden rounded-2xl border border-black/[0.07] p-1 text-popover-foreground dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-overlay)' }}>
          <div className="px-2.5 py-1.5">
            <p className="text-[11px] text-muted-foreground">已登录</p>
            <p className="truncate text-[13px] font-medium">{username}</p>
            {email && <p className="truncate text-[12px] text-muted-foreground">{email}</p>}
          </div>
          <div className="my-1 h-px bg-border" />
          {/* 主题快切 */}
          <div className="flex items-center gap-1 px-1 py-1">
            {(['light', 'dark', 'system'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTheme(t)}
                className={cn(
                  'flex-1 rounded-full px-2 py-1 text-[12px] capitalize transition-colors',
                  theme === t
                    ? 'bg-accent text-foreground'
                    : 'text-muted-foreground hover:bg-accent/60',
                )}
              >
                {t === 'light' ? '亮色' : t === 'dark' ? '暗色' : '跟随系统'}
              </button>
            ))}
          </div>
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            onClick={onLogout}
            className="flex w-full items-center gap-2 rounded-full px-2.5 py-1.5 text-[13px] text-foreground hover:bg-accent/60 transition-colors"
          >
            <LogOut className="size-3.5" />
            登出
          </button>
        </div>
      )}
    </div>
  )
}
