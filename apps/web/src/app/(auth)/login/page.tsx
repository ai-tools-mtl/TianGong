import Link from 'next/link'

import { AuthForm } from '@/components/auth-form'
import { Logo } from '@/components/logo'

export default function LoginPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2 lg:hidden">
        <Logo />
      </div>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-bold tracking-tight">登录</h1>
        <p className="text-[13px] text-muted-foreground">登录你的账户</p>
      </div>
      <AuthForm mode="login" />
      <p className="text-center text-[13px] text-muted-foreground">
        还没账户？{' '}
        <Link href="/register" className="font-medium text-primary hover:underline">
          注册
        </Link>
      </p>
    </div>
  )
}
