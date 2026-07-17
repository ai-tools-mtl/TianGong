'use client'

import type { Editor } from '@tiptap/react'
import { ImageIcon } from 'lucide-react'
import { useRef } from 'react'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

interface ToolbarProps {
  editor: Editor
  sectionId: string
}

export function Toolbar({ editor, sectionId }: ToolbarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)

  if (!editor) return null

  const tools = [
    { label: 'B', action: () => editor.chain().focus().toggleBold().run(), active: editor.isActive('bold') },
    { label: 'I', action: () => editor.chain().focus().toggleItalic().run(), active: editor.isActive('italic') },
    { label: 'H2', action: () => editor.chain().focus().toggleHeading({ level: 2 }).run(), active: editor.isActive('heading', { level: 2 }) },
    { label: 'H3', action: () => editor.chain().focus().toggleHeading({ level: 3 }).run(), active: editor.isActive('heading', { level: 3 }) },
    { label: '• 列表', action: () => editor.chain().focus().toggleBulletList().run(), active: editor.isActive('bulletList') },
    { label: '1. 列表', action: () => editor.chain().focus().toggleOrderedList().run(), active: editor.isActive('orderedList') },
  ]

  async function handleUploadImage(file: File) {
    try {
      const attachment = await api.uploadAttachment(sectionId, file)
      const src = api.attachmentUrl(attachment.project_id, attachment.id)
      editor.chain().focus().setImage({ src, alt: attachment.filename }).run()
    } catch {
      // 上传失败静默处理
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1 border-b p-2">
      {tools.map((t) => (
        <Button
          key={t.label}
          variant={t.active ? 'default' : 'ghost'}
          size="sm"
          onClick={t.action}
          type="button"
        >
          {t.label}
        </Button>
      ))}

      <span className="mx-1 h-4 w-px bg-border" />

      <Button
        variant="ghost"
        size="sm"
        onClick={() => fileInputRef.current?.click()}
        type="button"
        title="插入图片"
      >
        <ImageIcon className="size-4" />
      </Button>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/gif"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) handleUploadImage(file)
          e.target.value = ''
        }}
      />
    </div>
  )
}
