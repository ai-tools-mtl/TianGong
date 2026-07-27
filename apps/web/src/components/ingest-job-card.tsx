'use client'

import { CheckCircle, Loader2, X, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import type { WebIngestJob } from '@/types/api'

interface IngestJobCardProps {
  job: WebIngestJob
  onDismiss: () => void
}

export function IngestJobCard({ job, onDismiss }: IngestJobCardProps) {
  const isRunning = job.status === 'pending' || job.status === 'running'
  const isCompleted = job.status === 'completed'
  const isFailed = job.status === 'failed'

  const progress =
    job.mode === 'crawl' && job.pages_fetched > 0
      ? Math.min(100, (job.pages_fetched / Math.max(1, job.max_pages ?? 50)) * 100)
      : 0

  return (
    <Card className="apple-lift">
      <CardContent className="flex items-center gap-3 p-4">
        <div className="shrink-0">
          {isRunning && (
            <Loader2 className="size-4 animate-spin text-muted-foreground" />
          )}
          {isCompleted && <CheckCircle className="size-4 text-success" />}
          {isFailed && <XCircle className="size-4 text-destructive" />}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <a
              href={job.url}
              target="_blank"
              rel="noopener noreferrer"
              className="truncate text-sm font-medium hover:underline"
              title={job.url}
            >
              {job.url}
            </a>
            <Badge variant="outline" className="shrink-0 text-[10px] font-normal">
              {job.mode === 'crawl' ? '整站' : '单页'}
            </Badge>
          </div>

          {job.mode === 'crawl' && (
            <div className="mt-2 flex items-center gap-2">
              <Progress value={progress} className="h-1.5 flex-1" />
              <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                {job.pages_fetched} 页
              </span>
            </div>
          )}

          {isFailed && job.error_message && (
            <p
              className="mt-1 truncate text-xs text-destructive"
              title={job.error_message}
            >
              {job.error_message}
            </p>
          )}

          {isCompleted && job.mode === 'crawl' && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              抓取 {job.pages_fetched} 页
              {job.pages_filtered > 0 && `,过滤 ${job.pages_filtered} 页`}
              ,入库 {job.file_ids.length} 个文件
            </p>
          )}
        </div>

        {!isRunning && (
          <Button variant="ghost" size="xs" onClick={onDismiss}>
            <X className="size-3.5" />
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
