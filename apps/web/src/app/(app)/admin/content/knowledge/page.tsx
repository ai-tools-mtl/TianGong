'use client'

import Link from 'next/link'
import { useRef, useState } from 'react'
import { Download, Globe, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'

import { IngestJobTracker } from '@/components/ingest-job-tracker'
import { PageHeader, PageShell } from '@/components/page-shell'
import { WebIngestDialog } from '@/components/web-ingest-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import {
  useAdminUploadGlobal,
  useDeleteGlobalKnowledge,
  useGlobalKnowledge,
} from '@/lib/queries'
import { sourceTypeLabel } from '@/lib/source-type-labels'
import type { KnowledgeFile } from '@/types/api'

/**
 * /admin/content/knowledge 知识库直传（refactor/admin-ia-phase3 切片 C）。
 *
 * admin 直传文件到全局库——免审，全员立即可检索（与 /knowledge/upload 走审核流不同）。
 * 后端端点 POST /admin/knowledge/upload 早已就绪（admin.py），前端 hook
 * useAdminUploadGlobal 也已存在（queries.ts），此前是「死代码」无组件调用，
 * 本切片把 UI 接到 /admin/content/knowledge 占位页。
 *
 * 上传成功后 hook 的 onSuccess 已 invalidate knowledgeGlobal query，列表自动刷新。
 */
export default function AdminKnowledgePage() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [ingestOpen, setIngestOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeFile | null>(null)
  const upload = useAdminUploadGlobal()
  const { data: files, isLoading } = useGlobalKnowledge()

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    upload.mutate(file, {
      onSuccess: () => toast.success('已上传到全局库（免审，全员可检索）'),
      onError: (err) =>
        toast.error((err as { message?: string })?.message ?? '上传失败'),
    })
    // 清空 input value 让同一文件可重复选
    if (fileRef.current) fileRef.current.value = ''
  }

  const list: KnowledgeFile[] = files ?? []

  return (
    <PageShell>
      <PageHeader title="全局知识库" description={`全员可检索 · ${list.length} 个文件`}>
        <div className="flex gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx"
            onChange={handleUpload}
            className="hidden"
          />
          <Button
            onClick={() => fileRef.current?.click()}
            disabled={upload.isPending}
            className="gap-1.5"
          >
            <Upload className="size-3.5" />
            {upload.isPending ? '上传中...' : '上传到全局库'}
          </Button>
          <Button
            variant="outline"
            onClick={() => setIngestOpen(true)}
            className="gap-1.5"
          >
            <Globe className="size-3.5" />
            抓取网页
          </Button>
        </div>
      </PageHeader>

      <div className="py-6">
        <IngestJobTracker scope="global" />

        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-32" />
            ))}
          </div>
        ) : list.length === 0 ? (
          <EmptyState description="全局库暂无共享内容" />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {list.map((kf) => (
              <GlobalKnowledgeCard
                key={kf.id}
                kf={kf}
                onDelete={setDeleteTarget}
              />
            ))}
          </div>
        )}
      </div>

      <WebIngestDialog
        scope="global"
        open={ingestOpen}
        onOpenChange={setIngestOpen}
      />

      <DeleteConfirmDialog
        target={deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      />
    </PageShell>
  )
}

function GlobalKnowledgeCard({
  kf,
  onDelete,
}: {
  kf: KnowledgeFile
  onDelete: (kf: KnowledgeFile) => void
}) {
  return (
    <Card className="apple-lift">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between gap-2 text-[15px]">
          <span className="truncate" title={kf.filename}>
            {kf.filename}
          </span>
          <Badge variant="outline" className="shrink-0 text-[10px] font-normal">
            {sourceTypeLabel(kf.source_type)}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>{formatSize(kf.size)}</span>
          <span>{new Date(kf.created_at).toLocaleDateString('zh-CN')}</span>
        </div>
        <div className="flex items-center gap-2 pt-1">
          <Button variant="ghost" size="xs" asChild>
            <a href={api.knowledgeFileUrl(kf.id)} download>
              <Download className="mr-1 size-3.5" /> 下载
            </a>
          </Button>
          <Button variant="ghost" size="xs" asChild>
            {/* G4：跳该文件的 chunk 列表页，可逐块编辑 content/keywords/weight/locked */}
            <Link href={`/admin/content/knowledge/${kf.id}`}>查看分块 →</Link>
          </Button>
          <Button
            variant="ghost"
            size="xs"
            className="text-destructive hover:text-destructive"
            onClick={() => onDelete(kf)}
          >
            <Trash2 className="mr-1 size-3.5" /> 删除
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function DeleteConfirmDialog({
  target,
  onOpenChange,
}: {
  target: KnowledgeFile | null
  onOpenChange: (open: boolean) => void
}) {
  const del = useDeleteGlobalKnowledge()

  function handleConfirm() {
    if (!target) return
    del.mutate(target.id, {
      onSuccess: () => {
        toast.success('已删除')
        onOpenChange(false)
      },
      onError: (err: { message?: string }) =>
        toast.error(err?.message ?? '删除失败'),
    })
  }

  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>删除全局库文件?</DialogTitle>
          <DialogDescription>
            将永久删除「{target?.filename}」及其向量索引。此操作不可恢复。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={del.isPending}
          >
            {del.isPending ? '删除中...' : '确认删除'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
