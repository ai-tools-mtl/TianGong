import { AdminTemplateManager } from '@/components/admin/admin-template-manager'

/**
 * /admin/content/templates 内置模板管理（refactor/admin-ia-phase3 切片 B）。
 *
 * 阶段 1 留的占位页填实。渲染 AdminTemplateManager 组件：
 *   - 上传 docx → 解析为草稿模板（is_system=True, status='draft'）
 *   - 改状态（draft→published→offline→published）
 *   - 删除（draft/offline 可删，published 必须先下线）
 */
export default function AdminTemplatesPage() {
  return <AdminTemplateManager />
}
