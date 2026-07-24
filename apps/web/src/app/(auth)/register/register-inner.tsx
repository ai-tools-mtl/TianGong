'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'

import { AuthForm } from '@/components/auth-form'
import { Logo } from '@/components/logo'

/**
 * 注册页内容。内部产品化:无公开入口,仅凭邀请码直达(/register?code=XXXX)。
 * useSearchParams 需 Suspense 包裹(见 page.tsx)。
 */
export function RegisterInner() {
  const searchParams = useSearchParams()
  const code = searchParams.get('code') ?? undefined

  return (
    <div className="space-y-6">
      <div className="space-y-2 lg:hidden">
        <Logo />
      </div>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-bold tracking-tight">凭邀请码开通账户</h1>
        <p className="text-[13px] text-muted-foreground">
          内部产品,需邀请码注册
        </p>
      </div>
      <AuthForm mode="register" defaultInviteCode={code} />
      <p className="text-center text-[13px] text-muted-foreground">
        已有账户？{' '}
        <Link href="/login" className="font-medium text-primary hover:underline">
          登录
        </Link>
      </p>
    </div>
  )
}
