import { Building } from 'lucide-react'

import { PageHeader, PageShell } from '@/components/page-shell'

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
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-16 text-center">
          <Building className="size-8 text-muted-foreground" />
          <div className="text-sm font-medium">{title}</div>
          <p className="max-w-sm text-[13px] text-muted-foreground">
            {description}。当前阶段已立路由与导航骨架，相关能力（原 /admin 主页的操作区）
            会逐步迁移至此。
          </p>
        </div>
      </div>
    </PageShell>
  )
}
