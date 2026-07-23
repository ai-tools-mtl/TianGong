import { redirect } from 'next/navigation'

/**
 * /admin/settings redirect 到控制台 LLM 配置（refactor/admin-ia-phase3）。
 *
 * 产品立场：admin 强制使用全局 Key（无自定义配置），LLM 配置统一走「控制台 > LLM 配置」。
 * 本路由保留用于兼容老书签/历史链接，避免 admin 工作区出现 404。
 *
 * 用 server component 的 redirect() 而非 client router.replace，
 * 无中间渲染、浏览器直接收到 307。
 */
export default function AdminSettingsPage() {
  redirect('/admin/console/llm')
}
