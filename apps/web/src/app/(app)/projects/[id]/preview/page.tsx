'use client'

import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'

import { TiptapEditor } from '@/components/editor/tiptap-editor'
import { api } from '@/lib/api'
import type { PreviewSection, ProjectPreview } from '@/types/api'

export default function PreviewPage() {
  const params = useParams<{ id: string }>()
  const { data, isLoading } = useQuery<ProjectPreview>({
    queryKey: ['preview', params.id],
    queryFn: () => api.previewProject(params.id),
  })

  if (isLoading) return <p className="text-muted-foreground">加载中...</p>
  if (!data) return null

  const sections: PreviewSection[] = data.sections ?? []

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-bold">{data.title}</h1>
        {data.metadata?.inventors && (
          <p className="text-sm text-muted-foreground">
            发明人：{(data.metadata.inventors as string[]).join('、')}
          </p>
        )}
      </div>
      <hr />
      {sections.map((s) => (
        <div key={s.order} className="space-y-2">
          <h2 className="text-lg font-semibold">{s.title}</h2>
          <div className="border rounded-lg p-4">
            {s.content ? (
              <TiptapEditor content={s.content} editable={false} />
            ) : (
              <p className="text-muted-foreground">（待填写）</p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
