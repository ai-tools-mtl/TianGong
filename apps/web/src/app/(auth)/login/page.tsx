import Link from 'next/link'

import { AuthForm } from '@/components/auth-form'

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold">天工 TianGong</h1>
          <p className="text-sm text-muted-foreground">登录你的账户</p>
        </div>
        <AuthForm mode="login" />
        <p className="text-center text-sm text-muted-foreground">
          还没账户？{' '}
          <Link href="/register" className="text-primary underline">注册</Link>
        </p>
      </div>
    </main>
  )
}
