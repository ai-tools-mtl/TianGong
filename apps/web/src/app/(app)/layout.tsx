'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { Navbar } from '@/components/navbar'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

export default function AppLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

  useEffect(() => {
    // 进入应用页面前校验登录态
    if (user) return
    api
      .me()
      .then((u) => setUser(u))
      .catch(() => router.replace('/login'))
  }, [user, setUser, router])

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        加载中...
      </div>
    )
  }

  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </div>
  )
}
