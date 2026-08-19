'use client'

import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useBanUser,
  useGrantGlobalLLM,
  useResetUserPassword,
  useRevokeGlobalLLM,
  useUserDetail,
} from '@/lib/queries'
import { useAuthStore } from '@/stores/auth'

/**
 * /admin/users/[id] 用户详情（refactor/admin-ia-phase1 切片 1）。
 *
 * 两栏布局：
 *   左 — 基本信息卡（用户档案 + 运营统计）
 *   右 — 操作卡（全局 Key 授权区块 + 重置密码区块）
 *
 * 重置密码从阶段 1 主页的 inline Card 弹层，改为详情页内嵌的独立 Card 区块
 * （已经在详情页了，没必要再弹层）。
 */
export default function UserDetailPage() {
  const params = useParams<{ id: string }>()
  const userId = params.id
  const me = useAuthStore((s) => s.user)

  const { data: user, isLoading } = useUserDetail(userId)

  const ban = useBanUser()
  const grant = useGrantGlobalLLM()
  const revoke = useRevokeGlobalLLM()
  const resetPwd = useResetUserPassword()

  const [newPassword, setNewPassword] = useState('')

  // 等待数据 + 路由兜底（id 无效时不渲染操作区，避免误触）
  if (isLoading || !user) {
    return (
      <PageShell>
        <BackLink />
        <PageHeader title="用户详情" />
        <div className="py-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <Skeleton className="h-64" />
            <Skeleton className="h-64" />
          </div>
        </div>
      </PageShell>
    )
  }

  const isSelf = me?.id === user.id
  const isAdmin = user.role === 'admin'

  function handleBan(status: 'active' | 'disabled') {
    ban.mutate(
      { userId, status },
      {
        onSuccess: () => toast.success(status === 'disabled' ? '已封禁' : '已解禁'),
        onError: () => toast.error('操作失败（可能受自我保护约束）'),
      },
    )
  }

  function handleGrant() {
    grant.mutate(userId, {
      onSuccess: () => toast.success('已授权使用全局 Key'),
      onError: () => toast.error('授权失败（可能受自我保护约束）'),
    })
  }

  function handleRevoke() {
    revoke.mutate(userId, {
      onSuccess: () => toast.success('已撤销全局 Key 授权'),
      onError: () => toast.error('撤销失败'),
    })
  }

  function handleResetPassword() {
    if (!newPassword.trim()) {
      toast.error('新密码不能为空')
      return
    }
    resetPwd.mutate(
      { userId, newPassword },
      {
        onSuccess: () => {
          toast.success('密码已重置，请线下告知用户')
          setNewPassword('')
        },
        onError: () => toast.error('重置失败'),
      },
    )
  }

  const actionPending =
    ban.isPending || grant.isPending || revoke.isPending || resetPwd.isPending

  return (
    <PageShell>
      <BackLink />
      <PageHeader
        title={user.name}
        description={`@${user.username}${user.email ? ` · ${user.email}` : ''}`}
      />

      <div className="grid gap-4 py-6 sm:grid-cols-2">
        {/* 左：基本信息卡 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-[15px]">基本信息</CardTitle>
          </CardHeader>
          <CardContent className="text-[13px]">
            <div className="divide-y divide-black/[0.07] dark:divide-white/10">
            <InfoRow label="用户名">
              <span className="font-medium">@{user.username}</span>
            </InfoRow>
            <InfoRow label="姓名">
              <span className="font-medium">{user.name}</span>
            </InfoRow>
            <InfoRow label="邮箱">
              <span className="text-muted-foreground">{user.email || '—'}</span>
            </InfoRow>
            <InfoRow label="角色">
              {isAdmin ? <Badge>管理员</Badge> : <span className="text-muted-foreground">用户</span>}
            </InfoRow>
            <InfoRow label="状态">
              {user.status === 'disabled' ? (
                <Badge variant="destructive">已封禁</Badge>
              ) : (
                <span className="text-success">正常</span>
              )}
            </InfoRow>
            <InfoRow label="创建时间">
              <span className="text-muted-foreground">{formatDateTime(user.created_at)}</span>
            </InfoRow>
            <InfoRow label="最近登录">
              <span className="text-muted-foreground">
                {user.last_login_at ? formatDateTime(user.last_login_at) : '从未登录'}
              </span>
            </InfoRow>
            <InfoRow label="项目数">
              <span className="tabular-nums">{user.project_count}</span>
            </InfoRow>
            <InfoRow label="Key 来源">
              <Badge variant="outline">
                {user.has_own_llm_key ? '自配 Key' : '用全局 Key'}
              </Badge>
            </InfoRow>
            </div>
          </CardContent>
        </Card>

        {/* 右：操作卡 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-[15px]">操作</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* 账号状态：封禁/解禁（admin 自己不显示，防误锁） */}
            {!isSelf && (
              <div className="space-y-2">
                <Label className="text-[12px] text-muted-foreground">账号状态</Label>
                <div>
                  {user.status === 'active' ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={actionPending}
                      onClick={() => handleBan('disabled')}
                    >
                      封禁用户
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      disabled={actionPending}
                      onClick={() => handleBan('active')}
                    >
                      解禁用户
                    </Button>
                  )}
                </div>
              </div>
            )}

            {/* 全局 Key 授权（admin 免授权，整块隐藏） */}
            {!isAdmin && (
              <div className="space-y-2">
                <Label className="text-[12px] text-muted-foreground">全局 Key 授权</Label>
                <div className="rounded-lg border bg-muted/30 px-3 py-2 text-[12px]">
                  {user.grant_detail?.is_active ? (
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary">已授权</Badge>
                        {user.grant_detail.granted_at && (
                          <span className="text-muted-foreground">
                            自 {formatDateTime(user.grant_detail.granted_at)}
                          </span>
                        )}
                      </div>
                      {user.grant_detail.revoked_at && (
                        <div className="text-muted-foreground">
                          历史撤销：{formatDateTime(user.grant_detail.revoked_at)}
                        </div>
                      )}
                    </div>
                  ) : (
                    <span className="text-muted-foreground">未授权</span>
                  )}
                </div>
                <div>
                  {user.grant_detail?.is_active ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={actionPending}
                      onClick={handleRevoke}
                    >
                      撤销授权
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      disabled={actionPending}
                      onClick={handleGrant}
                    >
                      授权使用
                    </Button>
                  )}
                </div>
              </div>
            )}

            {/* 重置密码（admin 自己不显示，防误锁） */}
            {!isSelf && (
              <div className="space-y-2">
                <Label className="text-[12px] text-muted-foreground">重置密码</Label>
                <p className="text-[11px] text-muted-foreground">
                  重置后请通过安全渠道线下告知用户新密码。
                </p>
                <div className="flex items-center gap-2">
                  <Input
                    type="password"
                    placeholder="新密码（至少 8 位）"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    minLength={8}
                    className="flex-1"
                    autoComplete="new-password"
                  />
                  <Button
                    size="sm"
                    disabled={actionPending || !newPassword.trim()}
                    onClick={handleResetPassword}
                  >
                    确认重置
                  </Button>
                </div>
              </div>
            )}

            {/* admin 自己：只有提示 */}
            {isSelf && (
              <div className="rounded-xl border border-black/[0.07] bg-card p-4 text-center text-[12px] text-muted-foreground dark:border-white/10">
                这是您自己的账号，无法在此执行封禁/重置密码操作
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </PageShell>
  )
}

function BackLink() {
  return (
    <Link
      href="/admin/users"
      className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-3.5" />
      返回用户列表
    </Link>
  )
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  )
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
