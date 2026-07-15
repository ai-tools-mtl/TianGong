import { TagEditor } from '@/components/tag-editor'
import { PageHeader, PageShell } from '@/components/page-shell'

export default function TagsPage() {
  return (
    <PageShell>
      <PageHeader title="标签管理" description="管理你的项目标签词表" />
      <div className="py-6">
        <TagEditor />
      </div>
    </PageShell>
  )
}
