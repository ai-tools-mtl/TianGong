'use client'

import { FileText } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

import { cn } from '@/lib/utils'

/** 草稿大纲单章结构（后端 outline_extractor 输出）。 */
type OutlineChapter = { title: string; content: string }

interface OutlinePreviewProps {
  /** 后端 conversation.draft_outline：{key: {title, content}}，可能为 null/undefined。 */
  outline: Record<string, OutlineChapter> | null | undefined
  /** 是否正在等待提取（对话发送后、done 前）。用于展示「梳理中」态。 */
  extracting?: boolean
  /** 面板宽度（px）。由父组件拖拽手柄控制，默认 320。 */
  width?: number
}

// 8 章 key + 顺序（与后端 seed_service.DEFAULT_STRUCTURE 一致，单一来源对齐）
const CHAPTERS: { key: string; title: string }[] = [
  { key: 'name', title: '发明名称' },
  { key: 'field', title: '技术领域' },
  { key: 'background', title: '背景技术' },
  { key: 'problem', title: '发明目的与技术问题' },
  { key: 'solution', title: '技术方案' },
  { key: 'effect', title: '有益效果' },
  { key: 'drawings', title: '附图说明' },
  { key: 'embodiment', title: '具体实施方式' },
]

export function OutlinePreview({ outline, extracting, width = 320 }: OutlinePreviewProps) {
  const filledCount = CHAPTERS.filter((c) => outline?.[c.key]?.content?.trim()).length

  return (
    <div
      className="flex h-full shrink-0 flex-col bg-background"
      style={{ width: `${width}px`, borderLeft: '1px solid var(--hairline)' }}
    >
      {/* 头部：标题 + 填充进度 */}
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--hairline)' }}>
        <div className="flex items-center gap-2">
          <FileText className="size-4 text-muted-foreground" />
          <span className="text-[13px] font-medium tracking-tight">文档预览</span>
        </div>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {filledCount}/{CHAPTERS.length}
        </span>
      </div>

      {/* 8 章列表（统一面板 + hairline 分隔，Apple 风格）*/}
      <div className="flex-1 overflow-y-auto">
        {CHAPTERS.map((c, i) => {
          const ch = outline?.[c.key]
          const content = ch?.content?.trim() ?? ''
          const isFilled = !!content
          return (
            <div
              key={c.key}
              className="px-4 py-3"
              style={i < CHAPTERS.length - 1 ? { borderBottom: '1px solid var(--hairline)' } : undefined}
            >
              <div className="mb-1 flex items-center gap-2">
                <span className="text-[11px] tabular-nums text-muted-foreground/70">{i + 1}</span>
                <span className={cn('text-[12px] font-medium', isFilled ? 'text-foreground' : 'text-muted-foreground')}>
                  {c.title}
                </span>
                {isFilled && (
                  <span
                    aria-hidden
                    className="size-1.5 rounded-full"
                    style={{ background: 'var(--primary)' }}
                  />
                )}
              </div>
              {isFilled ? (
                <div className="prose prose-sm max-w-none text-[12.5px] leading-relaxed dark:prose-invert">
                  <ReactMarkdown>{content}</ReactMarkdown>
                </div>
              ) : (
                <p className="text-[12px] italic text-muted-foreground/50">
                  {extracting ? '梳理中…' : '待对话中补充'}
                </p>
              )}
            </div>
          )
        })}
      </div>

      {/* 底部说明 */}
      <div className="px-4 py-2.5 text-[11px] leading-relaxed text-muted-foreground/70" style={{ borderTop: '1px solid var(--hairline)' }}>
        预览随对话实时梳理，非最终内容。
        <br />
        信息充分后可一键生成完整初稿。
      </div>
    </div>
  )
}
