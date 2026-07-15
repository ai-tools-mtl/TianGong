'use client'

import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useDeleteProject } from '@/lib/queries'

interface DeleteConfirmDialogProps {
  projectId: string
  projectTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DeleteConfirmDialog({ projectId, projectTitle, open, onOpenChange }: DeleteConfirmDialogProps) {
  const del = useDeleteProject()

  function handleConfirm() {
    del.mutate(projectId, {
      onSuccess: () => {
        toast.success('已删除')
        onOpenChange(false)
      },
      onError: () => toast.error('删除失败'),
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>确认删除</DialogTitle>
          <DialogDescription>
            确认删除「{projectTitle}」？此操作不可恢复，项目及其所有章节将被永久删除。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={del.isPending}
          >
            {del.isPending ? '删除中...' : '确认删除'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
