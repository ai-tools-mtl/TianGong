'use client'

import { Loader2, Sparkles, RefreshCw, Trash2, Check, Plus, X, ListOrdered } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { getChatDefaultSource } from '@/lib/llm-source'
import { queryKeys } from '@/lib/queries'
import { useAuthImage } from '@/lib/use-auth-image'
import type { Figure, Section } from '@/types/api'

import { ImageLightbox } from './image-lightbox'

interface FigureGenerateProps {
  sectionId: string
  projectId: string
  /** 生成确认后把图片插入编辑器（图号系统 V1：图片 + 「图N：…」图注段落） */
  onInsertImageWithCaption: (src: string, alt: string, caption: string) => void
  /** 生成/替换附图说明清单块（图号系统 V1：重复点击替换旧块） */
  onInsertDrawingList: (lines: string[]) => void
}

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

/**
 * 缩略图条单项。独立成组件是为了合法使用 useAuthImage（每实例一个 hook，
 * 不能在父组件的 map 里循环调用）。
 */
function FigureThumb({
  figure,
  projectId,
  active,
  onClick,
  version,
}: {
  figure: Figure
  projectId: string
  active: boolean
  onClick: () => void
  /** 内容版本（父组件 regenerate 后 bump）：URL 不变也要重新拉取覆写后的新图 */
  version?: number
}) {
  const src = figure.attachment_id ? api.attachmentUrl(projectId, figure.attachment_id) : null
  const authed = useAuthImage(src, version)
  return (
    <button
      type="button"
      onClick={onClick}
      title={figure.prompt}
      className={`relative h-16 w-24 shrink-0 overflow-hidden rounded border bg-muted/30 transition-opacity ${
        active ? 'ring-2 ring-primary' : 'opacity-75 hover:opacity-100'
      }`}
    >
      {authed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={authed} alt={figure.prompt} className="h-full w-full object-contain" />
      ) : (
        <Loader2 className="absolute inset-0 m-auto size-4 animate-spin text-muted-foreground" />
      )}
      {/* 图号徽标（项目内连续编号，删除后服务端重排） */}
      <span className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[10px] font-medium text-white">
        图{figure.number}
      </span>
    </button>
  )
}

/**
 * AI 生成附图面板（多图）。后端每次生成都是新插一条 Figure（无数量限制），
 * 本面板维护该章节的全部附图：横向缩略图条切换选中图，逐张插入/重生成/删除。
 */
