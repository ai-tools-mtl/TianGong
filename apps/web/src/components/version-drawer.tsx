'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { Version } from '@/types/api'

interface VersionDrawerProps {
  sectionId: string
  open: boolean
  onClose: () => void
}

export function VersionDrawer({ sectionId, open, onClose }: VersionDrawerProps) {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['versions', sectionId],
    queryFn: () => api.listVersions(sectionId),
    enabled: open && !!sectionId,
  })
  const versions: Version[] = data ?? []

  const rollback = useMutation({
    mutationFn: (versionId: string) => api.rollbackVersion(sectionId, versionId),
    onSuccess: () => {
      toast.success('已回滚')
      qc.invalidateQueries({ queryKey: ['sections'] })
      onClose()
    },
  })

  if (!open) return null

  return (
    <div className="fixed inset-y-0 right-0 w-96 border-l bg-background p-4 shadow-lg overflow-y-auto z-50">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-semibold">版本历史</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>关闭</Button>
      </div>
      <div className="space-y-2">
        {versions.map((v) => (
          <div key={v.id} className="space-y-1 rounded-lg border p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {new Date(v.created_at).toLocaleString('zh-CN')}
              </span>
              <span className="rounded bg-muted px-2 py-0.5 text-xs">
                {v.created_by === 'auto' ? '自动' : '手动'}
              </span>
            </div>
            {v.note && <p className="text-sm">{v.note}</p>}
            <Button
              size="sm" variant="outline"
              onClick={() => rollback.mutate(v.id)}
              disabled={rollback.isPending}
            >
              回滚到此版本
            </Button>
          </div>
        ))}
        {versions.length === 0 && (
          <p className="text-sm text-muted-foreground">暂无版本记录</p>
        )}
      </div>
    </div>
  )
}
