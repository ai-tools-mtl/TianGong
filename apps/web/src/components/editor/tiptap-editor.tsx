'use client'

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Image from '@tiptap/extension-image'
import { forwardRef, useImperativeHandle } from 'react'

import { Toolbar } from './toolbar'

export interface TiptapEditorRef {
  insertImage: (src: string, alt: string) => void
}

interface TiptapEditorProps {
  content?: object | null
  onChange?: (json: object) => void
  editable?: boolean
  sectionId?: string
}

export const TiptapEditor = forwardRef<TiptapEditorRef, TiptapEditorProps>(
  function TiptapEditor({ content, onChange, editable = true, sectionId = '' }, ref) {
    const editor = useEditor({
      extensions: [
        StarterKit,
        Placeholder.configure({ placeholder: '在此撰写内容...' }),
        Image,
      ],
      content: content || undefined,
      editable,
      onUpdate: ({ editor }) => {
        onChange?.(editor.getJSON())
      },
    })

    useImperativeHandle(ref, () => ({
      insertImage: (src: string, alt: string) => {
        editor?.chain().focus().setImage({ src, alt }).run()
      },
    }))

    if (!editor) return null

    return (
      <div className="overflow-hidden rounded-lg border bg-card">
        {editable && <Toolbar editor={editor} sectionId={sectionId} />}
        <EditorContent
          editor={editor}
          className="prose prose-sm tiptap max-w-none px-5 py-4 focus:outline-none"
        />
      </div>
    )
  },
)
