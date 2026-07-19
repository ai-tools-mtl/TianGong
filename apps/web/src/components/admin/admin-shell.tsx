import { AdminSidebar } from '@/components/admin/sidebar'

/**
 * Admin 区域外壳：左侧 sidebar + 右侧主区（refactor/admin-ia-phase1）。
 *
 * 复用 (app)/layout.tsx 的顶部 Navbar（不隐藏），admin 子树在此处加 sidebar。
 * 不在 Shell 层套 max-width：sidebar 要贴视口左边，主区宽度由各页面自行用
 * PageShell 控制可读宽度。
 */
export function AdminShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex w-full">
      <AdminSidebar />
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  )
}
