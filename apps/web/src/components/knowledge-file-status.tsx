'use client'

import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { KnowledgeFile } from '@/types/api'

/**
 * 知识文件异步解析+向量化状态展示（plan async-knowledge-upload + async-parsing）。
 *
 * 三态：
 * - pending/processing：进度条 + 阶段文案（已上传 / 解析中 / 向量化中）
 * - ready：不渲染（正常卡片，由调用方决定是否显示完成态）
 * - failed：红色错误文案
 *
 * 用于 KnowledgeFileCard 顶部，让用户看到文件还在解析/向量化、何时可检索。
 */
export function KnowledgeFileStatus({ kf }: { kf: KnowledgeFile }) {
  if (kf.status === 'ready') return null

  if (kf.status === 'failed') {
    return (
      <div className="flex items-start gap-1.5 rounded-md bg-destructive/5 p-2 text-[11px] text-destructive">
        <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
        <div>
          <p className="font-medium">处理失败</p>
          {kf.error_message && (
            <p className="mt-0.5 line-clamp-2 text-destructive/80">{kf.error_message}</p>
          )}
        </div>
      </div>
    )
  }

  // pending / processing：显示进度
  const stageText =
    kf.stage === 'parsing'
      ? '解析中…'
      : kf.stage === 'embedding'
        ? '向量化中…'
        : kf.status === 'processing'
          ? '向量化中…'
          : kf.stage === 'done'
            ? '即将就绪'
            : '已上传，排队处理…'

  return (
    <div className="flex items-center gap-1.5 rounded-md bg-muted/40 p-2 text-[11px] text-muted-foreground">
      <Loader2 className="size-3.5 shrink-0 animate-spin" />
      <span>{stageText}</span>
    </div>
  )
}
