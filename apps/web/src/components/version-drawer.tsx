'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { api } from '@/lib/api'
import type { Version } from '@/types/api'

interface VersionDrawerProps {
  sectionId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function VersionDrawer({ sectionId, open, onOpenChange }: VersionDrawerProps) {
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
      onOpenChange(false)
    },
  })

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-96 max-w-sm">
        <SheetHeader>
          <SheetTitle>版本历史</SheetTitle>
        </SheetHeader>
        <div className="space-y-2 overflow-y-auto">
          {versions.map((v) => (
            <div key={v.id} className="space-y-1 rounded-xl border border-black/[0.07] p-3 dark:border-white/10">
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
          {versions.length === 0 && <EmptyState description="暂无版本记录" />}
        </div>
      </SheetContent>
    </Sheet>
  )
}
