'use client'

import { CheckCircle2, Eye, History, PanelLeft, PanelRight, Search } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { AIChatPanel } from '@/components/ai-chat-panel'
import { SectionOutline } from '@/components/section-outline'
import { TiptapEditor } from '@/components/editor/tiptap-editor'
import { VersionDrawer } from '@/components/version-drawer'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useSections, useUpdateSection } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/ui'
import type { Section } from '@/types/api'

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>()
  const projectId = params.id
  const { data, isLoading } = useSections(projectId)
  const sections: Section[] = data ?? []
  const updateSection = useUpdateSection()
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [current, setCurrent] = useState<Section | null>(null)
  const [versionOpen, setVersionOpen] = useState(false)

  const leftCollapsed = useUIStore((s) => s.leftCollapsed)
  const rightCollapsed = useUIStore((s) => s.rightCollapsed)
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
    }
  }, [sections, currentId])

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

  function handleSave(json: object) {
    if (!current) return
    updateSection.mutate(
      {
        id: current.id,
        content: json,
        status: current.status === 'empty' ? 'drafting' : current.status,
      },
      { onError: () => toast.error('保存失败') },
    )
  }

  function handleConfirm() {
    if (!current) return
    updateSection.mutate(
      { id: current.id, status: 'confirmed' },
      {
        onSuccess: () => toast.success('章节已确认'),
        onError: () => toast.error('操作失败'),
      },
    )
  }

  // 三栏宽度按折叠态切换：左栏 240 / 收起 56；右栏 360 / 收起 0
  const leftCol = leftCollapsed ? '56px' : '240px'
  const rightCol = rightCollapsed ? '0px' : '360px'

  return (
    <div
      className="grid h-[calc(100vh-3.5rem)] overflow-hidden"
      style={{ gridTemplateColumns: `${leftCol} 1fr ${rightCol}` }}
    >
      {/* 左栏：章节大纲 */}
      <aside
        className={cn(
          'flex flex-col border-r bg-background overflow-hidden',
          leftCollapsed ? 'items-center' : '',
        )}
      >
        <div className="flex h-9 items-center justify-between border-b px-2">
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
        <div className="flex h-12 shrink-0 items-center justify-between gap-2 border-b px-4">
          <h1 className="truncate text-[15px] font-semibold">
            {current?.title ?? '未选择章节'}
          </h1>
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
                <a
                  href={api.exportDocxUrl(projectId)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  导出 Word
                </a>
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5"
                onClick={() => setVersionOpen(true)}
              >
                <History className="size-3.5" />
                版本
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
            </div>
          )}
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="mx-auto max-w-3xl">
            {current && (
              <TiptapEditor
                key={current.id}
                content={current.content}
                onChange={handleSave}
              />
            )}
          </div>
        </div>
      </section>

      {/* 右栏：AI 对话（面板自带标题栏 + 折叠按钮） */}
      {current && !rightCollapsed && (
        <aside className="flex min-w-0 flex-col border-l bg-background">
          <div className="flex-1 overflow-hidden">
            <AIChatPanel sectionId={current.id} projectId={projectId} />
          </div>
        </aside>
      )}

      {/* 右栏折叠时：浮动展开按钮 */}
      {current && rightCollapsed && (
        <Button
          variant="outline"
          size="sm"
          onClick={toggleRight}
          className="fixed right-4 top-16 z-30 h-8 gap-1.5 shadow-sm"
        >
          <PanelRight className="size-3.5" />
          AI
        </Button>
      )}

      {current && (
        <VersionDrawer
          sectionId={current.id}
          open={versionOpen}
          onClose={() => setVersionOpen(false)}
        />
      )}
    </div>
  )
}
