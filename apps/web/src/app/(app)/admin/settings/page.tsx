import { UnderConstruction } from '@/components/admin/under-construction'

/**
 * /admin/settings 占位页（refactor/admin-ia-phase1 第 1 轮）。
 *
 * 第 2 轮会抽取 ByokSettings 共享组件，与 /settings 共用同一份 BYOK 表单。
 * 当前先占位，避免 sidebar 上的「我的设置」点击 404。
 */
export default function AdminSettingsPage() {
  return <UnderConstruction title="我的设置" description="admin 自身 BYOK 配置（与 /settings 共用）" />
}
