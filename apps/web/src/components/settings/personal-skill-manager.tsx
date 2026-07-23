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
  useCreateMySkill,
  useDeleteMySkill,
  useImportMySkill,
  useMySkills,
  useUpdateMySkill,
  useVisibleSkills,
} from '@/lib/queries'
import type { Skill, SkillCreate, SkillUpdate } from '@/types/api'

/**
 * 用户个人技能管理（spec 两档可见性之 personal）。
 * 上半区：可见的 global skill（只读）；下半区：我的 personal skill（CRUD）。
 * 仿 admin-skill-manager.tsx 模式。
 */
export function PersonalSkillManager() {
  const { data: mySkills, isLoading: myLoading } = useMySkills()
  const { data: visibleSkills, isLoading: visLoading } = useVisibleSkills()
  const createSkill = useCreateMySkill()
  const updateSkill = useUpdateMySkill()
  const deleteSkill = useDeleteMySkill()
  const importSkill = useImportMySkill()
  const [editing, setEditing] = useState<Skill | null | 'new'>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleCreate(data: SkillCreate) {
    await createSkill.mutateAsync(data)
  }

  async function handleUpdate(id: string, data: SkillUpdate) {
    await updateSkill.mutateAsync({ id, data })
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`确定删除个人技能「${name}」？MinIO 目录会一并清除。`)) return
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
  const visibleList: Skill[] = visibleSkills ?? []
  const globalSkills: Skill[] = visibleList.filter((s) => s.scope === 'global')
  const myList: Skill[] = mySkills ?? []

  return (
    <PageShell>
      <PageHeader
        title="我的技能"
        description="管理个人 Agent Skills（spec 合规 SKILL.md）"
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
                {editing === 'new' ? '新建个人技能' : `编辑：${editing.name}`}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <SkillEditor
                skill={editing === 'new' ? null : editing}
                mode="personal"
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

        {/* 全局技能（只读） */}
        <section className="mb-8">
          <h3 className="mb-3 text-sm font-medium text-muted-foreground">
            全局技能（admin 提供，只读）
          </h3>
          {visLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-20" />
              ))}
            </div>
          ) : globalSkills.length === 0 ? (
            <EmptyState title="暂无可用全局技能" description="管理员尚未发布任何全局技能" />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {globalSkills.map((s) => (
                <Card key={s.id} className="apple-lift">
                  <CardContent className="flex items-center justify-between gap-2 py-3">
                    <div className="min-w-0 space-y-0.5">
                      <span className="block truncate font-mono text-[13px]" title={s.name}>
                        {s.name}
                      </span>
                      <p className="line-clamp-2 text-[12px] text-muted-foreground">
                        {s.description}
                      </p>
                    </div>
                    <Badge variant="secondary" className="shrink-0 text-[10px]">
                      global
                    </Badge>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </section>

        {/* 我的个人技能 */}
        <section>
          <h3 className="mb-3 text-sm font-medium text-muted-foreground">我的个人技能</h3>
          {myLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 2 }).map((_, i) => (
                <Skeleton key={i} className="h-32" />
              ))}
            </div>
          ) : myList.length === 0 ? (
            <EmptyState
              title="暂无个人技能"
              description="点击「新建技能」创建你的第一个技能"
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {myList.map((s) => (
                <Card key={s.id} className="apple-lift">
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center justify-between gap-2 text-[15px]">
                      <span className="truncate font-mono" title={s.name}>
                        {s.name}
                      </span>
                      <Badge
                        variant={s.status === 'active' ? 'default' : 'secondary'}
                        className="shrink-0 text-[10px]"
                      >
                        {s.status}
                      </Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <p className="line-clamp-2 text-[12px] text-muted-foreground">
                      {s.description}
                    </p>
                    <div className="flex items-center gap-1 pt-1">
                      <Button size="xs" variant="outline" onClick={() => setEditing(s)}>
                        编辑
                      </Button>
                      <Button
                        size="xs"
                        variant="outline"
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
        </section>
      </div>
    </PageShell>
  )
}
