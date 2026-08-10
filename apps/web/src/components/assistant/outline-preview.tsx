'use client'

import { FileText } from 'lucide-react'
import ReactMarkdown from 'react-markdown'

import { cn } from '@/lib/utils'

/** 草稿大纲单章结构（后端 outline_extractor 输出）。 */
type OutlineChapter = { title: string; content: string; evidence_type?: string }

/** 维度覆盖率（后端 brief_dimensions.compute_coverage 输出，镜像 Coverage 类型）。 */
type Coverage = {
  covered: string[]
  missing: string[]
  ready: boolean
  core_filled: [number, number]
  aligned: boolean
  alignment_detail: Record<string, number>
}

interface OutlinePreviewProps {
  /** 后端 conversation.draft_outline：{key: {title, content}}，可能为 null/undefined。 */
  outline: Record<string, OutlineChapter> | null | undefined
  /** 维度覆盖率（来自 done.coverage）。驱动 ready 判断 + 缺失维度提示。 */
  coverage?: Coverage | null
  /** 是否正在等待提取（对话发送后、done 前）。用于展示「梳理中」态。 */
  extracting?: boolean
  /** 面板宽度（px）。由父组件拖拽手柄控制，默认 320。 */
  width?: number
}

// 8 章 key + 顺序（与后端 seed_service.DEFAULT_STRUCTURE 一致，单一来源对齐）
const CHAPTERS: { key: string; title: string }[] = [
  { key: 'name', title: '名称' },
  { key: 'field', title: '所属技术领域' },
  { key: 'background', title: '背景技术' },
  { key: 'problem', title: '技术问题' },
  { key: 'solution', title: '发明内容' },
  { key: 'effect', title: '有益效果' },
  { key: 'key_points', title: '关键点与保护范围' },
  { key: 'drawings', title: '附图' },
]

// 核心维度（与后端 brief_dimensions.CORE_DIMENSIONS 一致——决定 ready 判断的 5 维）。
// 放在头部覆盖率统计里，与「总章节数」区分。
const CORE_KEYS = new Set(['field', 'background', 'problem', 'solution', 'effect'])

// 维度缺失时的直白提示文案（key → 更口语化的「还需补充」说法）。
const MISSING_HINT: Record<string, string> = {
  field: '技术领域',
  background: '现有技术及其缺点',
  problem: '要解决的技术问题',
  solution: '技术方案轮廓',
  effect: '关键特征与效果',
}

export function OutlinePreview({ outline, coverage, extracting, width = 320 }: OutlinePreviewProps) {
  const filledCount = CHAPTERS.filter((c) => outline?.[c.key]?.content?.trim()).length
  // 核心维度覆盖率（优先用后端算的 coverage，无则本地兜底算）
  const coreFilled = coverage?.core_filled?.[0] ?? CHAPTERS.filter((c) => CORE_KEYS.has(c.key) && outline?.[c.key]?.content?.trim()).length
  const coreTotal = coverage?.core_filled?.[1] ?? [...CORE_KEYS].length

  return (
    <div
      className="flex h-full shrink-0 flex-col bg-background"
      style={{ width: `${width}px`, borderLeft: '1px solid var(--hairline)' }}
    >
      {/* 头部：标题 + 核心维度覆盖率 */}
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--hairline)' }}>
        <div className="flex items-center gap-2">
          <FileText className="size-4 text-muted-foreground" />
          <span className="text-[13px] font-medium tracking-tight">文档预览</span>
        </div>
        <div className="flex items-center gap-2 text-[11px] tabular-nums">
          {coverage && (
            <span
              className={cn('font-medium', coverage.ready ? 'text-primary' : 'text-muted-foreground')}
              title="核心维度覆盖率（决定是否可创建项目）"
            >
              核心 {coreFilled}/{coreTotal}
            </span>
          )}
          <span className="text-muted-foreground/60">{filledCount}/{CHAPTERS.length}</span>
        </div>
      </div>

      {/* 缺失维度提示（coverage 有值且未达标时显示） */}
      {coverage && !coverage.ready && coverage.missing.length > 0 && (
        <div className="px-4 py-2 text-[11px] leading-relaxed text-amber-600 dark:text-amber-500" style={{ borderBottom: '1px solid var(--hairline)' }}>
          还需补充：{coverage.missing.map((k) => MISSING_HINT[k] || k).join('、')}
        </div>
      )}
      {coverage?.ready && (
        <div className="px-4 py-2 text-[11px] leading-relaxed text-primary" style={{ borderBottom: '1px solid var(--hairline)' }}>
          ✓ 核心信息已充分，可创建项目
        </div>
      )}

      {/* 8 章列表（统一面板 + hairline 分隔，Apple 风格）*/}
      <div className="flex-1 overflow-y-auto">
        {CHAPTERS.map((c, i) => {
          const ch = outline?.[c.key]
          const content = ch?.content?.trim() ?? ''
          const isFilled = !!content
          const isCore = CORE_KEYS.has(c.key)
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
                {isCore && (
                  <span className="rounded-sm px-1 text-[9px] text-muted-foreground/60" style={{ border: '1px solid var(--hairline)' }}>
                    核心
                  </span>
                )}
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
                  {c.key === 'effect' && ch?.evidence_type && (
                    <p className="mt-1 text-[10px] not-italic text-muted-foreground/60">效果依据：{ch.evidence_type}</p>
                  )}
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
      <div className="px-4 py-2.5 text-[11px] leading-relaxed text-muted-foreground/70">
        预览随对话实时梳理，非最终内容。
        <br />
        核心信息充分后可一键生成完整初稿。
      </div>
    </div>
  )
}
