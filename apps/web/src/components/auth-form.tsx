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
    const username = String(form.get('username'))
    const emailRaw = form.get('email')
    const email = emailRaw ? String(emailRaw) : undefined
    const password = String(form.get('password'))
    const name = String(form.get('name') || '')

    try {
      if (isRegister) {
        await api.register({ username, email, password, name })
      }
      await api.login({ username, password })
      const user = await api.me()
      setUser(user)
      toast.success('登录成功')
      router.push('/dashboard')
    } catch (err) {
      const msg = (err as { message?: string })?.message
      // 后端认证错误的常见提示优化
      if (msg?.includes('用户名或密码')) {
        toast.error('用户名或密码错误，请检查后重试')
      } else if (msg?.includes('未登录') || msg?.includes('凭证')) {
        toast.error('登录态失效，请重新登录')
      } else {
        toast.error(msg || '操作失败，请重试')
      }
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
        <Label htmlFor="username">用户名</Label>
        <Input
          id="username"
          name="username"
          type="text"
          required
          minLength={3}
          maxLength={32}
          pattern="^[a-zA-Z0-9_-]+$"
          placeholder="字母/数字/下划线/连字符，3-32 位"
        />
      </div>
      {isRegister && (
        <div className="space-y-2">
          <Label htmlFor="email">邮箱（可选）</Label>
          <Input id="email" name="email" type="email" placeholder="可选，用于联系方式" />
        </div>
      )}
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
