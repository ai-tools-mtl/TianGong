'use client'

import { Loader2, Ticket } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useCreateInvite, useInvites, useRevokeInvite } from '@/lib/queries'
import type { InviteCode } from '@/types/api'

/** 邀请码状态 → Badge。 */
function statusBadge(status: InviteCode['status']) {
  switch (status) {
    case 'active':
      return <Badge variant="default">可用</Badge>
    case 'exhausted':
      return <Badge variant="secondary">已用尽</Badge>
    case 'revoked':
      return <Badge variant="destructive">已吊销</Badge>
    case 'expired':
      return <Badge variant="outline">已过期</Badge>
  }
}

/**
 * 生成注册直达链接并复制到剪贴板。
 * 链接形如 https://host/register?code=XXXX,接收者打开即预填邀请码。
 */
function copyRegisterLink(code: string) {
  const url = `${window.location.origin}/register?code=${code}`
  navigator.clipboard.writeText(url).then(
    () => toast.success(`已复制注册链接`),
    () => toast.error('复制失败'),
  )
}

/**
 * 邀请码管理区块(嵌入用户管理页)。
 * 内部产品化:开放注册已关闭,admin 在此生成邀请码发给同事。
 */
export function InviteSection() {
  const { data: invites, isLoading } = useInvites()
  const createInvite = useCreateInvite()
  const revokeInvite = useRevokeInvite()

  const [open, setOpen] = useState(false)
  const [maxUses, setMaxUses] = useState('1')
  const [expiresDays, setExpiresDays] = useState('7')

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    const uses = parseInt(maxUses, 10)
    if (!uses || uses < 1) {
      toast.error('可用次数至少为 1')
      return
    }
    const days = expiresDays.trim() === '' ? null : parseInt(expiresDays, 10)
    createInvite.mutate(
      { max_uses: uses, expires_in_days: days },
      {
        onSuccess: () => {
          toast.success('邀请码已生成')
          setOpen(false)
        },
        onError: () => toast.error('生成失败'),
      },
    )
  }

  function handleRevoke(invite: InviteCode) {
    revokeInvite.mutate(invite.id, {
      onSuccess: () => toast.success('已吊销'),
      onError: () => toast.error('吊销失败'),
    })
  }

  const list: InviteCode[] = invites ?? []

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-0.5">
          <h2 className="text-lg font-semibold tracking-tight">邀请码</h2>
          <p className="text-[13px] text-muted-foreground">
            开放注册已关闭,生成邀请码发给同事自助注册
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <Ticket className="size-4" />
              生成邀请码
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>生成邀请码</DialogTitle>
              <DialogDescription>
                生成后复制注册链接发给同事,对方打开即可凭码注册。
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="maxUses">可用次数</Label>
                <Input
                  id="maxUses"
                  type="number"
                  min={1}
                  value={maxUses}
                  onChange={(e) => setMaxUses(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  同一码可注册的用户数(1 = 一次性)
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="expiresDays">有效天数</Label>
                <Input
                  id="expiresDays"
                  type="number"
                  min={1}
                  placeholder="留空表示不过期"
                  value={expiresDays}
                  onChange={(e) => setExpiresDays(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">留空表示永久有效</p>
              </div>
              <DialogFooter>
                <Button type="submit" disabled={createInvite.isPending}>
                  {createInvite.isPending ? (
                    <>
                      <Loader2 className="size-3.5 animate-spin" />
                      生成中...
                    </>
                  ) : (
                    '生成'
                  )}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading ? (
        <div className="rounded-xl border p-4 text-[13px] text-muted-foreground">
          加载中...
        </div>
      ) : list.length === 0 ? (
        <EmptyState description="暂无邀请码" />
      ) : (
        <div className="rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[140px]">邀请码</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>用量</TableHead>
                <TableHead>有效期</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((invite) => (
                <TableRow key={invite.id}>
                  <TableCell>
                    <button
                      onClick={() => copyRegisterLink(invite.code)}
                      className="font-mono text-sm tracking-wider hover:underline"
                      title="点击复制注册链接"
                    >
                      {invite.code}
                    </button>
                  </TableCell>
                  <TableCell>{statusBadge(invite.status)}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {invite.used_count} / {invite.max_uses}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {invite.expires_at
                      ? new Date(invite.expires_at).toLocaleDateString()
                      : '永久'}
                  </TableCell>
                  <TableCell className="text-right">
                    {invite.status === 'active' && (
                      <Button
                        variant="ghost"
                        size="xs"
                        disabled={revokeInvite.isPending}
                        onClick={() => handleRevoke(invite)}
                      >
                        吊销
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
