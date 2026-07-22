'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { useAuthStore } from '@/stores/auth'

/**
 * 根路径按角色分流：
 * - admin → /admin（纯管理角色，不碰写作）
 * - 普通用户 → /dashboard
 * - 未登录 → /login（由 (app)/layout 的守卫或 auth-form 处理）
 *
 * 用 client component 读 auth store（与 (app)/layout.tsx 的登录态校验一致），
 * 避免 server 端无法访问 httpOnly cookie 里的 session。
 */
export default function Home() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)

  useEffect(() => {
    if (!user) {
      // store 还没填：尝试 me() 兜底，失败则去登录
      import('@/lib/api')
        .then(({ api }) => api.me())
        .then((u) => router.replace(u.role === 'admin' ? '/admin' : '/dashboard'))
        .catch(() => router.replace('/login'))
      return
    }
    router.replace(user.role === 'admin' ? '/admin' : '/dashboard')
  }, [user, router])

  return (
    <div className="flex min-h-screen items-center justify-center text-muted-foreground">
      加载中...
    </div>
  )
}
