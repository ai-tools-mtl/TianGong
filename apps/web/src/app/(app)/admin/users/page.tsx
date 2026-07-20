'use client'

import Link from 'next/link'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  useBanUser,
  useGrantGlobalLLM,
  useRevokeGlobalLLM,
  useUsers,
} from '@/lib/queries'
import { useAuthStore } from '@/stores/auth'
import type { AdminUser } from '@/types/api'

/**
 * /admin/users 用户列表（refactor/admin-ia-phase1 切片 1）。
 *
 * 阶段 1 把这部分从主页砍掉，本切片填回来。展示 Table + 平铺操作按钮（原 Section B 风格）。
 * 操作按钮可见性规则（前端预判 + 后端 service 层兜底 403）：
 *   - admin 角色（管理员）：免授权，不显示「授权/撤销」按钮
 *   - 当前登录用户自己：不显示「封禁/解禁/重置密码」（防误锁自己）
 *   - 自我保护由后端 admin_service._get_and_guard 强制（封超管/其他管理员一律 403）
 */
export default function UsersPage() {
  const { data: users, isLoading } = useUsers()
  const me = useAuthStore((s) => s.user)

  const ban = useBanUser()
  const grant = useGrantGlobalLLM()
  const revoke = useRevokeGlobalLLM()

  // toast 在调用方处理（遵循 review-workbench.tsx 模式，hook 内部只失效缓存）。
  function handleBan(u: AdminUser, status: 'active' | 'disabled') {
    ban.mutate(
      { userId: u.id, status },
      {
        onSuccess: () => toast.success(status === 'disabled' ? '已封禁' : '已解禁'),
        onError: () => toast.error('操作失败（可能受自我保护约束）'),
      },
    )
  }

  function handleGrant(u: AdminUser) {
    grant.mutate(u.id, {
      onSuccess: () => toast.success('已授权使用全局 Key'),
      onError: () => toast.error('授权失败（可能受自我保护约束）'),
    })
  }

  function handleRevoke(u: AdminUser) {
    revoke.mutate(u.id, {
      onSuccess: () => toast.success('已撤销全局 Key 授权'),
      onError: () => toast.error('撤销失败'),
    })
  }

  const list: AdminUser[] = users ?? []
  // 任意 mutation pending 时禁用所有按钮，避免并发误操作。
  const actionPending =
    ban.isPending || grant.isPending || revoke.isPending

  return (
    <PageShell>
      <PageHeader title="用户管理" description={`${list.length} 个用户`} />
      <div className="py-6">
        {isLoading ? (
          <UsersTableSkeleton />
        ) : list.length === 0 ? (
          <div className="rounded-lg border border-dashed p-12 text-center text-sm text-muted-foreground">
            暂无用户
          </div>
        ) : (
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[180px]">用户</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>全局 Key</TableHead>
                  <TableHead>项目</TableHead>
                  <TableHead>Key 来源</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((u) => {
                  const isSelf = me?.id === u.id
                  const isAdmin = u.role === 'admin'
                  return (
                    <TableRow key={u.id}>
                      {/* 用户名 */}
                      <TableCell>
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-1.5">
                            <Link
                              href={`/admin/users/${u.id}`}
                              className="text-[13px] font-medium hover:underline"
                            >
                              {u.name}
                            </Link>
                            <span className="text-[12px] text-muted-foreground">
                              @{u.username}
                            </span>
                          </div>
                          {u.email && (
                            <span className="text-[11px] text-muted-foreground">
                              {u.email}
                            </span>
                          )}
                        </div>
                      </TableCell>

                      {/* 角色 */}
                      <TableCell>
                        {isAdmin ? (
                          <Badge>管理员</Badge>
                        ) : (
                          <span className="text-[12px] text-muted-foreground">
                            用户
                          </span>
                        )}
                      </TableCell>

                      {/* 状态 */}
                      <TableCell>
                        {u.status === 'disabled' ? (
                          <Badge variant="destructive">已封禁</Badge>
                        ) : (
                          <span className="text-[12px] text-emerald-600">正常</span>
                        )}
                      </TableCell>

                      {/* 全局 Key 授权 */}
                      <TableCell>
                        {u.has_global_grant ? (
                          <Badge
                            variant="secondary"
                            className="bg-emerald-100 text-emerald-700"
                          >
                            已授权
                          </Badge>
                        ) : (
                          <span className="text-[12px] text-muted-foreground">—</span>
                        )}
                      </TableCell>

                      {/* 项目数 */}
                      <TableCell className="text-[12px] tabular-nums">
                        {u.project_count}
                      </TableCell>

                      {/* Key 来源 */}
                      <TableCell className="text-[12px] text-muted-foreground">
                        {u.has_own_llm_key ? '自配 Key' : '用全局 Key'}
                      </TableCell>

                      {/* 创建时间 */}
                      <TableCell className="text-[12px] text-muted-foreground">
                        {formatDate(u.created_at)}
                      </TableCell>

                      {/* 操作按钮组（平铺） */}
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          {/* admin 免授权 → 不显示授权/撤销 */}
                          {!isAdmin && !u.has_global_grant && (
                            <Button
                              size="xs"
                              variant="outline"
                              disabled={actionPending}
                              onClick={() => handleGrant(u)}
                            >
                              授权
                            </Button>
                          )}
                          {!isAdmin && u.has_global_grant && (
                            <Button
                              size="xs"
                              variant="outline"
                              disabled={actionPending}
                              onClick={() => handleRevoke(u)}
                            >
                              撤销
                            </Button>
                          )}
                          {/* 不对自己显示封禁/解禁（防误锁） */}
                          {!isSelf && u.status === 'active' && (
                            <Button
                              size="xs"
                              variant="outline"
                              disabled={actionPending}
                              onClick={() => handleBan(u, 'disabled')}
                            >
                              封禁
                            </Button>
                          )}
                          {!isSelf && u.status !== 'active' && (
                            <Button
                              size="xs"
                              variant="outline"
                              disabled={actionPending}
                              onClick={() => handleBan(u, 'active')}
                            >
                              解禁
                            </Button>
                          )}
                          <Button size="xs" variant="ghost" asChild>
                            <Link href={`/admin/users/${u.id}`}>详情</Link>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </PageShell>
  )
}

function UsersTableSkeleton() {
  return (
    <div className="rounded-lg border">
      <div className="space-y-2 p-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-5 w-12" />
            <Skeleton className="h-5 w-12" />
            <Skeleton className="h-5 w-12" />
            <Skeleton className="h-5 w-8" />
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-5 w-20" />
            <Skeleton className="ml-auto h-5 w-32" />
          </div>
        ))}
      </div>
    </div>
  )
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}
