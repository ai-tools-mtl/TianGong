'use client'

import { useState } from 'react'
import { Eye, Loader2, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { TiptapEditor } from '@/components/editor/tiptap-editor'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import type { SupportView } from '@/types/api'

/**
 * /admin/console/support-view — 凭授权码临时查看用户项目（§8.3 完整版）。
 *
 * 用户提供 8 位一次性授权码 → 核销（开 30 分钟查看窗口）→ 窗口内可刷新
 * 重复查看。只读渲染复用游客页的 TiptapEditor（editable=false）。每次
 * 访问后端都写审计（support_view_project）。
 */
export default function SupportViewPage() {
  const [code, setCode] = useState('')
  const [view, setView] = useState<SupportView | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleRedeem() {
    const trimmed = code.trim().toUpperCase()
    if (!trimmed) return
    setBusy(true)
    try {
      const data = view
        ? await api.viewSupportProject(trimmed) // 窗口内刷新
        : await api.redeemSupportCode(trimmed)
      setView(data)
      toast.success('已授权查看（30 分钟窗口）')
    } catch (err: unknown) {
      setView(null)
      toast.error((err as { message?: string })?.message ?? '授权码无效或已失效')
    } finally {
      setBusy(false)
    }
  }

  return (
    <PageShell>
      <PageHeader
        title="支持查看"
        description="凭用户提供的授权码，限时只读查看其项目（全程审计，30 分钟窗口）"
      />
      <div className="space-y-4 py-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="size-4" />
              输入授权码
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex gap-2">
              <Input
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleRedeem()
                  }
                }}
                placeholder="8 位授权码"
                maxLength={8}
                className="h-9 font-mono tracking-[0.3em]"
              />
              <Button onClick={handleRedeem} disabled={busy || !code.trim()} className="gap-1.5">
                {busy ? <Loader2 className="size-4 animate-spin" /> : <Eye className="size-4" />}
                {view ? '刷新查看' : '核销查看'}
              </Button>
            </div>
            {view && (
              <p className="text-xs text-muted-foreground">
                求助用户：{view.owner_name ?? view.owner_id} · 项目：{view.project_title}
                （窗口至 {new Date(view.view_expires_at).toLocaleTimeString('zh-CN')}）
              </p>
            )}
          </CardContent>
        </Card>

        {view && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                {view.project_title}
                <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground">
                  只读
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="max-w-none space-y-8">
                {view.project.sections.map((s) => (
                  <section key={s.order} className="space-y-2">
                    <h3 className="text-base font-semibold tracking-tight">{s.title}</h3>
                    {s.content ? (
                      <TiptapEditor content={s.content} editable={false} />
                    ) : (
                      <p className="text-sm text-muted-foreground">（待填写）</p>
                    )}
                  </section>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </PageShell>
  )
}
