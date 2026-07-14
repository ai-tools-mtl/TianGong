'use client'

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'

import { Toolbar } from './toolbar'

interface TiptapEditorProps {
  content?: object | null
  onChange?: (json: object) => void
  editable?: boolean
}

export function TiptapEditor({ content, onChange, editable = true }: TiptapEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({ placeholder: '在此撰写内容...' }),
    ],
    content: content || undefined,
    editable,
    onUpdate: ({ editor }) => {
      onChange?.(editor.getJSON())
    },
  })

  if (!editor) return null

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <Toolbar editor={editor} />
      <EditorContent
        editor={editor}
        className="prose prose-sm tiptap max-w-none p-5 min-h-[400px] focus:outline-none"
      />
    </div>
  )
}
