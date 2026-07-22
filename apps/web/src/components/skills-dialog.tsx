'use client'

import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useSkills, useUpdateSkill } from '@/lib/queries'
import type { AgentSkill } from '@/types/api'

interface SkillsDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SkillsDialog({ projectId, open, onOpenChange }: SkillsDialogProps) {
  const { data, isLoading } = useSkills(projectId)
  const updateSkill = useUpdateSkill(projectId)
  const skills: AgentSkill[] = data ?? []

  function handleToggle(skill: AgentSkill) {
    updateSkill.mutate(
      { skillKey: skill.skill_key, enabled: !skill.enabled },
      {
        onSuccess: () => toast.success(`${skill.enabled ? '已禁用' : '已启用'} ${skill.name}`),
        onError: () => toast.error('更新失败'),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>项目技能</DialogTitle>
          <DialogDescription>
            为本项目配置 Agent 技能组合。不同专利可启用不同技能。
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            加载中...
          </div>
        ) : (
          <div className="space-y-2">
            {skills.map((s) => (
              <div
                key={s.skill_key}
                className="flex items-center justify-between rounded-xl border p-3"
              >
                <div className="min-w-0 flex-1 pr-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{s.name}</span>
                    {s.is_overridden && (
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        已覆盖
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {s.description}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant={s.enabled ? 'default' : 'outline'}
                  onClick={() => handleToggle(s)}
                  disabled={updateSkill.isPending}
                  className="h-7 shrink-0 px-3 text-xs"
                >
                  {s.enabled ? '已启用' : '已禁用'}
                </Button>
              </div>
            ))}
            {skills.length === 0 && (
              <p className="py-4 text-center text-sm text-muted-foreground">
                暂无可用技能
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
