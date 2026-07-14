'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

interface AuthFormProps {
  mode: 'login' | 'register'
}

export function AuthForm({ mode }: AuthFormProps) {
  const router = useRouter()
  const setUser = useAuthStore((s) => s.setUser)
  const [loading, setLoading] = useState(false)
  const isRegister = mode === 'register'

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setLoading(true)
    const form = new FormData(e.currentTarget)
    const email = String(form.get('email'))
    const password = String(form.get('password'))
    const name = String(form.get('name') || '')

    try {
      if (isRegister) {
        await api.register({ email, password, name })
      }
      await api.login({ email, password })
      const user = await api.me()
      setUser(user)
      toast.success('登录成功')
      router.push('/dashboard')
    } catch (err) {
      toast.error((err as { message?: string })?.message || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 w-full max-w-sm">
      {isRegister && (
        <div className="space-y-2">
          <Label htmlFor="name">姓名</Label>
          <Input id="name" name="name" required placeholder="你的名字" />
        </div>
      )}
      <div className="space-y-2">
        <Label htmlFor="email">邮箱</Label>
        <Input id="email" name="email" type="email" required placeholder="you@example.com" />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">密码</Label>
        <Input id="password" name="password" type="password" required minLength={8} placeholder="至少 8 位" />
      </div>
      <Button type="submit" className="w-full" disabled={loading}>
        {loading ? '处理中...' : isRegister ? '注册并登录' : '登录'}
      </Button>
    </form>
  )
}
