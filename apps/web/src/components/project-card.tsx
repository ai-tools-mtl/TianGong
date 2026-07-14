'use client'

import { useRouter } from 'next/navigation'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useArchiveProject, useDeleteProject } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { Project } from '@/types/api'

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  in_progress: '进行中',
  completed: '已完成',
  archived: '已归档',
}

const STATUS_TONE: Record<string, string> = {
  draft: 'bg-muted text-muted-foreground',
  in_progress: 'bg-info/10 text-info',
  completed: 'bg-success/10 text-success',
  archived: 'bg-muted text-muted-foreground',
}

export function ProjectCard({ project }: { project: Project }) {
  const router = useRouter()
  const del = useDeleteProject()
  const archive = useArchiveProject()

  function handleArchive() {
    archive.mutate(project.id, {
      onSuccess: (res) => toast.success(`已归档到知识库（${res.chunks} 个知识块）`),
      onError: () => toast.error('归档失败'),
    })
  }

  function handleDelete() {
    if (!confirm(`确认删除「${project.title}」？此操作不可恢复。`)) return
    del.mutate(project.id, {
      onSuccess: () => toast.success('已删除'),
      onError: () => toast.error('删除失败'),
    })
  }

  return (
    <Card
      className="group cursor-pointer transition-colors hover:border-foreground/20"
      onClick={() => router.push(`/projects/${project.id}`)}
    >
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
        <CardTitle className="text-[15px] leading-snug">{project.title}</CardTitle>
        <Badge
          variant="secondary"
          className={cn('shrink-0', STATUS_TONE[project.status])}
        >
          {STATUS_LABEL[project.status] || project.status}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>{project.stage}</span>
            <span className="tabular-nums">{project.progress_pct}%</span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${project.progress_pct}%` }}
            />
          </div>
        </div>
        <div className="flex items-center justify-between pt-1">
          <p className="text-[11px] text-muted-foreground">
            {new Date(project.updated_at).toLocaleDateString('zh-CN')}
          </p>
          <div
            className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100"
            onClick={(e) => e.stopPropagation()}
          >
            {(project.status === 'completed' || project.status === 'archived') && (
              <Button
                variant="ghost"
                size="xs"
                onClick={handleArchive}
                disabled={archive.isPending}
              >
                {project.status === 'archived' ? '更新' : '归档'}
              </Button>
            )}
            <Button
              variant="ghost"
              size="xs"
              className="text-destructive hover:text-destructive"
              onClick={handleDelete}
              disabled={del.isPending}
            >
              删除
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
