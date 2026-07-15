'use client'

import { useState } from 'react'
import { Merge, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  useCreateTag, useDeleteTag, useMergeTags, useRenameTag, useTags,
} from '@/lib/queries'
import type { Tag } from '@/types/api'

export function TagEditor() {
  const { data: tags, isLoading } = useTags()
  const create = useCreateTag()
  const rename = useRenameTag()
  const del = useDeleteTag()
  const merge = useMergeTags()

  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [mergeOpen, setMergeOpen] = useState(false)
  const [mergeSource, setMergeSource] = useState('')
  const [mergeTarget, setMergeTarget] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string; count: number } | null>(null)

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    create.mutate(
      { name: newName.trim() },
      {
        onSuccess: () => { toast.success('标签已创建'); setNewName('') },
        onError: () => toast.error('创建失败'),
      },
    )
  }

  function handleRename(id: string) {
    if (!editingName.trim()) return
    rename.mutate(
      { id, name: editingName.trim() },
      {
        onSuccess: () => { toast.success('已重命名'); setEditingId(null) },
        onError: () => toast.error('重命名失败'),
      },
    )
  }

  function handleMerge(e: React.FormEvent) {
    e.preventDefault()
    if (!mergeSource || !mergeTarget || mergeSource === mergeTarget) {
      toast.error('请选择两个不同的标签')
      return
    }
    merge.mutate(
      { source_id: mergeSource, target_id: mergeTarget },
      {
        onSuccess: () => { toast.success('已合并'); setMergeOpen(false); setMergeSource(''); setMergeTarget('') },
        onError: () => toast.error('合并失败'),
      },
    )
  }

  function handleDelete() {
    if (!deleteTarget) return
    del.mutate(deleteTarget.id, {
      onSuccess: () => { toast.success('已删除'); setDeleteTarget(null) },
      onError: () => toast.error('删除失败'),
    })
  }

  return (
    <div className="space-y-6">
      {/* 创建新标签 */}
      <form onSubmit={handleCreate} className="flex max-w-md gap-2">
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="新标签名称"
        />
        <Button type="submit" disabled={create.isPending || !newName.trim()}>
          创建
        </Button>
      </form>

      {/* 标签列表 */}
      {isLoading ? (
        <p className="text-sm text-muted-foreground">加载中...</p>
      ) : !tags || tags.length === 0 ? (
        <p className="text-sm text-muted-foreground">还没有标签。</p>
      ) : (
        <div className="space-y-2">
          {tags.map((tag: Tag) => (
            <div
              key={tag.id}
              className="flex items-center justify-between rounded-md border px-3 py-2"
            >
              {editingId === tag.id ? (
                <div className="flex flex-1 items-center gap-2">
                  <Input
                    value={editingName}
                    onChange={(e) => setEditingName(e.target.value)}
                    className="h-7 max-w-[200px]"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRename(tag.id)
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                  />
                  <Button size="xs" onClick={() => handleRename(tag.id)} disabled={rename.isPending}>
                    保存
                  </Button>
                  <Button size="xs" variant="ghost" onClick={() => setEditingId(null)}>
                    取消
                  </Button>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{tag.name}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {tag.project_count} 个项目
                    </span>
                  </div>
                  <div className="flex gap-1">
                    <Button
                      size="xs" variant="ghost"
                      onClick={() => { setEditingId(tag.id); setEditingName(tag.name) }}
                    >
                      重命名
                    </Button>
                    <Button
                      size="xs" variant="ghost" className="text-destructive"
                      onClick={() => setDeleteTarget({ id: tag.id, name: tag.name, count: tag.project_count })}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 合并按钮（需 ≥2 个标签） */}
      {tags && tags.length >= 2 && (
        <Button variant="outline" onClick={() => setMergeOpen(true)}>
          <Merge className="mr-2 size-4" />
          合并标签
        </Button>
      )}

      {/* 合并弹窗 */}
      <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>合并标签</DialogTitle>
            <DialogDescription>
              将源标签的所有项目关联转移到目标标签，然后删除源标签。此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleMerge} className="space-y-4">
            <div className="space-y-2">
              <Label>源标签（将被删除）</Label>
              <select
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                value={mergeSource}
                onChange={(e) => setMergeSource(e.target.value)}
              >
                <option value="">选择...</option>
                {tags?.map((tag: Tag) => <option key={tag.id} value={tag.id}>{tag.name}</option>)}
              </select>
            </div>
            <div className="space-y-2">
              <Label>目标标签（保留）</Label>
              <select
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                value={mergeTarget}
                onChange={(e) => setMergeTarget(e.target.value)}
              >
                <option value="">选择...</option>
                {tags?.map((tag: Tag) => <option key={tag.id} value={tag.id}>{tag.name}</option>)}
              </select>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={merge.isPending || !mergeSource || !mergeTarget}>
                {merge.isPending ? '合并中...' : '确认合并'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 删除确认弹窗 */}
      <Dialog open={!!deleteTarget} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除标签</DialogTitle>
            <DialogDescription>
              确认删除标签「{deleteTarget?.name}」？
              {deleteTarget && deleteTarget.count > 0 && (
                <>它将从 {deleteTarget.count} 个项目上摘除（项目本身不受影响）。</>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={del.isPending}>
              {del.isPending ? '删除中...' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
