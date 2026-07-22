import { Building } from 'lucide-react'

import { PageHeader, PageShell } from '@/components/page-shell'
import { EmptyState } from '@/components/ui/empty-state'

/**
 * 阶段 2 待实现模块的占位页（refactor/admin-ia-phase1）。
 *
 * 本阶段只立 IA 骨架（路由 + sidebar + 落地页），子页内容（Users 列表/操作、
 * Console LLM 配置/统计/审计、Content 模板/知识库直传）留待阶段 2 填。
 * 用同一个占位组件避免重复样板代码。
 */
export function UnderConstruction({
  title,
  description = '本模块在阶段 2 实现',
}: {
  title: string
  description?: string
}) {
  return (
    <PageShell>
      <PageHeader title={title} description={description} />
      <div className="py-10">
        <EmptyState icon={<Building className="size-5" />} title={title} description={description} />
      </div>
    </PageShell>
  )
}
