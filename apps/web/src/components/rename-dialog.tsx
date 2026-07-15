'use client'

import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useUpdateProject } from '@/lib/queries'

interface RenameDialogProps {
  projectId: string
  currentTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function RenameDialog({ projectId, currentTitle, open, onOpenChange }: RenameDialogProps) {
  // 通过 key 在每次打开时重置内部表单状态，避免在 effect 中调用 setState
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>重命名项目</DialogTitle>
        </DialogHeader>
        {open ? (
          <RenameForm
            key={projectId}
            projectId={projectId}
            currentTitle={currentTitle}
            onOpenChange={onOpenChange}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

interface RenameFormProps {
  projectId: string
  currentTitle: string
  onOpenChange: (open: boolean) => void
}

function RenameForm({ projectId, currentTitle, onOpenChange }: RenameFormProps) {
  const update = useUpdateProject()
  const [title, setTitle] = useState(currentTitle)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim() || title.trim() === currentTitle) {
      onOpenChange(false)
      return
    }
    update.mutate(
      { id: projectId, data: { title: title.trim() } },
      {
        onSuccess: () => {
          toast.success('已重命名')
          onOpenChange(false)
        },
        onError: () => toast.error('重命名失败'),
      },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="rename-title">项目名称</Label>
        <Input
          id="rename-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          autoFocus
        />
      </div>
      <DialogFooter>
        <Button type="submit" disabled={update.isPending || !title.trim()}>
          {update.isPending ? '保存中...' : '保存'}
        </Button>
      </DialogFooter>
    </form>
  )
}
