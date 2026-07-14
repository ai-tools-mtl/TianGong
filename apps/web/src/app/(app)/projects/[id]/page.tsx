'use client'

import { useParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { TiptapEditor } from '@/components/editor/tiptap-editor'
import { SectionOutline } from '@/components/section-outline'
import { Button } from '@/components/ui/button'
import { useSections, useUpdateSection } from '@/lib/queries'
import type { Section } from '@/types/api'

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>()
  const projectId = params.id
  const { data, isLoading } = useSections(projectId)
  const sections: Section[] = data ?? []
  const updateSection = useUpdateSection()
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [current, setCurrent] = useState<Section | null>(null)

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

  if (isLoading) return <p className="text-muted-foreground">加载中...</p>
  if (!sections || sections.length === 0) {
    return <p className="text-muted-foreground">该项目暂无章节</p>
  }

  function handleSave(json: object) {
    if (!current) return
    updateSection.mutate(
      { id: current.id, content: json, status: current.status === 'empty' ? 'drafting' : current.status },
      { onSuccess: () => {}, onError: () => toast.error('保存失败') },
    )
  }

  function handleConfirm() {
    if (!current) return
    updateSection.mutate(
      { id: current.id, status: 'confirmed' },
      { onSuccess: () => toast.success('章节已确认'), onError: () => toast.error('操作失败') },
    )
  }

  return (
    <div className="grid grid-cols-[220px_1fr] gap-6">
      <aside className="space-y-4">
        <h2 className="text-sm font-semibold text-muted-foreground">章节大纲</h2>
        <SectionOutline sections={sections} currentId={currentId} onSelect={setCurrentId} />
      </aside>

      <div className="space-y-4">
        {current && (
          <>
            <div className="flex items-center justify-between">
              <h1 className="text-lg font-bold">{current.title}</h1>
              <Button onClick={handleConfirm} disabled={updateSection.isPending}>
                确认完成
              </Button>
            </div>
            <TiptapEditor
              key={current.id}
              content={current.content}
              onChange={handleSave}
            />
          </>
        )}
      </div>
    </div>
  )
}
