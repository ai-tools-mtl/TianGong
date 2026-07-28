'use client'

import { Archive, CheckCircle2, Eye, History, MoreHorizontal, PanelLeft, PanelRight, Search, Send, Share2 } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { AIChatPanel } from '@/components/ai-chat-panel'
import { ResizeHandle } from '@/components/resize-handle'
import { SectionOutline } from '@/components/section-outline'
import { FigureUpload } from '@/components/editor/figure-upload'
import { TiptapEditor } from '@/components/editor/tiptap-editor'
import type { TiptapEditorRef } from '@/components/editor/tiptap-editor'
import { VersionDrawer } from '@/components/version-drawer'
import { ShareDialog } from '@/components/share-dialog'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { api } from '@/lib/api'
import { queryKeys, useArchiveProject, useProject, useSections, useUpdateSection } from '@/lib/queries'
import { cn } from '@/lib/utils'
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
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const editorRef = useRef<TiptapEditorRef>(null)
  // 缓存当前章节最新编辑内容（handleSave 同步写入）。
  // 根因修复（crossover bug）：cleanup/handleConfirm 时不能读 editorRef.current.getJSON()，
  // 因为 React passive-effect cleanup 晚于子组件 remount，此时 editorRef 已指向新章节 editor，
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

  useEffect(() => {
    if (sections && sections.length > 0 && !currentId) {
      setCurrentId(sections[0].id)
    }
  }, [sections, currentId])

  useEffect(() => {
    if (sections && currentId) {
      setCurrent(sections.find((s) => s.id === currentId) || null)
      // 切章节时重置内容缓存——新章节的用户编辑尚未开始，旧残留不能被
      // flushPendingSave 当成本章节内容发出（crossover 修复配套）。
      lastContentRef.current = null
    }
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
    // 同步缓存最新内容到 ref（crossover 修复：cleanup 时 editorRef 已指向新章节，
    // 只能信任 handleSave 捕获的 json，它与 current 同属一次渲染闭包）。
    lastContentRef.current = json
    // 防抖 2s（设计 13.4）
    if (saveTimer.current) clearTimeout(saveTimer.current)
    setSaveState('saving')
    saveTimer.current = setTimeout(() => {
      sendPatch({
        content: json,
        status: current.status === 'empty' ? 'drafting' : current.status,
        expected_version: current.version,
      })
    }, 2000)
  }

  // flush pending 防抖保存：立即取出缓存内容同步发 PATCH，并清掉定时器。
  // 供确认按钮、切章节 cleanup 复用——避免用户输入停留在浏览器未落库。
  // 注意：必须读 lastContentRef.current，不能读 editorRef.current.getJSON()——
  // React passive-effect cleanup 晚于子组件 remount，此时 editorRef 已指向新章节 editor，
  // 读它会把新章节内容回写到旧章节（crossover bug）。
  function flushPendingSave() {
    if (saveTimer.current) {
      clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
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
    // 读 lastContentRef 而非 editorRef（同 flushPendingSave，避免 crossover）。
    // 用户没编辑过（lastContentRef 为 null）时回退到 current.content，避免把内容清空。
    const json = lastContentRef.current ?? current.content
    sendPatch({
      content: json ?? undefined,
      status: 'confirmed',
      expected_version: current.version,
      onSuccess: () => toast.success('章节已确认'),
    })
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
            onSelect={setCurrentId}
            collapsed={leftCollapsed}
          />
        </div>
      </aside>

      {/* 中栏：编辑器 */}
      <section className="flex min-w-0 flex-col overflow-hidden">
        <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b px-4">
          <div className="flex items-center gap-2">
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
        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="h-full">
            {current && current.key === 'drawings' && (
              <div className="mb-3">
                <FigureUpload
                  sectionId={current.id}
                  projectId={projectId}
                  onInsertImage={(src, alt) => editorRef.current?.insertImage(src, alt)}
                />
              </div>
            )}
            {current && (
              <TiptapEditor
                key={current.id}
                ref={editorRef}
                content={current.content}
                onChange={handleSave}
                sectionId={current.id}
              />
            )}
          </div>
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
              <AIChatPanel sectionId={current.id} section={current} projectId={projectId} />
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
    </div>
  )
}
