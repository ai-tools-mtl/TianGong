'use client'

import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useAttachProjectTag, useDetachProjectTag, useTags } from '@/lib/queries'
import type { Tag } from '@/types/api'

interface ProjectTagDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  attachedTagIds: string[]
}

export function ProjectTagDialog({ projectId, open, onOpenChange, attachedTagIds }: ProjectTagDialogProps) {
  const { data: tags, isLoading } = useTags()
  const attach = useAttachProjectTag()
  const detach = useDetachProjectTag()
  const attachedSet = new Set(attachedTagIds)

  function handleToggle(tagId: string, isAttached: boolean) {
    const mutation = isAttached ? detach : attach
    mutation.mutate(
      { projectId, tagId },
      {
        onError: () => toast.error(isAttached ? '摘除失败' : '贴标签失败'),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>管理标签</DialogTitle>
          <DialogDescription>
            为本项目贴标签。标签可在「标签管理」页创建。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">加载中...</p>
          ) : !tags || tags.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              还没有标签，请先到「标签管理」页创建标签。
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {tags.map((tag: Tag) => {
                const isAttached = attachedSet.has(tag.id)
                return (
                  <Badge
                    key={tag.id}
                    variant={isAttached ? 'default' : 'outline'}
                    className="cursor-pointer select-none"
                    onClick={() => handleToggle(tag.id, isAttached)}
                  >
                    {tag.name}
                  </Badge>
                )
              })}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
