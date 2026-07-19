import { AdminSidebar } from '@/components/admin/sidebar'

/**
 * Admin 区域外壳：左侧 sidebar + 右侧主区（refactor/admin-ia-phase1）。
 *
 * 复用 (app)/layout.tsx 的顶部 Navbar（不隐藏），admin 子树在此处加 sidebar。
 * 主区不套 PageShell——各页面自行用 PageShell 控制宽度。
 */
export function AdminShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-7xl">
      <AdminSidebar />
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  )
}
