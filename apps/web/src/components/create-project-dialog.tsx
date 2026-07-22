'use client'

import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { useCreateProject, useTemplates } from '@/lib/queries'
import type { TemplateSummary } from '@/types/api'

export function CreateProjectDialog() {
  const create = useCreateProject()
  const { data: templates } = useTemplates()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [templateId, setTemplateId] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    create.mutate(
      {
        title: title.trim(),
        template_id: templateId || undefined,
      },
      {
        onSuccess: () => {
          toast.success('项目已创建')
          setTitle('')
          setTemplateId('')
          setOpen(false)
        },
        onError: () => toast.error('创建失败'),
      },
    )
  }

  const templateList = templates ?? []

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>新建项目</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建交底书项目</DialogTitle>
          <DialogDescription>
            选择模板后将按模板预设的章节结构创建项目。
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="title">项目名称</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="给你的发明起个名字"
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="template">章节模板</Label>
            <Select
              id="template"
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
              className="text-[13px]"
            >
              <option value="">不选模板（创建空项目）</option>
              {templateList.map((t: TemplateSummary) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {t.is_default ? '（默认）' : ''} — {t.section_count} 个章节
                </option>
              ))}
            </Select>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || !title.trim()}>
              {create.isPending ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  创建中...
                </>
              ) : (
                '创建'
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
