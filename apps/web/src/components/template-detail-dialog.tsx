'use client'

import { Eye, Layers, ListOrdered, Loader2, Palette } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { SectionLabel } from '@/components/ui/section-label'
import { useTemplate } from '@/lib/queries'
import type { TemplateSection, TemplateStatus } from '@/types/api'

const STATUS_BADGE: Record<TemplateStatus, { label: string; className?: string }> = {
  draft: { label: '草稿', className: 'bg-muted text-muted-foreground' },
  published: { label: '已发布', className: 'bg-success/10 text-success' },
  offline: { label: '已下线', className: 'bg-muted text-muted-foreground' },
}

interface TemplateDetailDialogProps {
  templateId: string
  templateName: string
  status?: TemplateStatus
}

export function TemplateDetailDialog({ templateId, templateName, status }: TemplateDetailDialogProps) {
  const { data: tpl, isLoading, isError, error } = useTemplate(templateId)

  const statusCfg = status ? STATUS_BADGE[status] : null

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button size="xs" variant="ghost" className="gap-1">
          <Eye className="size-3" />
          查看
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>模板详情</DialogTitle>
          <DialogDescription>
            {templateName} — 章节结构、样式与编号配置
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            加载中...
          </div>
        ) : isError ? (
          <EmptyState description={(error as { message?: string })?.message || '加载模板详情失败'} />
        ) : tpl ? (
          <div className="space-y-4 pt-2">
            {/* ── 基本信息 ── */}
            <section>
              <div className="mb-2">
                <SectionLabel>基本信息</SectionLabel>
              </div>
              <div className="space-y-1.5 text-sm">
                {tpl.source_filename && (
                  <div className="flex gap-2">
                    <span className="shrink-0 text-muted-foreground">源文件</span>
                    <span>{tpl.source_filename}</span>
                  </div>
                )}
                <div className="flex gap-2">
                  <span className="shrink-0 text-muted-foreground">创建时间</span>
                  <span>{new Date(tpl.created_at).toLocaleString('zh-CN')}</span>
                </div>
                <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                  {statusCfg && (
                    <span
                      className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${statusCfg.className ?? ''}`}
                    >
                      {statusCfg.label}
                    </span>
                  )}
                  {tpl.is_system && (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      系统模板
                    </span>
                  )}
                  {tpl.is_default && (
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      默认模板
                    </span>
                  )}
                </div>
              </div>
            </section>

            {/* ── 章节结构 ── */}
            <section>
              <div className="mb-2 flex items-center gap-1.5">
                <Layers className="size-3.5" />
                <SectionLabel>章节结构</SectionLabel>
                <span className="text-[10px] normal-case tracking-normal text-muted-foreground">
                  （{tpl.structure.length} 个章节）
                </span>
              </div>
              {tpl.structure.length === 0 ? (
                <EmptyState description="暂无章节" />
              ) : (
                <div className="space-y-1">
                  {tpl.structure.map((s: TemplateSection) => (
                    <div
                      key={s.id ?? s.key}
                      className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2"
                    >
                      <div className="flex min-w-0 flex-1 items-center gap-2">
                        <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
                          {s.order}.
                        </span>
                        <span className="block truncate text-[13px] font-medium" title={s.title}>{s.title}</span>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <code className="text-[11px] text-muted-foreground">{s.key}</code>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          L{s.level}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* ── 样式配置 ── */}
            <section>
              <div className="mb-2 flex items-center gap-1.5">
                <Palette className="size-3.5" />
                <SectionLabel>样式配置</SectionLabel>
              </div>
              {tpl.styles && Object.keys(tpl.styles).length > 0 ? (
                <pre className="max-h-48 overflow-y-auto rounded-lg border bg-muted/30 p-3 text-xs leading-relaxed">
                  {JSON.stringify(tpl.styles, null, 2)}
                </pre>
              ) : (
                <EmptyState description="无样式配置" />
              )}
            </section>

            {/* ── 编号配置 ── */}
            <section>
              <div className="mb-2 flex items-center gap-1.5">
                <ListOrdered className="size-3.5" />
                <SectionLabel>编号配置</SectionLabel>
              </div>
              {tpl.numbering && Object.keys(tpl.numbering).length > 0 ? (
                <pre className="max-h-48 overflow-y-auto rounded-lg border bg-muted/30 p-3 text-xs leading-relaxed">
                  {JSON.stringify(tpl.numbering, null, 2)}
                </pre>
              ) : (
                <EmptyState description="无编号配置" />
              )}
            </section>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
