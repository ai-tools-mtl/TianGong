'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import type { FigurePreset } from '@/types/api'

/**
 * /admin/console/figure-presets — 附图风格预设管理。
 *
 * 3 个内置预设（patent-bw 专利黑白 / clean-color 清晰彩色 / technical 技术灰度），
 * admin 可微调 font_family / font_size / line_width（配色与渲染规格固定，不可改）。
 * patent-bw 符合中国专利局《专利审查指南》正式申请标准（纯黑白线条图）。
 */
export default function FigurePresetsPage() {
  const [presets, setPresets] = useState<Record<string, FigurePreset> | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  // 本地编辑态：{ preset_id: { font_family, font_size, line_width } }
  const [edits, setEdits] = useState<Record<string, { font_family: string; font_size: number; line_width: number }>>({})

  useEffect(() => {
    api.getFigurePresets().then((res) => {
      setPresets(res.presets)
      // 初始化编辑态
      const e: Record<string, { font_family: string; font_size: number; line_width: number }> = {}
      for (const [id, p] of Object.entries(res.presets)) {
        e[id] = { font_family: p.font_family, font_size: p.font_size, line_width: p.line_width }
      }
      setEdits(e)
    }).finally(() => setLoading(false))
  }, [])

  async function handleSave(presetId: string) {
    const e = edits[presetId]
    if (!e) return
    setSaving(presetId)
    try {
      const updated = await api.setFigurePreset(presetId, e)
      setPresets((prev) => prev ? { ...prev, [presetId]: updated } : prev)
      toast.success(`${presets?.[presetId]?.label ?? presetId} 已更新`)
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message ?? '保存失败')
    } finally {
      setSaving(null)
    }
  }

  if (loading) {
    return (
      <PageShell>
        <PageHeader title="附图风格预设" description="专利附图配色与渲染规格" />
        <Skeleton className="h-40 w-full" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader
        title="附图风格预设"
        description="3 个内置预设，可微调字体/字号/线宽。配色与渲染规格（300DPI/白边距）固定不可改"
      />
      <div className="space-y-4 py-4">
        {presets && Object.entries(presets).map(([id, p]) => {
          const e = edits[id]
          const dirty = e && (e.font_family !== p.font_family || e.font_size !== p.font_size || e.line_width !== p.line_width)
          return (
            <Card key={id}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  {p.label}
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{id}</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {/* 配色预览（只读展示） */}
                <div className="flex flex-wrap gap-2">
                  {Object.entries(p.colors).slice(0, 5).map(([shape, style]) => {
                    const fill = style.match(/fillColor=([^;]+)/)?.[1] || '#ffffff'
                    const stroke = style.match(/strokeColor=([^;]+)/)?.[1] || '#000000'
                    return (
                      <div key={shape} className="flex items-center gap-1 text-xs text-muted-foreground">
                        <span
                          className="inline-block size-4 rounded border"
                          style={{ background: fill, borderColor: stroke }}
                        />
                        {shape}
                      </div>
                    )
                  })}
                </div>
                {/* 渲染规格（只读） */}
                <p className="text-xs text-muted-foreground">
                  渲染：{p.render.scale}×缩放（≈{p.render.scale * 96}DPI）· {p.render.border}px 白边距
                </p>
                {/* 可微调字段 */}
                {e && (
                  <div className="grid grid-cols-3 gap-3">
                    <div className="space-y-1">
                      <Label className="text-xs">字体</Label>
                      <Input
                        value={e.font_family}
                        onChange={(ev) => setEdits({ ...edits, [id]: { ...e, font_family: ev.target.value } })}
                        className="h-8 text-sm"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">字号</Label>
                      <Input
                        type="number"
                        value={e.font_size}
                        onChange={(ev) => setEdits({ ...edits, [id]: { ...e, font_size: Number(ev.target.value) } })}
                        className="h-8 text-sm"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">线宽</Label>
                      <Input
                        type="number"
                        step="0.5"
                        value={e.line_width}
                        onChange={(ev) => setEdits({ ...edits, [id]: { ...e, line_width: Number(ev.target.value) } })}
                        className="h-8 text-sm"
                      />
                    </div>
                  </div>
                )}
                <Button
                  size="sm"
                  className="h-8"
                  disabled={!dirty || saving === id}
                  onClick={() => handleSave(id)}
                >
                  {saving === id ? '保存中...' : '保存'}
                </Button>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </PageShell>
  )
}
