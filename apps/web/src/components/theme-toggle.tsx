'use client'

import { Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'

/**
 * 主题切换。亮/暗/跟随系统三态。
 * mount 前不渲染图标，避免 next-themes SSR 水合不一致。
 */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  if (!mounted) {
    return (
      <Button variant="ghost" size="icon-sm" aria-label="切换主题" disabled>
        <Sun className="size-4" />
      </Button>
    )
  }

  const next = theme === 'dark' ? 'light' : 'dark'
  const Icon = theme === 'dark' ? Sun : Moon

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={`切换到${next === 'dark' ? '暗色' : '亮色'}主题`}
      title={theme === 'dark' ? '切换到亮色' : '切换到暗色'}
      onClick={() => setTheme(next)}
    >
      <Icon className="size-4" />
    </Button>
  )
}
