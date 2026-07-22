'use client'

import { Download, Check, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { useApproveReview, usePendingReviews, useRejectReview } from '@/lib/queries'
import type { KnowledgeReview } from '@/types/api'

const SOURCE_LABEL: Record<string, string> = {
  external: '外部素材',
  disclosure_export: '归档交底书',
}

function ReviewCard({ review }: { review: KnowledgeReview }) {
  const approve = useApproveReview()
  const reject = useRejectReview()
  const [comment, setComment] = useState('')
  const [showComment, setShowComment] = useState(false)

  function handleApprove() {
    approve.mutate(review.id, {
      onSuccess: () => toast.success('已通过,文件已升入全局库'),
      onError: () => toast.error('操作失败'),
    })
  }

  function handleReject() {
    reject.mutate(
      { reviewId: review.id, comment: comment || undefined },
      {
        onSuccess: () => toast.success('已拒绝,文件保留在个人库'),
        onError: () => toast.error('操作失败'),
      },
    )
  }

  return (
    <Card className="apple-lift">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between gap-2 text-[15px]">
          <span className="flex items-center gap-2">
            <Badge variant="secondary" className="text-[10px]">
              {SOURCE_LABEL[review.source_type] ?? review.source_type}
            </Badge>
          </span>
          <Badge variant="outline" className="text-[10px] font-normal">
            {new Date(review.created_at).toLocaleDateString('zh-CN')}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="text-[13px] font-medium truncate" title={review.filename ?? undefined}>
          {review.filename ?? '未命名文件'}
        </div>
        <div className="text-[11px] text-muted-foreground">
          file: <code className="break-all">{review.file_id.slice(0, 8)}…</code>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="xs" asChild>
            <a href={api.knowledgeFileUrl(review.file_id)} download>
              <Download className="mr-1 size-3.5" /> 下载查看
            </a>
          </Button>
        </div>

        {showComment && (
          <Input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="拒绝理由(可选)"
            className="text-xs"
          />
        )}

        <div className="flex items-center gap-2 pt-1">
          <Button
            size="xs" onClick={handleApprove} disabled={approve.isPending || reject.isPending}
          >
            <Check className="mr-1 size-3.5" /> 通过
          </Button>
          <Button
            variant="destructive" size="xs"
            onClick={() => {
              if (showComment) handleReject()
              else setShowComment(true)
            }}
            disabled={approve.isPending || reject.isPending}
          >
            <X className="mr-1 size-3.5" />
            {showComment ? '确认拒绝' : '拒绝'}
          </Button>
          {showComment && (
            <Button variant="ghost" size="xs" onClick={() => { setShowComment(false); setComment('') }}>
              取消
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function ReviewWorkbench() {
  const { data: reviews, isLoading } = usePendingReviews()

  return (
    <PageShell>
      <PageHeader title="知识库审核" description="处理用户上报的素材与归档案例" />
      <div className="py-6">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">加载中...</p>
        ) : !reviews || reviews.length === 0 ? (
          <EmptyState description="暂无待审核工单" />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {reviews.map((r: KnowledgeReview) => (
              <ReviewCard key={r.id} review={r} />
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
