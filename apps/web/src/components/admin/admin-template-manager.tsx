'use client'

import { Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { TemplateDetailDialog } from '@/components/template-detail-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import {
  useAdminTemplates,
  useDeleteAdminTemplate,
  useSetAdminTemplateStatus,
  useUploadAdminTemplate,
} from '@/lib/queries'
import type { TemplateStatus, TemplateSummary } from '@/types/api'

/**
 * Admin 内置模板管理（refactor/admin-ia-phase3 切片 B）。
 *
 * admin 能：
 *   - 上传 docx 创建内置模板（is_system=True，初始 status='draft'）
 *   - 改状态：draft→published→offline→published
 *   - 删除：draft/offline 可删，published 必须先下线（后端拒删 409）
 *
 * 状态机校验在 service 层，前端按钮可见性按当前状态预判（避免无效点击）。
 * 上传后用 1.5s × 40 次 = 60s 轮询 parse_job 状态（参考 template-manager.tsx）。
 */
const POLL_INTERVAL_MS = 1500
const POLL_MAX_ATTEMPTS = 40

interface PollResult {
  status: 'completed' | 'failed' | 'timeout'
  errorMessage?: string
}

async function pollAdminParseJob(jobId: string): Promise<PollResult> {
  for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
    const job = await api.getAdminParseJob(jobId)
    if (job.status === 'completed') return { status: 'completed' }
    if (job.status === 'failed') return { status: 'failed', errorMessage: job.error_message || undefined }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
  return { status: 'timeout' }
}

const STATUS_BADGE: Record<TemplateStatus, { label: string; variant: 'secondary' | 'default' | 'destructive' | 'outline'; className?: string }> = {
  draft: { label: '草稿', variant: 'outline' },
  published: { label: '已发布', variant: 'secondary', className: 'bg-success/10 text-success' },
  offline: { label: '已下线', variant: 'outline', className: 'text-muted-foreground' },
}

export function AdminTemplateManager() {
  const { data: templates, isLoading, refetch } = useAdminTemplates()
  const upload = useUploadAdminTemplate()
  const setStatus = useSetAdminTemplateStatus()
  const del = useDeleteAdminTemplate()

  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const { parse_job_id } = await api.uploadAdminTemplate(file)
      toast.info('模板已上传，正在解析...')
      const result = await pollAdminParseJob(parse_job_id)
      if (result.status === 'completed') {
        toast.success('模板解析成功（草稿状态，发布后用户可见）')
        refetch()
      } else if (result.status === 'timeout') {
        toast.error('解析超时（超过 60 秒），请刷新页面查看模板列表')
        refetch()
      } else {
        toast.error(result.errorMessage || '模板解析失败')
      }
    } catch (err) {
      const msg = (err as { message?: string })?.message
      toast.error(msg || '上传失败')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function handleSetStatus(t: TemplateSummary, status: TemplateStatus) {
    setStatus.mutate(
      { id: t.id, status },
      {
        onSuccess: () =>
          toast.success(
            status === 'published'
              ? '已发布，所有用户可见'
              : status === 'offline'
                ? '已下线，不再向新用户展示'
                : '已改回草稿',
          ),
        onError: (err) => {
          const msg = (err as { message?: string })?.message
          toast.error(msg || '操作失败')
        },
      },
    )
  }

  function handleDelete(t: TemplateSummary) {
    if (!confirm(`确认删除模板「${t.name}」？此操作不可撤销。`)) return
    del.mutate(t.id, {
      onSuccess: () => toast.success('模板已删除'),
      onError: (err) => {
        const msg = (err as { message?: string })?.message
        toast.error(msg || '删除失败（可能需先下线）')
      },
    })
  }

  const list: TemplateSummary[] = templates ?? []
  const actionPending = setStatus.isPending || del.isPending

  return (
    <PageShell>
      <PageHeader title="内置模板" description={`共 ${list.length} 个系统模板`}>
        <input
          ref={fileRef}
          type="file"
          accept=".docx"
          onChange={handleUpload}
          className="hidden"
        />
        <Button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="gap-1.5"
        >
          <Upload className="size-3.5" />
          {uploading ? '解析中...' : '上传模板'}
        </Button>
      </PageHeader>

      <div className="py-6">
        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-32" />
            ))}
          </div>
        ) : list.length === 0 ? (
          <EmptyState description="还没有模板，上传一个 Word 模板开始" />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {list.map((t) => {
              const badge = STATUS_BADGE[t.status]
              return (
                <Card key={t.id} className="apple-lift">
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center justify-between gap-2 text-[15px]">
                      <span className="truncate" title={t.name}>
                        {t.name}
                      </span>
                      <Badge
                        variant={badge.variant}
                        className={`shrink-0 text-[10px] ${badge.className ?? ''}`}
                      >
                        {badge.label}
                      </Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="text-[12px] text-muted-foreground">
                        {t.section_count} 个章节
                        {t.is_default && <span className="ml-2">· 默认</span>}
                      </p>
                      <TemplateDetailDialog templateId={t.id} templateName={t.name} status={t.status} />
                    </div>
                    <div className="flex flex-wrap items-center gap-1 pt-1">
                      {/* draft：发布 + 删除 */}
                      {t.status === 'draft' && (
                        <>
                          <Button
                            size="xs"
                            disabled={actionPending}
                            onClick={() => handleSetStatus(t, 'published')}
                          >
                            发布
                          </Button>
                          <Button
                            size="xs"
                            variant="outline"
                            disabled={actionPending}
                            onClick={() => handleDelete(t)}
                          >
                            删除
                          </Button>
                        </>
                      )}
                      {/* published：下线（不可直接删） */}
                      {t.status === 'published' && (
                        <Button
                          size="xs"
                          variant="outline"
                          disabled={actionPending}
                          onClick={() => handleSetStatus(t, 'offline')}
                        >
                          下线
                        </Button>
                      )}
                      {/* offline：重新上线 + 删除 */}
                      {t.status === 'offline' && (
                        <>
                          <Button
                            size="xs"
                            disabled={actionPending}
                            onClick={() => handleSetStatus(t, 'published')}
                          >
                            重新上线
                          </Button>
                          <Button
                            size="xs"
                            variant="outline"
                            disabled={actionPending}
                            onClick={() => handleDelete(t)}
                          >
                            删除
                          </Button>
                        </>
                      )}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </PageShell>
  )
}
