'use client'

import type { ReactNode } from 'react'

import { TiptapEditor } from '@/components/editor/tiptap-editor'
import type { TiptapEditorRef } from '@/components/editor/tiptap-editor'
import { SECTION_STATUS_LABEL, STATUS_DOT } from '@/components/section-outline'
import { cn } from '@/lib/utils'
import type { Section } from '@/types/api'

interface SectionBlockProps {
  section: Section
  /** 章节序号（从 1 开始，按大纲顺序） */
  index: number
  isActive: boolean
  /** 挂载初始内容：页面统一传 contentCache.get(id) ?? section.content（spec §3.5） */
  initialContent: object | null
  onActivate: (id: string) => void
  /** 回调 ref：把编辑器实例登记进页面 per-section 引用表（spec §3.7） */
  editorRef: (r: TiptapEditorRef | null) => void
  /** 块根节点引用：页面点击激活后 scrollIntoView 用 */
  rootRef?: (el: HTMLDivElement | null) => void
  /** 章块动作槽（drawings 章的 FigureUpload/FigureGenerate，渲染在章头之下编辑器之上） */
  figureSlot?: ReactNode
  onChange?: (json: object) => void
  onRewriteComplete?: (aiOutput: string, selectedText: string) => void
}

/**
 * 连续文档视图的章节块（spec 2026-08-18 §3.3）：
 * 章头（序号·标题 + 状态徽标 + 动作槽）+ 激活章可编辑 / 其余只读的编辑器。
 *
 * key 由页面传入编辑器内部以 `${id}-${isActive?'edit':'read'}` 强制重挂载，
 * 激活切换不残留 undo 栈/选区。正文点击（onMouseDownCapture）也可激活，
 * 但激活后光标不自动落位，需第二次点击定位——v1 已知瑕点（spec §3.3）。
 */
export function SectionBlock({
  section,
  index,
  isActive,
  initialContent,
  onActivate,
  editorRef,
  rootRef,
  figureSlot,
  onChange,
  onRewriteComplete,
}: SectionBlockProps) {
  const status = section.status ?? 'empty'
  return (
    <div
      ref={rootRef}
      data-section-id={section.id}
      className="space-y-2"
      onMouseDownCapture={() => {
        if (!isActive) onActivate(section.id)
      }}
    >
      <div className="flex items-center gap-2 px-1">
        <span
          className={cn(
            'text-sm font-medium tracking-tight',
            isActive ? 'text-foreground' : 'text-muted-foreground',
          )}
        >
          {index + 1}. {section.title}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">
          <span className={cn('size-1.5 rounded-full', STATUS_DOT[status] || STATUS_DOT.empty)} />
          {SECTION_STATUS_LABEL[status] ?? SECTION_STATUS_LABEL.empty}
        </span>
      </div>
      {figureSlot && <div className="space-y-2">{figureSlot}</div>}
      <div
        className={cn(
          'rounded-xl',
          isActive && 'ring-2 ring-ring ring-offset-2 ring-offset-background',
        )}
      >
        <TiptapEditor
          key={`${section.id}-${isActive ? 'edit' : 'read'}`}
          ref={editorRef}
          content={initialContent}
          editable={isActive}
          sectionId={isActive ? section.id : undefined}
          onChange={isActive ? onChange : undefined}
          onRewriteComplete={isActive ? onRewriteComplete : undefined}
        />
      </div>
    </div>
  )
}
