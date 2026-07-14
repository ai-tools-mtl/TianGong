'use client'

import { useParams } from 'next/navigation'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { ReviewRecord } from '@/types/api'

export default function ReviewPage() {
  const params = useParams<{ id: string }>()
  const qc = useQueryClient()
  const [reviewing, setReviewing] = useState(false)

  const { data: reviews } = useQuery({
    queryKey: ['reviews', params.id],
    queryFn: () => api.listReviews(params.id),
  })

  const latest: ReviewRecord | undefined = reviews?.[0]

  const runReview = useMutation({
    mutationFn: () => api.runReview(params.id),
    onMutate: () => setReviewing(true),
    onSuccess: () => {
      toast.success('审查完成')
      qc.invalidateQueries({ queryKey: ['reviews', params.id] })
    },
    onError: () => toast.error('审查失败'),
    onSettled: () => setReviewing(false),
  })

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">交底书审查</h1>
        <Button onClick={() => runReview.mutate()} disabled={reviewing}>
          {reviewing ? '审查中...' : '执行审查'}
        </Button>
      </div>

      {latest ? (
        <div className="space-y-4">
          <div className="rounded-lg border p-6 text-center">
            <div className="text-4xl font-bold">{latest.total_score}</div>
            <div className="text-sm text-muted-foreground">总分（第 {latest.round} 轮）</div>
            {latest.previous_score !== null && (
              <Badge variant={latest.total_score >= latest.previous_score ? 'default' : 'destructive'} className="mt-2">
                {latest.total_score >= latest.previous_score ? '+' : ''}
                {latest.total_score - latest.previous_score}
              </Badge>
            )}
          </div>

          {(latest.dimension_scores as import('@/types/api').DimensionScore[]).map((d) => (
            <div key={d.key} className="space-y-2 rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <span className="font-medium">{d.name}</span>
                <span className="text-lg font-bold">{d.score}</span>
              </div>
              <p className="text-xs text-muted-foreground">权重 {Math.round(d.weight * 100)}%</p>
              {d.evidence && <p className="text-sm">依据：{d.evidence}</p>}
              {d.suggestion && <p className="text-sm text-muted-foreground">建议：{d.suggestion}</p>}
              <p className="text-xs text-muted-foreground">
                自一致性评分：{d.run_scores.join(' / ')}
              </p>
            </div>
          ))}

          {latest.resolved_issues.length > 0 && (
            <div className="rounded-lg border border-green-200 bg-green-50 p-4">
              <h3 className="text-sm font-semibold text-green-800">已解决的问题</h3>
              <ul className="mt-2 space-y-1 text-sm">
                {latest.resolved_issues.map((issue, i) => (
                  <li key={i}>✓ {issue}</li>
                ))}
              </ul>
            </div>
          )}
          {latest.remaining_issues.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
              <h3 className="text-sm font-semibold text-amber-800">待改进</h3>
              <ul className="mt-2 space-y-1 text-sm">
                {latest.remaining_issues.map((issue, i) => (
                  <li key={i}>→ {issue}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <p className="py-12 text-center text-muted-foreground">
          尚未审查，点击「执行审查」开始
        </p>
      )}
    </div>
  )
}
