'use client'

import { ImageIcon, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

interface FigureUploadProps {
  sectionId: string
  projectId: string
  /** 上传成功后把图片插入编辑器 */
  onInsertImage: (src: string, alt: string) => void
}

export function FigureUpload({ sectionId, projectId, onInsertImage }: FigureUploadProps) {
  const [uploading, setUploading] = useState(false)

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const att = await api.uploadAttachment(sectionId, file)
      const src = api.attachmentUrl(projectId, att.id)
      onInsertImage(src, file.name)
      toast.success('图片已上传')
    } catch {
      toast.error('上传失败（仅支持 PNG/JPEG/GIF，≤10MB）')
    } finally {
      setUploading(false)
      e.target.value = '' // 允许重复选同一文件
    }
  }

  return (
    <Button variant="outline" size="sm" className="h-8 gap-1.5" disabled={uploading} asChild>
      <label className="cursor-pointer">
        {uploading ? <Loader2 className="size-3.5 animate-spin" /> : <ImageIcon className="size-3.5" />}
        {uploading ? '上传中...' : '上传图片'}
        <input type="file" accept="image/png,image/jpeg,image/gif" onChange={handleFile} className="hidden" />
      </label>
    </Button>
  )
}
