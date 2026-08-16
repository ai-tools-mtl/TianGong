'use client'

import { useEffect, useState } from 'react'
import { Eye } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'

/**
 * /admin/console/vision-markers — vision 模型探测名单配置。
 *
 * 内置保守名单（gpt-4o/claude-3/glm-4v/qwen-vl/-vl/-vision 等）之外，admin 可
 * 追加自有模型的标记（小写子串匹配，与内置合并）；enabled=False 全局禁用
 * vision（图注一律走文字降级）。名单刻意保守：误判会触发不支持的图片请求报错，
 * 漏判只是降级文字描述（安全方向）。
 */
export default function VisionMarkersPage() {
  const [enabled, setEnabled] = useState(true)
  const [markers, setMarkers] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [newMarker, setNewMarker] = useState('')

  useEffect(() => {
    api.getVisionMarkers().then((cfg) => {
      setEnabled(cfg.enabled)
      setMarkers(cfg.extra_markers)
    }).finally(() => setLoading(false))
  }, [])

  function toggleEnabled() {
    setEnabled((v) => !v)
    setDirty(true)
  }

  function removeMarker(i: number) {
    setMarkers((m) => m.filter((_, idx) => idx !== i))
    setDirty(true)
  }

  function addMarker() {
    const m = newMarker.trim().toLowerCase()
    if (!m) return
    if (markers.includes(m)) {
      toast.info('该标记已存在')
      return
    }
    setMarkers((t) => [...t, m])
    setNewMarker('')
    setDirty(true)
  }

  async function handleSave() {
    setSaving(true)
    try {
      const saved = await api.setVisionMarkers({ enabled, extra_markers: markers })
      setEnabled(saved.enabled)
      setMarkers(saved.extra_markers)
      setDirty(false)
      toast.success('vision 名单已更新')
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message ?? '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <PageShell>
        <PageHeader title="Vision 模型名单" description="图注看图说话的模型能力探测" />
        <Skeleton className="h-40 w-full" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader
        title="Vision 模型名单"
        description="内置保守名单之外的追加标记（小写子串匹配）；停用后图注一律走文字降级"
      />
      <div className="space-y-4 py-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Eye className="size-4" />
              追加标记
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">{enabled ? '已启用' : '已停用'}</div>
                <div className="text-xs text-muted-foreground">
                  停用后所有模型都按「不支持图片」处理，图注走文字描述降级
                </div>
              </div>
              <Button variant={enabled ? 'default' : 'outline'} size="sm" onClick={toggleEnabled}>
                {enabled ? '停用' : '启用'}
              </Button>
            </div>
            <div className="space-y-2">
              <Label className="text-xs">
                追加的模型名标记（与内置名单合并；小写子串匹配，如 my-model-vision）
              </Label>
              {markers.length === 0 && (
                <p className="text-xs text-muted-foreground">无追加标记 = 仅用内置名单</p>
              )}
              <div className="space-y-2">
                {markers.map((m, i) => (
                  <div key={m} className="flex items-center gap-2">
                    <Input value={m} readOnly className="h-8 flex-1 font-mono text-sm" />
                    <Button variant="outline" size="sm" className="h-8" onClick={() => removeMarker(i)}>
                      移除
                    </Button>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <Input
                  value={newMarker}
                  onChange={(e) => setNewMarker(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      addMarker()
                    }
                  }}
                  placeholder="输入模型名标记后回车添加"
                  className="h-8 flex-1 font-mono text-sm"
                />
                <Button variant="outline" size="sm" className="h-8" onClick={addMarker}>
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
