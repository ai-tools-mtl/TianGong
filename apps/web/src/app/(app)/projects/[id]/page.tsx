'use client'

import { Archive, BookA, CheckCircle2, Eye, History, MoreHorizontal, PanelLeft, PanelRight, PanelTop, Rows3, ScanSearch, Search, Send, Share2, Wand2, X } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { AIChatPanel } from '@/components/ai-chat-panel'
import type { AIChatPanelRef } from '@/components/ai-chat-panel'
import { ResizeHandle } from '@/components/resize-handle'
import { SectionOutline } from '@/components/section-outline'
import { SectionBlock } from '@/components/section-block'
import { FigureGenerate } from '@/components/editor/figure-generate'
import { FigureUpload } from '@/components/editor/figure-upload'
import { TiptapEditor } from '@/components/editor/tiptap-editor'
import type { TiptapEditorRef } from '@/components/editor/tiptap-editor'
import { VersionDrawer } from '@/components/version-drawer'
import { ShareDialog } from '@/components/share-dialog'
import { TermsPanel } from '@/components/terms-panel'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api } from '@/lib/api'
import { queryKeys, useArchiveProject, useProject, useSections, useUpdateSection } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useRevisionStore } from '@/stores/revision-store'
import { useUIStore } from '@/stores/ui'
import type { Section } from '@/types/api'

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>()
  const projectId = params.id
  const { data, isLoading } = useSections(projectId)
  const sections: Section[] = data ?? []
  const updateSection = useUpdateSection()
  const { data: project } = useProject(projectId)
  const archiveMutation = useArchiveProject()
  const submitDisclosure = useMutation({
    mutationFn: () => api.submitDisclosureReview(projectId),
    onSuccess: () => toast.success('已上报,等待管理员审核进入全局库'),
    onError: (err: { message?: string }) => toast.error(err?.message ?? '上报失败'),
  })
  const qc = useQueryClient()
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [current, setCurrent] = useState<Section | null>(null)
  const [versionOpen, setVersionOpen] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [termsOpen, setTermsOpen] = useState(false)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 每章编辑器实例引用表（spec §3.7）：连续模式下多个编辑器同挂，单例 ref 会指向
  // 最后挂载的实例，导致 apply-diff 重置 / 图章插入作用错章节。
  const editorRefs = useRef<Record<string, TiptapEditorRef | null>>({})
  // 每章内容缓存（spec §3.5）：handleSave 同步写入；编辑器挂载 content 一律读缓存，
  // 避免快速回切章节时查询 refetch 未落地导致最后输入显示回退。
  const contentCacheRef = useRef<Map<string, object>>(new Map())
  // 连续模式章节块根节点引用表：点击激活后 scrollIntoView 用。
  const blockRootRefs = useRef<Record<string, HTMLDivElement | null>>({})
  // 滚动容器引用（IntersectionObserver 的 root，spec §3.8）。
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // 连续模式滚动跟随：候选章防抖定时器 + 各章在观察带内的可见性 + 激活章 id 镜像。
  // 全部走 ref：observer 回调/定时器跨渲染存活，读 state 闭包会过期。
  const followTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const visibleMapRef = useRef<Record<string, boolean>>({})
  const currentIdRef = useRef<string | null>(null)
  const sectionsRef = useRef<Section[]>([])
  // 编辑锁的 dirty 标记（spec §3.2）：防抖窗口内有未 flush 输入时为 true。
  const dirtyRef = useRef(false)
  // 待滚动定位标记：点击/深链切换激活章后，由 currentId 变化 effect 统一滚动（挂载后执行）。
  const pendingScrollRef = useRef(false)
  // AIChatPanel 的 imperative ref：选区重写气泡（在下方 <TiptapEditor> 内）触发
  // onRewriteComplete 时，通过此 ref 桥接到 AIChatPanel.handleRewriteComplete，
  // 复用 AIChatPanel 已有的 phase/hunks/DiffReviewPanel diff 审核流程。
  const aiChatRef = useRef<AIChatPanelRef>(null)
  // 缓存当前章节最新编辑内容（handleSave 同步写入）。
  // 根因修复（crossover bug）：cleanup/handleConfirm 时不能读 editorRefs 里该章实例的 getJSON()，
  // 因为 React passive-effect cleanup 晚于子组件 remount，此时引用表里可能已是新章节 editor，
  // 会把新章节内容当成旧章节内容 PATCH，导致章节内容串台。
  // lastContentRef 与 current 来自同一次渲染闭包，章节 id 与内容始终配对。
  const lastContentRef = useRef<object | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle')

  const leftCollapsed = useUIStore((s) => s.leftCollapsed)
  const rightCollapsed = useUIStore((s) => s.rightCollapsed)
  const rightWidth = useUIStore((s) => s.rightWidth)
  const setRightWidth = useUIStore((s) => s.setRightWidth)
  const toggleLeft = useUIStore((s) => s.toggleLeft)
  const toggleRight = useUIStore((s) => s.toggleRight)
  const editorMode = useUIStore((s) => s.editorMode)
  const setEditorMode = useUIStore((s) => s.setEditorMode)

  useEffect(() => {
    if (sections && sections.length > 0 && !currentId) {
      setCurrentId(sections[0].id)
    }
  }, [sections, currentId])

  // ?section={key} 深链定位（T2 spec §3.5.1）：报告页/新颖性页/术语面板发起修订
  // （launchRevision）后跳转至此。挂载时读一次并切到目标章节，随后清参防刷新重复跳转。
  // 用 window.location.search 而非 useSearchParams：'use client' 页面直接用后者
  // 需要 Suspense 边界（Next 15 构建要求），此处只读一次，无需响应式。
  useEffect(() => {
    const key = new URLSearchParams(window.location.search).get('section')
    if (!key || !sections?.length) return
    const target = sections.find((s) => s.key === key)
    if (target) {
      pendingScrollRef.current = true
      setCurrentId(target.id)
      window.history.replaceState(null, '', `/projects/${projectId}`)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sections?.length])

  // 激活章变化后的滚动定位（spec §3.6）：点击章头/大纲、?section= 深链、revision 前往
  // 统一走 pendingScrollRef 标记，在目标章挂载后的本 effect 中滚动（首帧未挂载时
  // scrollIntoView 无效）。滚动跟随触发的激活不置标记、不滚动。
  useEffect(() => {
    if (!pendingScrollRef.current || !currentId) return
    pendingScrollRef.current = false
    blockRootRefs.current[currentId]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [currentId, sections?.length, editorMode])

  // 滞留修订任务提示条（T2 spec §3.5.1）：store 有 pending 但当前章节不匹配时，
  // 顶部轻提示引导切换（用户可能刷新/绕路，任务单值滞留需可见）。
  const pendingRevision = useRevisionStore((s) => s.pending)
  const clearRevision = useRevisionStore((s) => s.clear)
  const pendingTarget = pendingRevision
    ? sections.find((s) => s.key === pendingRevision.sectionKey)
    : undefined
  const showPendingBar = Boolean(
    pendingRevision && current && pendingTarget && pendingTarget.id !== current.id,
  )

  useEffect(() => {
    if (sections && currentId) {
      setCurrent(sections.find((s) => s.id === currentId) || null)
      // 切章节时重置内容缓存——新章节的用户编辑尚未开始，旧残留不能被
      // flushPendingSave 当成本章节内容发出（crossover 修复配套）。
      lastContentRef.current = null
    }
    // ref 镜像同步（滚动跟随 observer 回调/定时器内读，闭包会过期）
    currentIdRef.current = currentId
    sectionsRef.current = sections ?? []
  }, [sections, currentId])

  // 切换章节前 flush 防抖中的保存（根因修复：旧实现只 clearTimeout 不发请求，
  // 导致用户在 2s 防抖窗口内切章节会丢失未落库的输入）。
  // 注意：flushPendingSave 读 current 闭包，cleanup 在 currentId 变化时执行，
  // 此时闭包里的 current 仍是旧章节（即将离开的那个），正是要保存的对象。
  useEffect(() => {
    return () => {
      flushPendingSave()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId])

  // 连续模式滚动停稳跟随（spec §3.8）：IntersectionObserver 观察各章块与滚动容器
  // 顶部 40% 观察带（rootMargin 下收 60%）的交集，取可见章为候选，500ms 防抖后切换。
  // 两把锁（spec §3.2）在定时器触发时判定：
  // - 编辑锁：激活章仍在观察带内 且（防抖窗口有未 flush 输入 或 焦点在编辑器内）
  // - AI 忙碌锁：AI 面板相位非 idle（含 done/diff-review，防待审草稿被静默丢弃）
  // 锁生效则不切换；显式点击（handleActivate）不受锁约束。
  useEffect(() => {
    if (editorMode !== 'continuous' || !sections?.length) return
    const root = scrollRef.current
    if (!root) return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const sid = (e.target as HTMLElement).dataset.sectionId
          if (sid) visibleMapRef.current[sid] = e.isIntersecting
        }
        const candidate = sectionsRef.current.find((s) => visibleMapRef.current[s.id])
        if (!candidate || candidate.id === currentIdRef.current) return
        if (followTimerRef.current) clearTimeout(followTimerRef.current)
        followTimerRef.current = setTimeout(() => {
          if (candidate.id === currentIdRef.current) return
          const activeVisible = visibleMapRef.current[currentIdRef.current ?? '']
          const focusedInEditor = Boolean(document.activeElement?.closest('.tiptap'))
          if (activeVisible && (dirtyRef.current || focusedInEditor)) return
          if ((aiChatRef.current?.getPhase() ?? 'idle') !== 'idle') return
          setCurrentId(candidate.id)
        }, 500)
      },
      { root, rootMargin: '0px 0px -60% 0px', threshold: 0 },
    )
    for (const sid of Object.keys(blockRootRefs.current)) {
      const el = blockRootRefs.current[sid]
      if (el) observer.observe(el)
    }
    return () => {
      observer.disconnect()
      if (followTimerRef.current) clearTimeout(followTimerRef.current)
    }
  }, [editorMode, sections?.length])

  if (isLoading) {
    return (
      <div className="grid place-items-center py-20 text-sm text-muted-foreground">
        加载中...
      </div>
    )
  }
  if (!sections || sections.length === 0) {
    return (
      <div className="grid place-items-center py-20 text-sm text-muted-foreground">
        该项目暂无章节
      </div>
    )
  }

  // 实际发送 PATCH 保存的逻辑（防抖/确认/切章节 flush 共用）。
  // content/status/expected_version 均可选；confirm 时三参同发以原子完成"保存+确认"，
  // 避免与 pending 防抖保存竞态撞 409（根因：旧 handleConfirm 不取消定时器、不带 version）。
  function sendPatch(payload: {
    content?: object
    status?: string
    expected_version?: number
    onSuccess?: () => void
    onError?: (err: { code?: string; message?: string }) => void
  }) {
    if (!current) return
    updateSection.mutate(
      {
        id: current.id,
        content: payload.content,
        status: payload.status,
        expected_version: payload.expected_version,
      },
      {
        onSuccess: () => {
          setSaveState('saved')
          payload.onSuccess?.()
        },
        onError: (err: { code?: string; message?: string }) => {
          if (err?.code === 'conflict') {
            toast.error('内容已被其他端修改，已刷新为最新版本')
            qc.invalidateQueries({ queryKey: queryKeys.sections(projectId) })
          } else if (payload.status === 'confirmed') {
            toast.error('确认失败')
          } else {
            toast.error('保存失败')
          }
          setSaveState('idle')
          payload.onError?.(err)
        },
      },
    )
  }

  function handleSave(json: object) {
    if (!current) return
    // 同步缓存最新内容到 ref（crossover 修复：cleanup 时 editorRefs 已指向新章节实例，
    // 只能信任 handleSave 捕获的 json，它与 current 同属一次渲染闭包）。
    lastContentRef.current = json
    contentCacheRef.current.set(current.id, json)
    // 编辑锁 dirty 标记：防抖窗口内有未 flush 输入（spec §3.2）
    dirtyRef.current = true
    // 防抖 2s（设计 13.4）
    if (saveTimer.current) clearTimeout(saveTimer.current)
    setSaveState('saving')
    saveTimer.current = setTimeout(() => {
      sendPatch({
        content: json,
        status: current.status === 'empty' ? 'drafting' : current.status,
        expected_version: current.version,
      })
      // 防抖窗口清空：解除编辑锁的 dirty 部分（焦点判定仍由 observer 侧读 activeElement）
      dirtyRef.current = false
    }, 2000)
  }

  // flush pending 防抖保存：立即取出缓存内容同步发 PATCH，并清掉定时器。
  // 供确认按钮、切章节 cleanup 复用——避免用户输入停留在浏览器未落库。
  // 注意：必须读 lastContentRef.current，不能读 editorRefs 里实例的 getJSON()——
  // React passive-effect cleanup 晚于子组件 remount，此时引用表里可能是新章节 editor，
  // 读它会把新章节内容回写到旧章节（crossover bug）。
  function flushPendingSave() {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    dirtyRef.current = false
    if (!current) return
    const json = lastContentRef.current
    if (!json) return
    sendPatch({
      content: json,
      status: current.status === 'empty' ? 'drafting' : current.status,
      expected_version: current.version,
    })
  }

  function handleConfirm() {
    if (!current) return
    // 根因修复：先取消 pending 防抖保存，再把"最新内容 + 确认状态"一次性 PATCH 发出。
    // 旧实现只发 {status:'confirmed'} 且不取消定时器，导致 2s 后的防抖保存带旧
    // expected_version 撞已被自增的 version → 409，且那次被拒的正是用户最后输入 → 内容丢失。
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    dirtyRef.current = false
    // 读 lastContentRef 而非 editorRefs（同 flushPendingSave，避免 crossover）。
    // 用户没编辑过（lastContentRef 为 null）时回退内容缓存（快速回切时查询缓存
    // 可能未刷新）再回退 current.content，避免把最新内容清空。
    const json = lastContentRef.current ?? contentCacheRef.current.get(current.id) ?? current.content
    sendPatch({
      content: json ?? undefined,
      status: 'confirmed',
      expected_version: current.version,
      onSuccess: () => toast.success('章节已确认'),
    })
  }

  // 模式切换（单章⇄全文）：先 flush 防抖保存再切——编辑器树整体重挂载前落库（spec §3.2）。
  function handleToggleMode() {
    flushPendingSave()
    setEditorMode(editorMode === 'single' ? 'continuous' : 'single')
  }

  // 激活章切换入口（连续模式章头/大纲点击）：显式点击不受两把锁约束（spec §3.2）。
  // 滚动定位经 pendingScrollRef 标记 + currentId 变化 effect 统一执行（挂载后滚动）。
  // 滚动跟随触发的激活（IntersectionObserver 路径）不走此函数，不置标记、不滚动。
  function handleActivate(id: string) {
    if (id === currentId) return
    pendingScrollRef.current = true
    setCurrentId(id)
  }

  // apply-diff 成功后（AIChatPanel 回调）：重置激活章编辑器 + 同步 ref 兜底缓存，
  // 保证缓存与后端一致（spec §3.5）。
  function handleAppliedContent(content: object) {
    if (current) {
      lastContentRef.current = content
      contentCacheRef.current.set(current.id, content)
      editorRefs.current[current.id]?.resetContent(content)
    }
  }

  function handleArchive() {
    archiveMutation.mutate(projectId, {
      onSuccess: (res) => {
        if (project?.status === 'archived') {
          toast.success('知识库已更新')
        } else {
          toast.success(`已归档，写入 ${res.chunks} 个知识块`)
        }
      },
      onError: (err: { code?: string; message?: string }) =>
        toast.error(err?.message || '归档失败'),
    })
  }

  // 选区重写气泡（SelectionBubbleMenu，挂在下方 <TiptapEditor> 内）流式完成后回调：
  // 桥接到 AIChatPanel.handleRewriteComplete，由它复用已有 diff 审核流程
  // （setHunks + setPhase('diff-review') → DiffReviewPanel 接管，handleApplyDiff 落地）。
  // spec §3.3：气泡不碰 diff 逻辑，只是给 diff 审核提供"选区重写"这条新数据源。
  function handleRewriteComplete(aiOutput: string, selectedText: string) {
    aiChatRef.current?.handleRewriteComplete(aiOutput, selectedText)
  }

  // 三栏宽度按折叠态切换：左栏 240 / 收起 56；右栏 rightWidth / 收起 0
  const leftCol = leftCollapsed ? '56px' : '240px'
  const rightCol = rightCollapsed ? '0px' : `${rightWidth}px`

  return (
    <div
      className="grid h-[calc(100vh-3.5rem)] overflow-hidden"
      style={{ gridTemplateColumns: `${leftCol} 1fr ${rightCol}`, gridTemplateRows: 'minmax(0, 1fr)' }}
    >
      {/* 左栏：章节大纲 */}
      <aside
        className={cn(
          'flex flex-col border-r bg-background overflow-hidden',
          leftCollapsed ? 'items-center' : '',
        )}
      >
        <div className="flex h-10 items-center justify-between border-b px-2">
          {!leftCollapsed && (
            <span className="px-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              章节大纲
            </span>
          )}
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={toggleLeft}
            aria-label={leftCollapsed ? '展开大纲' : '收起大纲'}
            title={leftCollapsed ? '展开大纲' : '收起大纲'}
            className={leftCollapsed ? 'mx-auto' : ''}
          >
            <PanelLeft className="size-3.5" />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto px-2 py-2">
          <SectionOutline
            sections={sections}
            currentId={currentId}
            onSelect={handleActivate}
            collapsed={leftCollapsed}
          />
        </div>
      </aside>

      {/* 中栏：编辑器 */}
      <section className="flex min-w-0 flex-col overflow-hidden">
        <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b px-4">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={handleToggleMode}
              title={editorMode === 'single' ? '切换为全文视图' : '切换为单章视图'}
              aria-label={editorMode === 'single' ? '切换为全文视图' : '切换为单章视图'}
            >
              {editorMode === 'single' ? (
                <Rows3 className="size-4" />
              ) : (
                <PanelTop className="size-4" />
              )}
            </Button>
            <h1 className="truncate text-[15px] font-semibold tracking-tight">
              {current?.title ?? '未选择章节'}
            </h1>
            {saveState === 'saving' && (
              <span className="text-[11px] text-muted-foreground">保存中…</span>
            )}
            {saveState === 'saved' && (
              <span className="text-[11px] text-muted-foreground">已保存</span>
            )}
          </div>
          {current && (
            <div className="flex shrink-0 items-center gap-1">
              <Button variant="ghost" size="sm" className="h-8 gap-1.5" asChild>
                <a href={`/projects/${projectId}/preview`}>
                  <Eye className="size-3.5" />
                  预览
                </a>
              </Button>
              <Button variant="ghost" size="sm" className="h-8 gap-1.5" asChild>
                <a href={`/projects/${projectId}/review`}>
                  <Search className="size-3.5" />
                  审查
                </a>
              </Button>
              <Button variant="ghost" size="sm" className="h-8 gap-1.5" asChild>
                <a href={`/projects/${projectId}/patents`}>
                  <ScanSearch className="size-3.5" />
                  检索
                </a>
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5"
                onClick={() => setTermsOpen(true)}
              >
                <BookA className="size-3.5" />
                术语
              </Button>
              <Button
                size="sm"
                className="h-8 gap-1.5"
                onClick={handleConfirm}
                disabled={updateSection.isPending}
              >
                <CheckCircle2 className="size-3.5" />
                确认完成
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" className="h-8 gap-1.5">
                    <MoreHorizontal className="size-3.5" />
                    更多
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => setShareOpen(true)}>
                    <Share2 className="size-3.5" />
                    分享
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <a
                      href={api.exportDocxUrl(projectId)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      导出 Word
                    </a>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <a
                      href={api.exportPdfUrl(projectId)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      导出 PDF
                    </a>
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setVersionOpen(true)}>
                    <History className="size-3.5" />
                    版本
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={handleArchive}
                    disabled={archiveMutation.isPending}
                  >
                    <Archive className="size-3.5" />
                    {project?.status === 'archived' ? '更新知识库' : '归档到知识库'}
                  </DropdownMenuItem>
                  {project?.status === 'archived' && (
                    <DropdownMenuItem
                      onClick={() => submitDisclosure.mutate()}
                      disabled={submitDisclosure.isPending}
                    >
                      <Send className="size-3.5" />
                      {submitDisclosure.isPending ? '上报中...' : '上报到全局库'}
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
              {rightCollapsed && (
                <>
                  <span className="mx-1 h-4 w-px bg-border" />
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1.5"
                    onClick={toggleRight}
                  >
                    <PanelRight className="size-3.5" />
                    AI
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
        {showPendingBar && pendingTarget && (
          <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-amber-50 px-4 py-1.5 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            <span className="flex items-center gap-1.5">
              <Wand2 className="size-3.5" />
              有待执行的 AI 修订任务（{pendingTarget.title}）
            </span>
            <span className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-xs"
                onClick={() => handleActivate(pendingTarget.id)}
              >
                前往
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="丢弃修订任务"
                onClick={clearRevision}
              >
                <X className="size-3.5" />
              </Button>
            </span>
          </div>
        )}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4">
          {editorMode === 'single' ? (
            <div className="h-full">
              {current && current.key === 'drawings' && (
                <div className="mb-3 space-y-2">
                  <FigureUpload
                    sectionId={current.id}
                    projectId={projectId}
                    onInsertImage={(src, alt) =>
                      editorRefs.current[current.id]?.insertImage(src, alt)
                    }
                  />
                  <FigureGenerate
                    sectionId={current.id}
                    projectId={projectId}
                    onInsertImage={(src, alt) =>
                      editorRefs.current[current.id]?.insertImage(src, alt)
                    }
                  />
                </div>
              )}
              {current && (
                <TiptapEditor
                  key={current.id}
                  ref={(r) => {
                    editorRefs.current[current.id] = r
                  }}
                  content={contentCacheRef.current.get(current.id) ?? current.content}
                  onChange={handleSave}
                  sectionId={current.id}
                  onRewriteComplete={handleRewriteComplete}
                />
              )}
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-6 pb-16">
              {sections.map((s, i) => (
                <SectionBlock
                  key={s.id}
                  section={s}
                  index={i}
                  isActive={s.id === currentId}
                  initialContent={contentCacheRef.current.get(s.id) ?? s.content}
                  onActivate={handleActivate}
                  editorRef={(r) => {
                    editorRefs.current[s.id] = r
                  }}
                  rootRef={(el) => {
                    blockRootRefs.current[s.id] = el
                  }}
                  figureSlot={
                    s.key === 'drawings' ? (
                      <>
                        <FigureUpload
                          sectionId={s.id}
                          projectId={projectId}
                          onInsertImage={(src, alt) =>
                            editorRefs.current[s.id]?.insertImage(src, alt)
                          }
                        />
                        <FigureGenerate
                          sectionId={s.id}
                          projectId={projectId}
                          onInsertImage={(src, alt) =>
                            editorRefs.current[s.id]?.insertImage(src, alt)
                          }
                        />
                      </>
                    ) : undefined
                  }
                  onChange={handleSave}
                  onRewriteComplete={handleRewriteComplete}
                />
              ))}
            </div>
          )}
        </div>
      </section>

      {/* 拖拽分隔条 + 右栏：AI 对话（作为一个 grid 子元素） */}
      {current && !rightCollapsed && (
        <div className="flex min-w-0">
          <ResizeHandle
            side="left"
            onResize={(delta) => setRightWidth(rightWidth + delta)}
          />
          {/* flex-1 必需：让 aside 撑满 grid item（列宽随 rightWidth 变化），
              否则宽度会被内容自然宽度钉死、拖拽无效 */}
          <aside className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
            <div className="flex min-h-0 flex-1 overflow-hidden">
              <AIChatPanel
                ref={aiChatRef}
                sectionId={current.id}
                section={current}
                projectId={projectId}
                onAppliedContent={handleAppliedContent}
              />
            </div>
          </aside>
        </div>
      )}

      {current && (
        <VersionDrawer
          sectionId={current.id}
          open={versionOpen}
          onOpenChange={setVersionOpen}
        />
      )}

      <ShareDialog
        projectId={projectId}
        open={shareOpen}
        onOpenChange={setShareOpen}
      />

      {current && (
        <TermsPanel
          projectId={projectId}
          sections={sections}
          open={termsOpen}
          onOpenChange={setTermsOpen}
        />
      )}
    </div>
  )
}
