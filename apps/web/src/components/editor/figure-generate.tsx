'use client'

import { Loader2, Sparkles, RefreshCw, Trash2, Check, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { getChatDefaultSource } from '@/lib/llm-source'
import type { Figure } from '@/types/api'

interface FigureGenerateProps {
  sectionId: string
  projectId: string
  /** 生成确认后把图片插入编辑器 */
  onInsertImage: (src: string, alt: string) => void
}

type Phase = 'idle' | 'generating' | 'preview'

const DIAGRAM_TYPES = [
  { value: '', label: '通用' },
  { value: 'flowchart', label: '流程图' },
  { value: 'architecture', label: '系统架构图' },
  { value: 'sequence', label: '时序图' },
  { value: 'block', label: '模块框图' },
  { value: 'state', label: '状态图' },
]

export function FigureGenerate({ sectionId, projectId, onInsertImage }: FigureGenerateProps) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [prompt, setPrompt] = useState('')
  const [diagramType, setDiagramType] = useState('')
  const [figure, setFigure] = useState<Figure | null>(null)

  // 进入组件时拉取该章节已有的最近一张附图（支持继续操作：插入/重生成/删除）
  useEffect(() => {
    api.listFigures(projectId).then((figs) => {
      const mine = figs.filter((f) => f.section_id === sectionId)
      if (mine.length > 0) setFigure(mine[0]) // 列表按创建时间倒序，第一个最新
    }).catch(() => {})
  }, [projectId, sectionId])

  async function handleGenerate() {
    const source = getChatDefaultSource()
    if (!source) {
      toast.error('请先在设置中选择 LLM 源')
      return
    }
    setPhase('generating')
    try {
      const fig = await api.generateFigure(sectionId, {
        prompt,
        diagram_type: diagramType || null,
        chat_source: source,
      })
      setFigure(fig)
      setPhase('preview')
      toast.success('附图已生成')
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? '生成失败'
      toast.error(msg)
      setPhase('idle')
    }
  }

  async function handleRegenerate() {
    if (!figure) return
    const source = getChatDefaultSource()
    if (!source) {
      toast.error('请先在设置中选择 LLM 源')
      return
    }
    setPhase('generating')
    try {
      const fig = await api.regenerateFigure(figure.id, {
        prompt: prompt || undefined,
        chat_source: source,
      })
      setFigure(fig)
      setPhase('preview')
      toast.success('已重新生成')
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? '重新生成失败'
      toast.error(msg)
      setPhase('preview')
    }
  }

  async function handleDelete() {
    if (!figure) return
    try {
      await api.deleteFigure(figure.id)
      setFigure(null)
      setPhase('idle')
      toast.success('已删除')
    } catch {
      toast.error('删除失败')
    }
  }

  function handleInsert() {
    if (!figure?.attachment_id) return
    const src = api.attachmentUrl(projectId, figure.attachment_id)
    onInsertImage(src, figure.prompt)
    toast.success('已插入文档')
  }

  // idle：展开输入区
  if (phase === 'idle' && !figure) {
    return (
      <div className="flex flex-col gap-2 rounded-md border border-dashed p-2">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          <Sparkles className="size-3.5" />
          AI 生成附图
        </div>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="描述要画的图，如「一种基于大模型的专利撰写流程，客户端→API网关→Agent→数据库」"
          className="min-h-[60px] w-full resize-y rounded border bg-background px-2 py-1.5 text-sm"
        />
        <div className="flex items-center gap-2">
          <select
            value={diagramType}
            onChange={(e) => setDiagramType(e.target.value)}
            className="h-8 rounded border bg-background px-2 text-sm"
          >
            {DIAGRAM_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <Button
            size="sm"
            className="h-8 gap-1.5"
            disabled={!prompt.trim()}
            onClick={handleGenerate}
          >
            <Sparkles className="size-3.5" />
            生成
          </Button>
        </div>
      </div>
    )
  }

  // generating：loading
  if (phase === 'generating') {
    return (
      <div className="flex items-center gap-2 rounded-md border border-dashed p-3 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        正在生成附图（LLM 生成图结构 + 渲染，约 10-30 秒）...
      </div>
    )
  }

  // preview：显示图 + 操作按钮
  return (
    <div className="flex flex-col gap-2 rounded-md border p-2">
      {figure?.attachment_id && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={api.attachmentUrl(projectId, figure.attachment_id)}
          alt={figure.prompt}
          className="max-h-[300px] w-full rounded border object-contain"
        />
      )}
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder={figure?.prompt ?? '描述要画的图'}
        className="min-h-[40px] w-full resize-y rounded border bg-background px-2 py-1.5 text-sm"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" className="h-8 gap-1.5" onClick={handleInsert} disabled={!figure?.attachment_id}>
          <Check className="size-3.5" />
          插入文档
        </Button>
        <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={handleRegenerate}>
          <RefreshCw className="size-3.5" />
          重新生成
        </Button>
        <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={handleDelete}>
          <Trash2 className="size-3.5" />
          删除
        </Button>
        <Button
          size="sm" variant="ghost" className="h-8 gap-1.5 ml-auto"
          onClick={() => { setFigure(null); setPhase('idle'); setPrompt('') }}
        >
          <X className="size-3.5" />
          收起
        </Button>
      </div>
    </div>
  )
}
