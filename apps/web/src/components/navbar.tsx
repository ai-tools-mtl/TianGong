'use client'

import {
  BookOpen,
  ChevronDown,
  FileText,
  LayoutDashboard,
  LogOut,
  Settings,
  Shield,
  Tags,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Logo } from '@/components/logo'
import { ThemeToggle } from '@/components/theme-toggle'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'

type NavItem = {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  adminOnly?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: '工作台', icon: LayoutDashboard },
  { href: '/templates', label: '模板', icon: FileText },
  { href: '/knowledge', label: '知识库', icon: BookOpen },
  { href: '/tags', label: '标签', icon: Tags },
  { href: '/admin', label: '管理', icon: Shield, adminOnly: true },
  { href: '/settings', label: '设置', icon: Settings },
]

export function Navbar() {
  const router = useRouter()
  const pathname = usePathname()
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

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

  const items = NAV_ITEMS.filter((i) => !i.adminOnly || user?.role === 'admin')

  return (
    <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/75">
      <div className="flex h-14 items-center justify-between px-6">
        {/* 左：logo + 全局导航 */}
        <div className="flex items-center gap-6">
          <Link href="/dashboard" className="flex items-center">
            <Logo />
          </Link>
          <nav className="flex items-center gap-0.5">
            {items.map((item) => {
              const active =
                pathname === item.href || pathname.startsWith(`${item.href}/`)
              const Icon = item.icon
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-colors',
                    active
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                  )}
                >
                  <Icon className="size-3.5" />
                  {item.label}
                </Link>
              )
            })}
          </nav>
        </div>

        {/* 右：主题 + 用户 */}
        <div className="flex items-center gap-2">
          <ThemeToggle />
          {user && <UserMenu email={user.email} onLogout={handleLogout} />}
        </div>
      </div>
    </header>
  )
}

function UserMenu({
  email,
  onLogout,
}: {
  email: string
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
        className="flex items-center gap-2 rounded-md py-1.5 pl-2 pr-1.5 text-[13px] hover:bg-accent/60 transition-colors"
      >
        <span className="grid size-6 place-items-center rounded-full bg-primary text-[11px] font-medium text-primary-foreground">
          {email[0]?.toUpperCase()}
        </span>
        <span className="hidden text-muted-foreground sm:inline max-w-[180px] truncate">
          {email}
        </span>
        <ChevronDown className="size-3.5 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-56 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md">
          <div className="px-2.5 py-1.5">
            <p className="text-[11px] text-muted-foreground">已登录</p>
            <p className="truncate text-[13px]">{email}</p>
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
                  'flex-1 rounded px-2 py-1 text-[12px] capitalize transition-colors',
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
            className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-[13px] text-foreground hover:bg-accent/60 transition-colors"
          >
            <LogOut className="size-3.5" />
            登出
          </button>
        </div>
      )}
    </div>
  )
}
