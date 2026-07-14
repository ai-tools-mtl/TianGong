'use client'

import { CreateProjectDialog } from '@/components/create-project-dialog'
import { ProjectCard } from '@/components/project-card'
import { useProjects } from '@/lib/queries'
import type { Project } from '@/types/api'

export function ProjectList() {
  const { data, isLoading, isError } = useProjects()
  const projects: Project[] = data ?? []

  if (isLoading) return <p className="text-muted-foreground">加载中...</p>
  if (isError) return <p className="text-destructive">加载失败，请重试</p>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">我的项目</h1>
        <CreateProjectDialog />
      </div>

      {projects.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
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
  )
}
