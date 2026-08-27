'use client'

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Image from '@tiptap/extension-image'
import { TableKit } from '@tiptap/extension-table'
import { forwardRef, useImperativeHandle, useState, type MouseEvent } from 'react'

import { ImageLightbox } from './image-lightbox'
import { SelectionBubbleMenu } from './selection-bubble-menu'
import { Toolbar } from './toolbar'

/** 附图说明清单块的定位标记（insertDrawingList 生成/替换的块首行）。 */
const DRAWING_LIST_MARKER = '【附图清单（自动生成）】'

export interface TiptapEditorRef {
  insertImage: (src: string, alt: string) => void
  /** 插图带图注（图号系统 V1：图片 + 紧随的「图N：…」段落） */
  insertImageWithCaption: (src: string, alt: string, caption: string) => void
  /** 插入/替换附图说明清单块（标记段落 + 图N：行；重复点击替换旧块） */
  insertDrawingList: (lines: string[]) => void
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
    const [lightbox, setLightbox] = useState<{ src: string; alt: string } | null>(null)
    const editor = useEditor({
      extensions: [
        StarterKit,
        Placeholder.configure({ placeholder: '在此撰写内容...' }),
        Image,
        TableKit,
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
      insertImageWithCaption: (src: string, alt: string, caption: string) => {
        editor
          ?.chain()
          .focus()
          .setImage({ src, alt })
          .insertContent({
            type: 'paragraph',
            content: [{ type: 'text', text: caption }],
          })
          .run()
      },
      insertDrawingList: (lines: string[]) => {
        if (!editor || lines.length === 0) return
        // 找既有清单块范围：标记段落 + 其后**从 图1 起严格连续递增**的「图N：」段落
        // （图号系统 V1，D3 按钮化——用户手改过的其他段落不动，只替换系统生成的块）。
        // 系统生成的块恒为 1..n 连续（服务端删除重排保证无空洞），故以连续编号锚定
        // 块边界；用户手写的零散「图K」段落只要不恰好接续编号就不会被吞进替换范围。
        const paragraphs = [
          { type: 'paragraph', content: [{ type: 'text', text: DRAWING_LIST_MARKER }] },
          ...lines.map((l) => ({ type: 'paragraph', content: [{ type: 'text', text: l }] })),
        ]
        let inBlock = false
        let expectedNum = 1
        let from = 0
        let to = 0
        editor.state.doc.forEach((node, offset) => {
          const text = node.textContent?.trim() ?? ''
          if (!inBlock && text === DRAWING_LIST_MARKER) {
            inBlock = true
            expectedNum = 1
            from = offset
            to = offset + node.nodeSize
          } else if (inBlock) {
            const m = /^图(\d+)[:：]/.exec(text)
            if (m && Number(m[1]) === expectedNum) {
              to = offset + node.nodeSize
              expectedNum += 1
            } else {
              inBlock = false // 块结束（编号断档或非清单段落截断）
            }
          }
        })
        if (to > from) {
          editor.chain().focus().insertContentAt({ from, to }, paragraphs).run()
        } else {
          // 首次生成：追加到文档末尾
          editor
            .chain()
            .focus()
            .insertContentAt(editor.state.doc.content.size, paragraphs)
            .run()
        }
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

    // 图片点击放大（事件委托到容器，不给 Image 节点写自定义 NodeView 保持轻量）。
    // 只读态（连续模式非激活章/预览）单击直接放大；编辑态单击保留「选中节点」
    // 语义（拖拽/删除节点），双击才放大。图片由 globals.css 的
    // .tiptap-img-scope 规则统一缩略展示。
    function openImageLightbox(e: MouseEvent) {
      const el = e.target as HTMLElement
      if (el.tagName !== 'IMG') return
      e.preventDefault()
      e.stopPropagation()
      setLightbox({ src: (el as HTMLImageElement).src, alt: (el as HTMLImageElement).alt })
    }

    if (!editor) return null

    return (
      <div
        className="tiptap-img-scope overflow-hidden rounded-xl border bg-card"
        onClick={editable ? undefined : openImageLightbox}
        onDoubleClick={editable ? openImageLightbox : undefined}
      >
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
        {lightbox && (
          <ImageLightbox
            src={lightbox.src}
            alt={lightbox.alt}
            onClose={() => setLightbox(null)}
          />
        )}
      </div>
    )
  },
)
