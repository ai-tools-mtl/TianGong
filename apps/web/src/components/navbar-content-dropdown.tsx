'use client'

import { BookOpen, ChevronDown, FileText } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

const SUB_ITEMS = [
  { href: '/admin/content/templates', label: '模板', icon: FileText },
  { href: '/admin/content/knowledge', label: '知识库', icon: BookOpen },
] as const

/**
 * admin 导航「内容」子菜单 dropdown。
 *
 * 点击「内容」展开 templates/knowledge 两个子项；外部点击或选中后关闭。
 * 任一子页处于激活态时，「内容」本身也点亮。
 */
export function NavbarContentDropdown() {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // 外部点击关闭
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

  const isContentActive = pathname.startsWith('/admin/content')

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[13px] font-medium transition-colors',
          isContentActive
            ? 'bg-accent text-accent-foreground'
            : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
        )}
      >
        <FileText className="size-3.5" />
        内容
        <ChevronDown
          className={cn('size-3.5 transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && (
        <div
          className="glass-overlay absolute left-0 top-full mt-1 w-44 overflow-hidden rounded-2xl border border-black/[0.07] p-1 dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-overlay)' }}
        >
          {SUB_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`)
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setOpen(false)}
                className={cn(
                  'flex items-center gap-2 rounded-full px-2.5 py-1.5 text-[13px] transition-colors',
                  active
                    ? 'bg-accent text-accent-foreground'
                    : 'text-foreground hover:bg-accent/60',
                )}
              >
                <Icon className="size-3.5" />
                {label}
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
