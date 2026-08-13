'use client'

import { Loader2, Sparkles, RefreshCw, Trash2, Check, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { getChatDefaultSource } from '@/lib/llm-source'
import { useAuthImage } from '@/lib/use-auth-image'
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

const STYLE_OPTIONS = [
  { value: 'patent-bw', label: '专利黑白' },
  { value: 'clean-color', label: '清晰彩色' },
  { value: 'technical', label: '技术灰度' },
]
const DEFAULT_STYLE = 'patent-bw'
const STYLE_STORAGE_KEY = 'tg_figure_style'

function readStoredStyle(): string {
  if (typeof window === 'undefined') return DEFAULT_STYLE
  return window.localStorage.getItem(STYLE_STORAGE_KEY) || DEFAULT_STYLE
}

export function FigureGenerate({ sectionId, projectId, onInsertImage }: FigureGenerateProps) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [prompt, setPrompt] = useState('')
  const [diagramType, setDiagramType] = useState('')
  const [style, setStyle] = useState<string>(readStoredStyle)
  const [figure, setFigure] = useState<Figure | null>(null)
  const [captionText, setCaptionText] = useState('')
  const [captioning, setCaptioning] = useState(false)

  // 鉴权图片加载：fetch + credentials 转 blob URL，绕过 <img> 跨端口 cookie 限制
  const imgUrl = figure?.attachment_id ? api.attachmentUrl(projectId, figure.attachment_id) : null
  const authedImgUrl = useAuthImage(imgUrl)

  // 进入组件时拉取该章节已有的最近一张附图（支持继续操作：插入/重生成/删除）
  useEffect(() => {
    api.listFigures(projectId).then((figs) => {
      const mine = figs.filter((f) => f.section_id === sectionId)
      if (mine.length > 0) setFigure(mine[0]) // 列表按创建时间倒序，第一个最新
    }).catch(() => {})
  }, [projectId, sectionId])

  function changeStyle(v: string) {
    setStyle(v)
    if (typeof window !== 'undefined') window.localStorage.setItem(STYLE_STORAGE_KEY, v)
  }

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
        style,
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
        style,
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

  async function handleCaption() {
    if (!figure?.attachment_id) return
    const source = getChatDefaultSource()
    if (!source) {
      toast.error('请先在设置中选择 LLM 源')
      return
    }
    setCaptioning(true)
    setCaptionText('')
    try {
      await api.captionFigures(
        sectionId,
        { attachment_ids: [figure.attachment_id], chat_source: source },
        (t) => setCaptionText((prev) => prev + t),
      )
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? '图注生成失败'
      toast.error(msg)
    } finally {
      setCaptioning(false)
    }
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
          <select
            value={style}
            onChange={(e) => changeStyle(e.target.value)}
            className="h-8 rounded border bg-background px-2 text-sm"
            title="风格预设（专利黑白符合专利局正式申请标准）"
          >
            {STYLE_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
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
        authedImgUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={authedImgUrl}
            alt={figure.prompt}
            className="max-h-[300px] w-full rounded border object-contain"
          />
        ) : (
          <div className="flex h-[120px] items-center justify-center rounded border bg-muted/30 text-xs text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            图片加载中...
          </div>
        )
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
        <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={handleCaption} disabled={captioning || !figure?.attachment_id}>
          {captioning ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
          {captioning ? '生成中...' : 'AI 看图写注'}
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
          onClick={() => { setFigure(null); setPhase('idle'); setPrompt(''); setCaptionText('') }}
        >
          <X className="size-3.5" />
          收起
        </Button>
      </div>
      {captionText && (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">AI 生成的图注（可复制到正文）：</p>
          <textarea
            value={captionText}
            readOnly
            className="min-h-[60px] w-full resize-y rounded border bg-muted/30 px-2 py-1.5 text-sm"
          />
        </div>
      )}
    </div>
  )
}
