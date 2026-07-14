'use client'

import { useRouter } from 'next/navigation'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

export function Navbar() {
  const router = useRouter()
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

  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
        <span className="font-bold">天工 TianGong</span>
        {user && (
          <div className="flex items-center gap-3 text-sm">
            <span className="text-muted-foreground">{user.email}</span>
            <Button variant="ghost" size="sm" onClick={handleLogout}>登出</Button>
          </div>
        )}
      </div>
    </header>
  )
}
