import Link from 'next/link'

import { AuthForm } from '@/components/auth-form'
import { Logo } from '@/components/logo'

export default function RegisterPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2 lg:hidden">
        <Logo />
      </div>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-bold tracking-tight">创建账户</h1>
        <p className="text-[13px] text-muted-foreground">开始你的第一份交底书</p>
      </div>
      <AuthForm mode="register" />
      <p className="text-center text-[13px] text-muted-foreground">
        已有账户？{' '}
        <Link href="/login" className="font-medium text-primary hover:underline">
          登录
        </Link>
      </p>
    </div>
  )
}
