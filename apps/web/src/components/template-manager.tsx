'use client'

import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useTemplates } from '@/lib/queries'
import type { TemplateSummary } from '@/types/api'

export function TemplateManager() {
  const { data, isLoading, refetch } = useTemplates()
  const templates: TemplateSummary[] = data ?? []
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      await api.uploadTemplate(file)
      toast.success('模板上传成功')
      refetch()
    } catch {
      toast.error('上传失败')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  if (isLoading) return <p className="text-muted-foreground">加载中...</p>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">模板管理</h1>
        <div>
          <input ref={fileRef} type="file" accept=".docx" onChange={handleUpload} className="hidden" />
          <Button onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? '上传中...' : '上传 Word 模板'}
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        {templates?.map((t) => (
          <div key={t.id} className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">{t.name}</span>
                {t.is_system && <Badge variant="secondary">系统</Badge>}
                {t.is_default && <Badge>默认</Badge>}
              </div>
              <p className="text-xs text-muted-foreground">{t.section_count} 个章节</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
