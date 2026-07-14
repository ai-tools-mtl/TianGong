'use client'

import { useRouter } from 'next/navigation'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useDeleteProject } from '@/lib/queries'
import type { Project } from '@/types/api'

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  in_progress: '进行中',
  completed: '已完成',
  archived: '已归档',
}

export function ProjectCard({ project }: { project: Project }) {
  const router = useRouter()
  const del = useDeleteProject()

  function handleDelete() {
    if (!confirm(`确认删除「${project.title}」？此操作不可恢复。`)) return
    del.mutate(project.id, {
      onSuccess: () => toast.success('已删除'),
      onError: () => toast.error('删除失败'),
    })
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base cursor-pointer" onClick={() => router.push(`/projects/${project.id}`)}>
          {project.title}
        </CardTitle>
        <Badge variant="secondary">{STATUS_LABEL[project.status] || project.status}</Badge>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-xs text-muted-foreground">
          阶段：{project.stage} · 进度 {project.progress_pct}%
        </p>
        <p className="text-xs text-muted-foreground">
          更新于 {new Date(project.updated_at).toLocaleString('zh-CN')}
        </p>
        <Button variant="ghost" size="sm" className="text-destructive" onClick={handleDelete} disabled={del.isPending}>
          删除
        </Button>
      </CardContent>
    </Card>
  )
}
