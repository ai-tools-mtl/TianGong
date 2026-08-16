'use client'

import { useEffect, useState } from 'react'
import { ShieldQuestion } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'

/**
 * /admin/console/hitl — HITL 工具确认配置。
 *
 * 配置 agent 哪些工具在执行前需要用户确认（对话面板弹「同意/拒绝」卡片）。
 * 默认拦 generate_figure（LLM + drawio 渲染较贵）；MCP 工具按名添加。
 * interrupt 断点依赖 checkpoint——后端 checkpoint 不可用时会自动放行全部工具。
 */
export default function HitlConfigPage() {
  const [enabled, setEnabled] = useState(true)
  const [tools, setTools] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [newTool, setNewTool] = useState('')

  useEffect(() => {
    api.getHitlConfig().then((cfg) => {
      setEnabled(cfg.enabled)
      setTools(cfg.tools)
    }).finally(() => setLoading(false))
  }, [])

  function toggleEnabled() {
    setEnabled((v) => !v)
    setDirty(true)
  }

  function removeTool(i: number) {
    setTools((t) => t.filter((_, idx) => idx !== i))
    setDirty(true)
  }

  function addTool() {
    const name = newTool.trim()
    if (!name) return
    if (tools.includes(name)) {
      toast.info('该工具已在拦截清单中')
      return
    }
    setTools((t) => [...t, name])
    setNewTool('')
    setDirty(true)
  }

  async function handleSave() {
    setSaving(true)
    try {
      const saved = await api.setHitlConfig({ enabled, tools })
      setEnabled(saved.enabled)
      setTools(saved.tools)
      setDirty(false)
      toast.success('HITL 配置已更新')
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message ?? '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <PageShell>
        <PageHeader title="工具确认（HITL）" description="agent 工具执行前的人工确认" />
        <Skeleton className="h-40 w-full" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader
        title="工具确认（HITL）"
        description="配置 agent 哪些工具执行前需要用户在对话中确认。断点由 checkpoint 持久化，用户同意/拒绝后从断点续跑"
      />
      <div className="space-y-4 py-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldQuestion className="size-4" />
              拦截清单
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">{enabled ? '已启用' : '已停用'}</div>
                <div className="text-xs text-muted-foreground">
                  停用后所有工具直接执行，不再弹确认
                </div>
              </div>
              <Button variant={enabled ? 'default' : 'outline'} size="sm" onClick={toggleEnabled}>
                {enabled ? '停用' : '启用'}
              </Button>
            </div>
            <div className="space-y-2">
              <Label className="text-xs">拦截的工具名（每行一个概念：内置工具如 generate_figure，MCP 工具按名配置）</Label>
              {tools.length === 0 && (
                <p className="text-xs text-muted-foreground">清单为空 = 不拦任何工具</p>
              )}
              <div className="space-y-2">
                {tools.map((t, i) => (
                  <div key={t} className="flex items-center gap-2">
                    <Input
                      value={t}
                      readOnly
                      className="h-8 flex-1 font-mono text-sm"
                    />
                    <Button variant="outline" size="sm" className="h-8" onClick={() => removeTool(i)}>
                      移除
                    </Button>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <Input
                  value={newTool}
                  onChange={(e) => setNewTool(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      addTool()
                    }
                  }}
                  placeholder="输入工具名后回车添加"
                  className="h-8 flex-1 font-mono text-sm"
                />
                <Button variant="outline" size="sm" className="h-8" onClick={addTool}>
                  添加
                </Button>
              </div>
            </div>
            <Button size="sm" className="h-8" disabled={!dirty || saving} onClick={handleSave}>
              {saving ? '保存中...' : '保存'}
            </Button>
          </CardContent>
        </Card>
      </div>
    </PageShell>
  )
}
