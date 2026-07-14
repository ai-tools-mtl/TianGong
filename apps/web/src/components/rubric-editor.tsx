'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { RubricCriterion } from '@/types/api'

export function RubricEditor() {
  const qc = useQueryClient()
  const { data: rubric } = useQuery({
    queryKey: ['rubric'],
    queryFn: () => api.getRubric(),
  })

  const reset = useMutation({
    mutationFn: () => api.resetRubric(),
    onSuccess: () => {
      toast.success('已恢复系统默认')
      qc.invalidateQueries({ queryKey: ['rubric'] })
    },
  })

  if (!rubric) return <p className="text-muted-foreground">加载中...</p>

  const criteria = (rubric.criteria as unknown as RubricCriterion[]) ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">{rubric.name}</h1>
          <p className="text-sm text-muted-foreground">
            {rubric.is_customized ? '已自定义' : '系统默认'}
          </p>
        </div>
        {rubric.is_customized && (
          <Button variant="outline" onClick={() => reset.mutate()}>恢复默认</Button>
        )}
      </div>

      <div className="space-y-3">
        {criteria.map((c) => (
          <div key={c.key} className="rounded-lg border p-4">
            <div className="flex items-center gap-2">
              <span className="font-medium">{c.name}</span>
              <Badge variant="secondary">权重 {Math.round(c.weight * 100)}%</Badge>
            </div>
            <div className="mt-2 space-y-1 text-sm text-muted-foreground">
              {Object.entries(c.scoring_guide).map(([range, desc]) => (
                <p key={range}><strong>{range}</strong>：{desc}</p>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
