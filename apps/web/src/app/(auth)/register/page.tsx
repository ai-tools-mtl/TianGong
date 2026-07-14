import Link from 'next/link'

import { AuthForm } from '@/components/auth-form'

export default function RegisterPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold">天工 TianGong</h1>
          <p className="text-sm text-muted-foreground">创建新账户</p>
        </div>
        <AuthForm mode="register" />
        <p className="text-center text-sm text-muted-foreground">
          已有账户？{' '}
          <Link href="/login" className="text-primary underline">登录</Link>
        </p>
      </div>
    </main>
  )
}
