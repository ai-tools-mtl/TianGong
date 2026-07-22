'use client'

import { Copy, Link2, Loader2, Trash2, UserPlus, Users } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import {
  useAddMember,
  useCreateShareLink,
  useMembers,
  useRemoveMember,
  useRevokeShareLink,
  useShareLinks,
} from '@/lib/queries'
import type { Member, ShareLink } from '@/types/api'

interface ShareDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ShareDialog({ projectId, open, onOpenChange }: ShareDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>分享与协作</DialogTitle>
          <DialogDescription>
            邀请代理人协作，或生成分享链接供访客批注。
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="members" className="w-full">
          <TabsList className="w-full">
            <TabsTrigger value="members" className="flex-1 gap-1.5">
              <Users className="size-3.5" />
              协作者
            </TabsTrigger>
            <TabsTrigger value="links" className="flex-1 gap-1.5">
              <Link2 className="size-3.5" />
              分享链接
            </TabsTrigger>
          </TabsList>
          <TabsContent value="members">
            <MembersTab projectId={projectId} />
          </TabsContent>
          <TabsContent value="links">
            <LinksTab projectId={projectId} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

// ── Tab 1: 协作者管理 ──

function MembersTab({ projectId }: { projectId: string }) {
  const { data, isLoading } = useMembers(projectId)
  const addMember = useAddMember(projectId)
  const removeMember = useRemoveMember(projectId)
  const [email, setEmail] = useState('')
  const members: Member[] = data ?? []

  function handleAdd() {
    if (!email.trim()) return
    addMember.mutate(email.trim(), {
      onSuccess: (m) => {
        toast.success(`已邀请 ${m.name || m.email}`)
        setEmail('')
      },
      onError: (err: { code?: string; message?: string }) => {
        const e = err as { code?: string; message?: string }
        if (e?.code === 'conflict') {
          toast.error('该用户已是项目成员')
        } else {
          toast.error(e?.message || '邀请失败（用户需已注册）')
        }
      },
    })
  }

  function handleRemove(member: Member) {
    removeMember.mutate(member.id, {
      onSuccess: () => toast.success(`已移除 ${member.name || member.email}`),
      onError: () => toast.error('移除失败'),
    })
  }

  return (
    <div className="space-y-3 pt-2">
      {/* 添加成员 */}
      <div className="flex gap-2">
        <Input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          placeholder="代理人邮箱（需已注册）"
          className="h-8 text-[13px]"
          disabled={addMember.isPending}
        />
        <Button size="sm" onClick={handleAdd} disabled={addMember.isPending || !email.trim()} className="gap-1.5">
          {addMember.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <UserPlus className="size-3.5" />}
          邀请
        </Button>
      </div>

      {/* 成员列表 */}
      <div className="space-y-1.5">
        {isLoading ? (
          <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            加载中...
          </div>
        ) : members.length === 0 ? (
          <EmptyState description="暂无协作者" />
        ) : (
          members.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between rounded-lg border px-3 py-2"
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-medium">
                  {m.email[0]?.toUpperCase()}
                </span>
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium">{m.name || m.email}</div>
                  <div className="truncate text-[11px] text-muted-foreground">{m.email}</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {m.role === 'reviewer' ? '审查员' : m.role}
                </span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => handleRemove(m)}
                  disabled={removeMember.isPending}
                  aria-label={`移除 ${m.email}`}
                  title="移除"
                >
                  <Trash2 className="size-3.5 text-destructive" />
                </Button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ── Tab 2: 分享链接 ──

function LinksTab({ projectId }: { projectId: string }) {
  const { data, isLoading } = useShareLinks(projectId)
  const createShareLink = useCreateShareLink(projectId)
  const revokeShareLink = useRevokeShareLink(projectId)
  const links: ShareLink[] = data ?? []
  const [permissions, setPermissions] = useState<'comment' | 'readonly'>('comment')

  function handleCreate() {
    createShareLink.mutate(
      { permissions },
      {
        onSuccess: (link) => {
          toast.success('分享链接已创建')
          // 自动复制到剪贴板
          const url = buildShareUrl(link.token)
          navigator.clipboard?.writeText(url).then(
            () => toast.success('链接已复制到剪贴板'),
            () => {},
          )
        },
        onError: () => toast.error('创建失败'),
      },
    )
  }

  function handleCopy(token: string) {
    const url = buildShareUrl(token)
    navigator.clipboard?.writeText(url).then(
      () => toast.success('已复制'),
      () => toast.error('复制失败，请手动复制'),
    )
  }

  function handleRevoke(link: ShareLink) {
    revokeShareLink.mutate(link.id, {
      onSuccess: () => toast.success('链接已撤销'),
      onError: () => toast.error('撤销失败'),
    })
  }

  return (
    <div className="space-y-3 pt-2">
      {/* 创建新链接 */}
      <div className="flex items-end gap-2">
        <div className="flex-1 space-y-1">
          <label className="text-[11px] text-muted-foreground">权限</label>
          <Select
            value={permissions}
            onChange={(e) => setPermissions(e.target.value as 'comment' | 'readonly')}
            className="h-8 px-2 text-[13px]"
          >
            <option value="comment">可批注</option>
            <option value="readonly">只读</option>
          </Select>
        </div>
        <Button
          size="sm"
          onClick={handleCreate}
          disabled={createShareLink.isPending}
          className="gap-1.5"
        >
          {createShareLink.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Link2 className="size-3.5" />}
          生成链接
        </Button>
      </div>

      {/* 链接列表 */}
      <div className="space-y-1.5">
        {isLoading ? (
          <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            加载中...
          </div>
        ) : links.length === 0 ? (
          <EmptyState description="暂无分享链接" />
        ) : (
          links.map((link) => (
            <div key={link.id} className="rounded-lg border px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className={cn(
                      'rounded px-1.5 py-0.5 text-[10px] font-medium',
                      link.permissions === 'comment'
                        ? 'bg-info/10 text-info'
                        : 'bg-muted text-muted-foreground',
                    )}
                  >
                    {link.permissions === 'comment' ? '可批注' : '只读'}
                  </span>
                  <code className="truncate text-[11px] text-muted-foreground">
                    {buildShareUrl(link.token).replace(/^https?:\/\/[^/]+/, '')}
                  </code>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => handleCopy(link.token)}
                    aria-label="复制链接"
                    title="复制链接"
                  >
                    <Copy className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => handleRevoke(link)}
                    disabled={revokeShareLink.isPending}
                    aria-label="撤销链接"
                    title="撤销"
                  >
                    <Trash2 className="size-3.5 text-destructive" />
                  </Button>
                </div>
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">
                {link.expires_at
                  ? `过期：${new Date(link.expires_at).toLocaleString('zh-CN')}`
                  : '永不过期'}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

/** 构造前端分享页 URL（访问 /shared/[token]） */
function buildShareUrl(token: string): string {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return `${origin}/shared/${token}`
}
