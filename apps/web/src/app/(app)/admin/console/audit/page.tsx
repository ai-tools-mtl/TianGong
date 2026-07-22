'use client'

import { useState } from 'react'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuditLogs } from '@/lib/queries'
import type { AuditLogItem } from '@/types/api'

/**
 * /admin/console/audit 审计日志（refactor/admin-ia-phase2 切片 2）。
 *
 * 把阶段 1 主页砍掉的 Section E 填回，从 divide-y 列表升级为 Table。
 * 分页由 query 参数控制（page + size），由后端返回 total/page/size/items。
 *
 * 字段：action / actor_username / target_type / target_id / detail / created_at
 * detail 是 JSON 对象，直接 JSON.stringify 展示（保持原 Section E 行为）。
 */
const PAGE_SIZE = 20

export default function ConsoleAuditPage() {
  const [page, setPage] = useState(1)
  const { data: auditData, isLoading } = useAuditLogs(page, PAGE_SIZE)

  const items: AuditLogItem[] = auditData?.items ?? []
  const total = auditData?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <PageShell>
      <PageHeader
        title="审计日志"
        description={auditData ? `共 ${total} 条` : '管理操作记录'}
      />

      <div className="py-6">
        <Card className="overflow-hidden">
          <CardContent className="px-0 py-4">
            {isLoading ? (
              <div className="space-y-2 px-6">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-10" />
                ))}
              </div>
            ) : items.length === 0 ? (
              <div className="px-6">
                <EmptyState description="暂无记录" />
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>操作</TableHead>
                    <TableHead>操作人</TableHead>
                    <TableHead>目标</TableHead>
                    <TableHead>详情</TableHead>
                    <TableHead>时间</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell className="font-medium">{a.action}</TableCell>
                      <TableCell className="text-muted-foreground">
                        @{a.actor_username}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {a.target_type}
                        {a.target_id ? `:${a.target_id.slice(0, 8)}` : ''}
                      </TableCell>
                      <TableCell className="max-w-[400px]">
                        {a.detail ? (
                          <code className="block truncate text-[12px] text-muted-foreground" title={JSON.stringify(a.detail)}>
                            {JSON.stringify(a.detail)}
                          </code>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-[12px] text-muted-foreground">
                        {a.created_at ? formatDateTime(a.created_at) : ''}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>

          {/* 分页（内嵌于卡片底部，发丝线分隔，形成统一面板） */}
          {auditData && items.length > 0 && (
            <div className="flex items-center justify-between border-t border-black/[0.07] px-6 py-3 text-[12px] text-muted-foreground dark:border-white/10">
              <span>
                第 {page} / {totalPages} 页（每页 {PAGE_SIZE} 条）
              </span>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  上一页
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={items.length < PAGE_SIZE || page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>
    </PageShell>
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
