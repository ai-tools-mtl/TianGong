'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { useAuthStore } from '@/stores/auth'

/**
 * Admin 子树布局。
 *
 * 职责：角色守卫——非 admin 用户被踢到 /dashboard（防手敲 /admin/users 等）。
 * auth store 在 (app)/layout.tsx 已通过 api.me() 填好，这里只判角色。
 *
 * 导航统一：admin 区域不再有独立 sidebar，顶栏 Navbar 在 /admin/* 下
 * 整组切换为 admin 功能项（概览/用户/内容/审核/控制台）。
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)

  // user 可能还在 (app)/layout.tsx 的 me() 加载中（null），此时不踢，等上层加载完。
  useEffect(() => {
    if (user && user.role !== 'admin') {
      router.replace('/dashboard')
    }
  }, [user, router])

  // 加载中或角色不符时不渲染 admin 内容，避免闪烁暴露。
  if (!user || user.role !== 'admin') {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-muted-foreground">
        加载中...
      </div>
    )
  }

  return <>{children}</>
}
