'use client'

import type { Editor } from '@tiptap/react'

import { Button } from '@/components/ui/button'

interface ToolbarProps {
  editor: Editor
}

export function Toolbar({ editor }: ToolbarProps) {
  if (!editor) return null

  const tools = [
    { label: 'B', action: () => editor.chain().focus().toggleBold().run(), active: editor.isActive('bold') },
    { label: 'I', action: () => editor.chain().focus().toggleItalic().run(), active: editor.isActive('italic') },
    { label: 'H2', action: () => editor.chain().focus().toggleHeading({ level: 2 }).run(), active: editor.isActive('heading', { level: 2 }) },
    { label: 'H3', action: () => editor.chain().focus().toggleHeading({ level: 3 }).run(), active: editor.isActive('heading', { level: 3 }) },
    { label: '• 列表', action: () => editor.chain().focus().toggleBulletList().run(), active: editor.isActive('bulletList') },
    { label: '1. 列表', action: () => editor.chain().focus().toggleOrderedList().run(), active: editor.isActive('orderedList') },
  ]

  return (
    <div className="flex flex-wrap gap-1 border-b p-2">
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
    </div>
  )
}
