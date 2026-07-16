'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { MoreHorizontal, Tag as TagIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { DeleteConfirmDialog } from '@/components/delete-confirm-dialog'
import { ProjectTagDialog } from '@/components/project-tag-dialog'
import { RenameDialog } from '@/components/rename-dialog'
import { useArchiveProject, useTags } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { Project, Tag } from '@/types/api'

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  in_progress: '进行中',
  completed: '已完成',
  archived: '已归档',
}

// 生命周期阶段：默认 disclosure（交底书阶段）不显示，避免死值噪音；
// 进入答复等后续阶段时才显示中文标签
const STAGE_LABEL: Record<string, string> = {
  response: '审查答复',
}

const STATUS_TONE: Record<string, string> = {
  draft: 'bg-muted text-muted-foreground',
  in_progress: 'bg-info/10 text-info',
  completed: 'bg-success/10 text-success',
  archived: 'bg-muted text-muted-foreground',
}

export function ProjectCard({ project }: { project: Project }) {
  const router = useRouter()
  const archive = useArchiveProject()
  const { data: allTags } = useTags()
  const [renameOpen, setRenameOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [tagOpen, setTagOpen] = useState(false)

  // 解析项目上的标签 id → 名称
  const tagMap = new Map((allTags ?? []).map((t: Tag) => [t.id, t.name]))
  const projectTags = (project.tags ?? []).map((id) => tagMap.get(id)).filter(Boolean) as string[]

  function handleArchive() {
    archive.mutate(project.id, {
      onSuccess: (res) => toast.success(`已归档到知识库（${res.chunks} 个知识块）`),
      onError: () => toast.error('归档失败'),
    })
  }

  return (
    <>
      <Card
        className="group cursor-pointer transition-colors hover:border-foreground/20"
        onClick={() => router.push(`/projects/${project.id}`)}
      >
        <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
          <CardTitle className="text-[15px] leading-snug">{project.title}</CardTitle>
          <div className="flex items-center gap-1">
            <Badge
              variant="secondary"
              className={cn('shrink-0', STATUS_TONE[project.status])}
            >
              {STATUS_LABEL[project.status] || project.status}
            </Badge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="opacity-40 hover:opacity-100"
                  onClick={(e) => e.stopPropagation()}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                <DropdownMenuItem onClick={() => setRenameOpen(true)}>
                  重命名
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTagOpen(true)}>
                  <TagIcon className="mr-2 size-4" />
                  标签
                </DropdownMenuItem>
                {(project.status === 'completed' || project.status === 'archived') && (
                  <DropdownMenuItem onClick={handleArchive} disabled={archive.isPending}>
                    {project.status === 'archived' ? '更新知识库' : '归档'}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={() => setDeleteOpen(true)}
                >
                  删除
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span>{STAGE_LABEL[project.stage]}</span>
              <span className="tabular-nums">{project.progress_pct}%</span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${project.progress_pct}%` }}
              />
            </div>
          </div>
          {projectTags.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {projectTags.map((name) => (
                <Badge key={name} variant="outline" className="text-[10px] font-normal">
                  {name}
                </Badge>
              ))}
            </div>
          )}
          <div className="flex items-center justify-between pt-1">
            <p className="text-[11px] text-muted-foreground">
              {new Date(project.updated_at).toLocaleDateString('zh-CN')}
            </p>
          </div>
        </CardContent>
      </Card>

      <RenameDialog
        projectId={project.id}
        currentTitle={project.title}
        open={renameOpen}
        onOpenChange={setRenameOpen}
      />
      <ProjectTagDialog
        projectId={project.id}
        open={tagOpen}
        onOpenChange={setTagOpen}
        attachedTagIds={project.tags ?? []}
      />
      <DeleteConfirmDialog
        projectId={project.id}
        projectTitle={project.title}
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
      />
    </>
  )
}
