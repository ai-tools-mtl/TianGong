'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'

import { ChunkEditorDialog, type EditableChunk } from '@/components/admin/chunk-editor-dialog'
import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useFileChunks } from '@/lib/queries'

/** 列表页用的完整 chunk 结构（含 chunk_index/source_section_key 两个列表专属字段）。 */
type ChunkListItem = EditableChunk & {
  chunk_index: number
  source_section_key: string | null
}

/**
 * G4 分块可视化干预（Task 4.4）：某文件的 chunk 列表页。
 *
 * 路由 /admin/content/knowledge/[fileId]，动态参数 fileId。
 * 入口在父级 knowledge/page.tsx 的文件卡片「查看分块」。
 * 点单 chunk「编辑」弹 ChunkEditorDialog。
 */
export default function FileChunksPage() {
  const params = useParams<{ fileId: string }>()
  const fileId = params.fileId
  const { data: chunks, isLoading } = useFileChunks(fileId)
  const [editing, setEditing] = useState<EditableChunk | null>(null)
  const [open, setOpen] = useState(false)

  return (
    <PageShell>
      <PageHeader
        title={`分块列表 ${fileId.slice(0, 8)}…`}
        description="点击分块编辑内容、关键词、权重。编辑文本会触发重新 embed。"
      />
      <div className="py-6 space-y-3">
        {isLoading && <Skeleton className="h-64" />}
        {!isLoading && chunks?.length === 0 && (
          <p className="text-sm text-muted-foreground">该文件无分块</p>
        )}
        {chunks?.map((c: ChunkListItem) => (
          <div key={c.id} className="space-y-2 rounded border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge>#{c.chunk_index}</Badge>
              <Badge variant="outline">权重 {c.weight}</Badge>
              {c.locked && <Badge variant="destructive">已锁定</Badge>}
              {(c.keywords?.length ?? 0) > 0 && (
                <Badge variant="secondary">{c.keywords.length} 关键词</Badge>
              )}
              {c.edited_text && <Badge variant="secondary">已编辑</Badge>}
            </div>
            <p className="line-clamp-3 whitespace-pre-wrap text-sm">
              {c.edited_text || c.content}
            </p>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setEditing(c)
                setOpen(true)
              }}
            >
              编辑
            </Button>
          </div>
        ))}
      </div>

      <ChunkEditorDialog chunk={editing} open={open} onOpenChange={setOpen} />
    </PageShell>
  )
}
