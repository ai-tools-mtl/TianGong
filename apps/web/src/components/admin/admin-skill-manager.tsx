'use client'

import { Plus, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { SkillEditor } from '@/components/skills/skill-editor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useCreateGlobalSkill,
  useDeleteGlobalSkill,
  useGlobalSkills,
  useImportGlobalSkill,
  useUpdateGlobalSkill,
} from '@/lib/queries'
import type { Skill, SkillCreate, SkillUpdate } from '@/types/api'

/**
 * Admin 全局技能管理（spec 两档可见性之 global）。
 * 仿 admin-template-manager.tsx 模式。
 *
 * 列表展示 name/description/status，行内编辑/删除。
 * 编辑面板用 SkillEditor（admin/user 共用表单）。
 * 删除后后端会一并清 MinIO 目录（spec §12）。
 */
export function AdminSkillManager() {
  const { data: skills, isLoading } = useGlobalSkills()
  const createSkill = useCreateGlobalSkill()
  const updateSkill = useUpdateGlobalSkill()
  const deleteSkill = useDeleteGlobalSkill()
  const importSkill = useImportGlobalSkill()
  const [editing, setEditing] = useState<Skill | null | 'new'>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleCreate(data: SkillCreate) {
    await createSkill.mutateAsync(data)
  }

  async function handleUpdate(id: string, data: SkillUpdate) {
    await updateSkill.mutateAsync({ id, data })
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`确定删除全局技能「${name}」？MinIO 目录会一并清除。`)) return
    try {
      await deleteSkill.mutateAsync(id)
      toast.success('已删除')
    } catch (e) {
      toast.error('删除失败：' + (e as Error).message)
    }
  }

  async function handleImportZip(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // 重置，允许重复选同一文件
    if (!file) return
    try {
      await importSkill.mutateAsync(file)
      toast.success(`已导入：${file.name}`)
    } catch (e) {
      toast.error('导入失败：' + ((e as { message?: string })?.message ?? String(e)))
    }
  }

  const isEditing = editing !== null
  const list: Skill[] = skills ?? []

  return (
    <PageShell>
      <PageHeader
        title="全局技能"
        description="admin 管理的全站可见 Agent Skills（spec 合规 SKILL.md）"
      >
        <div className="flex gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={handleImportZip}
          />
          <Button
            variant="outline"
            className="gap-1.5"
            disabled={importSkill.isPending}
            onClick={() => fileRef.current?.click()}
          >
            <Upload className="size-3.5" /> 导入 zip
          </Button>
          <Button onClick={() => setEditing('new')} className="gap-1.5">
            <Plus className="size-3.5" /> 新建技能
          </Button>
        </div>
      </PageHeader>

      <div className="py-6">
        {isEditing && (
          <Card className="mb-6">
            <CardHeader>
              <CardTitle>
                {editing === 'new' ? '新建全局技能' : `编辑：${editing.name}`}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <SkillEditor
                skill={editing === 'new' ? null : editing}
                mode="global"
                onSave={async (data) => {
                  if (editing === 'new') {
                    await handleCreate(data as SkillCreate)
                  } else if (editing) {
                    await handleUpdate(editing.id, data as SkillUpdate)
                  }
                }}
                onCancel={() => setEditing(null)}
              />
            </CardContent>
          </Card>
        )}

        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-32" />
            ))}
          </div>
        ) : list.length === 0 ? (
          <EmptyState
            title="暂无全局技能"
            description="点击「新建技能」创建第一个全局技能"
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {list.map((s) => (
              <Card key={s.id} className="apple-lift">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center justify-between gap-2 text-[15px]">
                    <span className="truncate font-mono" title={s.name}>
                      {s.name}
                    </span>
                    <div className="flex shrink-0 items-center gap-1">
                      {s.is_builtin && (
                        <Badge variant="outline" className="text-[10px]">
                          内置
                        </Badge>
                      )}
                      <Badge
                        variant={s.status === 'active' ? 'default' : 'secondary'}
                        className="text-[10px]"
                      >
                        {s.status}
                      </Badge>
                    </div>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <p className="line-clamp-2 text-[12px] text-muted-foreground">
                    {s.description}
                  </p>
                  <div className="flex items-center gap-1 pt-1">
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={s.is_builtin}
                      title={s.is_builtin ? '内置技能由文件系统管理，不可编辑' : undefined}
                      onClick={() => setEditing(s)}
                    >
                      编辑
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={s.is_builtin}
                      title={s.is_builtin ? '内置技能由文件系统管理，不可删除' : undefined}
                      onClick={() => handleDelete(s.id, s.name)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