export function FigureGenerate({ sectionId, projectId, onInsertImageWithCaption, onInsertDrawingList }: FigureGenerateProps) {
  const qc = useQueryClient()
  const [figures, setFigures] = useState<Figure[]>([]) // 创建时间倒序（同后端 list）
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // 首次拉取完成前不渲染，避免「先闪空表单、再变缩略图条」
  const [loaded, setLoaded] = useState(false)
  const [formOpen, setFormOpen] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [diagramType, setDiagramType] = useState('')
  const [style, setStyle] = useState<string>(readStoredStyle)
  const [captionText, setCaptionText] = useState('')
  const [capDesc, setCapDesc] = useState('')
  const [captioning, setCaptioning] = useState(false)
  const [zoom, setZoom] = useState(false)
  // 附图清单生成中（点击时需拉全项目图列表，防双击重复插入）
  const [listing, setListing] = useState(false)
  // regenerate 原地覆写同一附件（attachment_id/URL 均不变），bump 此版本号
  // 强制 useAuthImage 重新拉取，否则面板会一直显示覆写前的旧 blob
  const [imgVersion, setImgVersion] = useState(0)

  const selected = figures.find((f) => f.id === selectedId) ?? figures[0] ?? null

  // 鉴权图片加载：fetch + credentials 转 blob URL，绕过 <img> 跨端口 cookie 限制
  const imgUrl = selected?.attachment_id ? api.attachmentUrl(projectId, selected.attachment_id) : null
  const authedImgUrl = useAuthImage(imgUrl, imgVersion)

  // 进入时拉取该章节全部附图（多图管理：不只取最新一张）
  useEffect(() => {
    api.listFigures(projectId).then((figs) => {
      const mine = figs.filter((f) => f.section_id === sectionId)
      setFigures(mine)
      if (mine.length > 0) {
        setSelectedId(mine[0].id)
        setFormOpen(false) // 已有图：默认展示图集，要新图再点「再生成一张」
      }
      setLoaded(true)
    }).catch(() => setLoaded(true))
  }, [projectId, sectionId])

  // 切换选中图（含清理图注草稿/辅助描述——直接在调用点清，不放 effect，
  // 规避 react-hooks/set-state-in-effect）
  function selectFigure(id: string | null) {
    setSelectedId(id)
    setCaptionText('')
    setCapDesc('')
  }

  function changeStyle(v: string) {
    setStyle(v)
    if (typeof window !== 'undefined') window.localStorage.setItem(STYLE_STORAGE_KEY, v)
  }

  async function handleGenerate() {
    // source 为 null 走后端 fallback 链，不前端硬拦（同 ai-chat-panel）
    const source = getChatDefaultSource()
    setGenerating(true)
    try {
      const fig = await api.generateFigure(sectionId, {
        prompt,
        diagram_type: diagramType || null,
        chat_source: source,
        style,
      })
      setFigures((prev) => [fig, ...prev])
      selectFigure(fig.id)
      setFormOpen(false)
      setPrompt('')
      toast.success('附图已生成')
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? '生成失败'
      toast.error(msg)
    } finally {
      setGenerating(false)
    }
  }

  // 正文引用探测（best-effort）：正文图 <img src> 含 attachment id（attachmentUrl
  // 拼进 src），在 sections 缓存的 Tiptap JSON 里搜该 id 即知是否已插入正文。
  // 缓存未含最新未保存内容时探测不到——确认框兜底常显，探测命中只是文案升级。
  function referencedInBody(attachmentId: string | null | undefined): boolean {
    if (!attachmentId) return false
    const secs = qc.getQueryData<Section[]>(queryKeys.sections(projectId)) ?? []
    return secs.some((s) => !!s.content && JSON.stringify(s.content).includes(attachmentId))
  }

  async function handleRegenerate() {
    if (!selected) return
    // 后端 regenerate 原地覆写同一 attachment（attachment_id/图号均不变）——已插入
    // 正文的图会自动同步为新图，不存在失效风险，确认即可
    if (!window.confirm(`重新生成将替换图${selected.number}的内容（编号不变）；若已插入正文，正文中的图会同步更新为新图。确定继续？`)) {
      return
    }
    // source 为 null 走后端 fallback 链，不前端硬拦（同 ai-chat-panel）
    const source = getChatDefaultSource()
    setGenerating(true)
    try {
      // 不传 prompt：沿用该图的原描述重新生成；要改描述就生成一张新的
      const fig = await api.regenerateFigure(selected.id, { chat_source: source, style })
      setFigures((prev) => prev.map((f) => (f.id === fig.id ? fig : f)))
      // 覆写后 URL 不变，bump 版本号让详情图与缩略图重拉新字节
      setImgVersion((v) => v + 1)
      toast.success('已重新生成')
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? '重新生成失败'
      toast.error(msg)
    } finally {
      setGenerating(false)
    }
  }

  function applyDeleted(id: string) {
    const rest = figures.filter((f) => f.id !== id)
    setFigures(rest)
    selectFigure(rest[0]?.id ?? null)
    if (rest.length === 0) setFormOpen(true)
    toast.success('已删除')
  }

  async function handleDelete() {
    if (!selected) return
    // 两级确认：① 前端缓存快速预检（best-effort，可能滞后）；② 服务端权威探测
    // （409 带引用章节清单——缓存没看到的引用在此拦下）→ 再确认后带 force 强删。
    // 删除后服务端重排图号（后续图前移），正文「图K」文字引用需人工核对（V1 原则不自动改写）
    const inBody = referencedInBody(selected.attachment_id)
    const msg = inBody
      ? `检测到图${selected.number}已插入正文，删除后不可恢复，正文中的这张图将失效。确定删除？`
      : `删除图${selected.number}后不可恢复，后续图号将前移（正文中「图K」文字引用需手动核对）。确定删除？`
    if (!window.confirm(msg)) {
      return
    }
    try {
      await api.deleteFigure(selected.id)
      applyDeleted(selected.id)
    } catch (err: unknown) {
      const e = err as { code?: string; message?: string }
      if (e?.code !== 'conflict') {
        toast.error('删除失败')
        return
      }
      // 服务端探测到正文引用：拿权威清单再确认，确认后强制删除
      const confirmMsg =
        e.message ?? '该图已插入正文，删除后正文中的这张图将失效。'
      if (!window.confirm(`${confirmMsg}\n（此操作不可恢复）`)) {
        return
      }
      try {
        await api.deleteFigure(selected.id, true)
        applyDeleted(selected.id)
      } catch {
        toast.error('删除失败')
      }
    }
  }

  function handleInsert() {
    if (!selected?.attachment_id) return
    onInsertImageWithCaption(
      api.attachmentUrl(projectId, selected.attachment_id),
      selected.prompt,
      `图${selected.number}：${selected.prompt}`,
    )
    toast.success('已插入文档（含图注）')
  }

  /** 附图说明清单（D3 按钮化）：点击时实时拉取**全项目**图列表生成「图N：描述」
   * 清单块插入编辑器，重复点击替换旧块。图号是项目级连续编号，面板展示的是本章节
   * 过滤集——清单若用本地过滤集，多 drawings 章节模板下会漏其他章节的图且跳号，
   * 故必须以全项目最新数据为准；插入后用户可自由编辑，系统不再自动维护。 */
  async function handleDrawingList() {
    setListing(true)
    try {
      const all = await api.listFigures(projectId)
      const sorted = [...all].sort((a, b) => a.number - b.number)
      if (sorted.length === 0) {
        toast.info('项目中还没有附图')
        return
      }
      onInsertDrawingList(sorted.map((f) => `图${f.number}：${f.prompt}`))
      toast.success(`已生成附图说明清单（共 ${sorted.length} 张图，文末可自由编辑）`)
    } catch {
      toast.error('获取附图列表失败')
    } finally {
      setListing(false)
    }
  }

  async function handleCaption() {
    if (!selected?.attachment_id) return
    // source 为 null 走后端 fallback 链，不前端硬拦（同 ai-chat-panel）
    const source = getChatDefaultSource()
    // 非 vision 模型必须靠文字描述：用户手填优先，否则用生成图时的 prompt 兜底
    const desc = capDesc.trim() || selected.prompt || ''
    setCaptioning(true)
    setCaptionText('')
    try {
      await api.captionFigures(
        sectionId,
        {
          attachment_ids: [selected.attachment_id],
          ...(desc ? { descriptions: [desc] } : {}),
          chat_source: source,
        },
        (t) => setCaptionText((prev) => prev + t),
      )
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? '图注生成失败'
      toast.error(msg)
    } finally {
      setCaptioning(false)
    }
  }

  if (!loaded) return null

  // generating：loading
  if (generating) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-dashed p-3 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        正在生成附图（LLM 生成图结构 + 渲染，约 10-30 秒）...
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border p-2">
      {/* 头部：标题 + 图数 + 新图开关 */}
      <div className="flex items-center gap-1.5 text-sm font-medium">
        <Sparkles className="size-3.5" />
        AI 生成附图
        {figures.length > 0 && (
          <span className="text-xs font-normal text-muted-foreground">共 {figures.length} 张</span>
        )}
        {figures.length > 0 && (
          <Button
            variant="ghost"
            size="xs"
            className="ml-auto h-7 gap-1"
            onClick={() => setFormOpen((v) => !v)}
          >
            {formOpen ? <X className="size-3" /> : <Plus className="size-3" />}
            {formOpen ? '收起' : '再生成一张'}
          </Button>
        )}
      </div>

      {/* 生成表单（无图时常驻；有图时按需展开） */}
      {formOpen && (
        <div className="flex flex-col gap-2">
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
      )}

      {/* 图集缩略条：点选切换当前操作的图 */}
      {figures.length > 0 && (
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {figures.map((f) => (
            <FigureThumb
              key={f.id}
              figure={f}
              projectId={projectId}
              active={f.id === selected?.id}
              onClick={() => selectFigure(f.id)}
              version={imgVersion}
            />
          ))}
        </div>
      )}

      {/* 当前选中图：预览（点击放大）+ 操作 */}
      {selected?.attachment_id && (
        <div className="flex flex-col gap-2">
          {authedImgUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={authedImgUrl}
              alt={selected.prompt}
              onClick={() => setZoom(true)}
              className="max-h-[300px] w-full cursor-zoom-in rounded border object-contain"
            />
          ) : (
            <div className="flex h-[120px] items-center justify-center rounded border bg-muted/30 text-xs text-muted-foreground">
              <Loader2 className="mr-2 size-4 animate-spin" />
              图片加载中...
            </div>
          )}
          <p className="line-clamp-2 text-[11px] text-muted-foreground" title={selected.prompt}>
            图{selected.number} · 描述:{selected.prompt}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" className="h-8 gap-1.5" onClick={handleInsert}>
              <Check className="size-3.5" />
              插入文档
            </Button>
            <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={handleDrawingList} disabled={listing} title="按当前编号在文末生成全项目「图N：描述」清单（重复点击替换旧块）">
              {listing ? <Loader2 className="size-3.5 animate-spin" /> : <ListOrdered className="size-3.5" />}
              附图清单
            </Button>
            <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={handleCaption} disabled={captioning}>
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
          </div>
          <input
            value={capDesc}
            onChange={(e) => setCapDesc(e.target.value)}
            placeholder="图注辅助描述（可选；当前模型不支持看图时与生成 prompt 一同作为依据）"
            className="w-full rounded border bg-background px-2 py-1 text-xs"
          />
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
      )}

      {zoom && authedImgUrl && (
        <ImageLightbox src={authedImgUrl} alt={selected?.prompt ?? ''} onClose={() => setZoom(false)} />
      )}
    </div>
  )
}
