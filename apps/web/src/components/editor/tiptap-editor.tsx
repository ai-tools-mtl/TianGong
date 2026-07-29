'use client'

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Image from '@tiptap/extension-image'
import { forwardRef, useImperativeHandle } from 'react'

import { SelectionBubbleMenu } from './selection-bubble-menu'
import { Toolbar } from './toolbar'

export interface TiptapEditorRef {
  insertImage: (src: string, alt: string) => void
  getJSON: () => object
  // 新增（选区重写气泡菜单用，spec §3.1）
  getSelectionText: () => string
  getSelectionCoords: () => { top: number; left: number; bottom: number } | null
  // 显式重置编辑器内容（apply-diff 成功后由 page.tsx 调用）。
  // 不用 useEffect 自动同步 content prop——会和 onChange→save→refetch→content 变→setContent 形成回环。
  resetContent: (content: object) => void
}

interface TiptapEditorProps {
  content?: object | null
  onChange?: (json: object) => void
  editable?: boolean
  sectionId?: string
  /** 选区重写完成时回调（传给 SelectionBubbleMenu） */
  onRewriteComplete?: (aiOutput: string, selectedText: string) => void
}

export const TiptapEditor = forwardRef<TiptapEditorRef, TiptapEditorProps>(
  function TiptapEditor({ content, onChange, editable = true, sectionId = '', onRewriteComplete }, ref) {
    const editor = useEditor({
      extensions: [
        StarterKit,
        Placeholder.configure({ placeholder: '在此撰写内容...' }),
        Image,
      ],
      content: content || undefined,
      editable,
      // Tiptap v3 起默认 false 以避免 SSR hydration mismatch。
      // 本组件已 'use client'，仅在客户端渲染，显式传 true 消除警告并让编辑器首帧即可用。
      immediatelyRender: true,
      onUpdate: ({ editor }) => {
        onChange?.(editor.getJSON())
      },
    })

    useImperativeHandle(ref, () => ({
      insertImage: (src: string, alt: string) => {
        editor?.chain().focus().setImage({ src, alt }).run()
      },
      getJSON: () => editor?.getJSON() ?? {},
      getSelectionText: () => {
        if (!editor) return ''
        const { from, to, empty } = editor.state.selection
        if (empty) return ''
        return editor.state.doc.textBetween(from, to, '\n')
      },
      getSelectionCoords: () => {
        if (!editor) return null
        const { from, to, empty } = editor.state.selection
        if (empty) return null
        // 用 ProseMirror view 的 coordsAtPos 拿视口坐标
        const view = editor.view
        const startCoords = view.coordsAtPos(from)
        const endCoords = view.coordsAtPos(to)
        return {
          top: Math.min(startCoords.top, endCoords.top),
          left: Math.min(startCoords.left, endCoords.left),
          bottom: Math.max(startCoords.bottom, endCoords.bottom),
        }
      },
      resetContent: (content: object) => {
        // emitUpdate: false 避免 setContent 触发 onUpdate → onChange 回环
        // （apply-diff 成功后 page.tsx 已 refetch，编辑器只需同步显示，不需再 save）
        editor?.commands.setContent(content, { emitUpdate: false })
      },
    }))

    if (!editor) return null

    return (
      <div className="overflow-hidden rounded-xl border bg-card">
        {editable && <Toolbar editor={editor} sectionId={sectionId} />}
        <EditorContent
          editor={editor}
          className="prose prose-sm tiptap max-w-none px-5 py-4 focus:outline-none"
        />
        {editable && onRewriteComplete && sectionId && (
          <SelectionBubbleMenu
            sectionId={sectionId}
            getSelectionText={() => {
              if (!editor) return ''
              const { from, to, empty } = editor.state.selection
              if (empty) return ''
              return editor.state.doc.textBetween(from, to, '\n')
            }}
            getSelectionCoords={() => {
              if (!editor) return null
              const { from, to, empty } = editor.state.selection
              if (empty) return null
              const startCoords = editor.view.coordsAtPos(from)
              const endCoords = editor.view.coordsAtPos(to)
              return {
                top: Math.min(startCoords.top, endCoords.top),
                left: Math.min(startCoords.left, endCoords.left),
                bottom: Math.max(startCoords.bottom, endCoords.bottom),
              }
            }}
            onRewriteComplete={onRewriteComplete}
          />
        )}
      </div>
    )
  },
)
