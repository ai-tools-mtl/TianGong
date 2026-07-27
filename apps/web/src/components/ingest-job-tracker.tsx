'use client'

import { useState } from 'react'

import { IngestJobCard } from '@/components/ingest-job-card'
import { useIngestJobs } from '@/lib/queries'
import type { WebIngestJob } from '@/types/api'

interface IngestJobTrackerProps {
  scope: 'personal' | 'global'
}

const FIVE_MINUTES = 5 * 60 * 1000

/**
 * 任务追踪区:展示匹配 scope 的网页摄入任务。
 *
 * - 无任务时 return null(不占空间)
 * - 终态(completed/failed)任务完成后 5 分钟自动隐藏;也可手动 dismiss
 * - 最多展示 5 个(防刷屏)
 * - 通过 useIngestJobs 的 refetchInterval 自动轮询(5s)
 */
export function IngestJobTracker({ scope }: IngestJobTrackerProps) {
  const { data: jobs } = useIngestJobs()
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  const visible = (jobs ?? [])
    .filter((j: WebIngestJob) => j.scope === scope)
    .filter((j: WebIngestJob) => !dismissed.has(j.id))
    .filter((j: WebIngestJob) => {
      // 进行中任务永远显示;终态任务只在完成后 5 分钟内显示
      if (j.status === 'pending' || j.status === 'running') return true
      // 终态:看 completed_at(后端 completed/failed 都会填 completed_at)
      if (!j.completed_at) return true // 兜底:无时间戳则显示(让用户手动 dismiss)
      return Date.now() - new Date(j.completed_at).getTime() < FIVE_MINUTES
    })
    .slice(0, 5)

  if (visible.length === 0) return null

  function handleDismiss(jobId: string) {
    setDismissed((prev) => new Set(prev).add(jobId))
  }

  return (
    <div className="mb-4 space-y-2">
      {visible.map((job: WebIngestJob) => (
        <IngestJobCard
          key={job.id}
          job={job}
          onDismiss={() => handleDismiss(job.id)}
        />
      ))}
    </div>
  )
}
