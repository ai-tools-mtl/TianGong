'use client'

import { CreateProjectDialog } from '@/components/create-project-dialog'
import { PageHeader, PageShell } from '@/components/page-shell'
import { ProjectCard } from '@/components/project-card'
import { useProjects } from '@/lib/queries'
import type { Project } from '@/types/api'

export function ProjectList() {
  const { data, isLoading, isError } = useProjects()
  const projects: Project[] = data ?? []

  return (
    <PageShell>
      <PageHeader title="我的项目" description="管理你的专利交底书">
        <CreateProjectDialog />
      </PageHeader>

      <div className="py-6">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">加载中...</p>
        ) : isError ? (
          <p className="text-sm text-destructive">加载失败，请重试</p>
        ) : projects.length === 0 ? (
          <div className="rounded-lg border border-dashed p-12 text-center text-sm text-muted-foreground">
            还没有项目，点击右上角「新建项目」开始你的第一份交底书
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
