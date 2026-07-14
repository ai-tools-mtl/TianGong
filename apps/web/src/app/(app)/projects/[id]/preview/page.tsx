'use client'

import { ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'

import { TiptapEditor } from '@/components/editor/tiptap-editor'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { PreviewSection, ProjectPreview } from '@/types/api'

export default function PreviewPage() {
  const params = useParams<{ id: string }>()
  const { data, isLoading } = useQuery<ProjectPreview>({
    queryKey: ['preview', params.id],
    queryFn: () => api.previewProject(params.id),
  })

  if (isLoading) {
    return (
      <div className="grid place-items-center py-20 text-sm text-muted-foreground">
        加载中...
      </div>
    )
  }
  if (!data) return null

  const sections: PreviewSection[] = data.sections ?? []

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <Button variant="ghost" size="sm" className="mb-4 gap-1.5 px-2" asChild>
        <Link href={`/projects/${params.id}`}>
          <ArrowLeft className="size-3.5" />
          返回编辑
        </Link>
      </Button>

      <div className="space-y-1 border-b pb-6">
        <h1 className="prose-headings:text-2xl text-2xl font-bold">{data.title}</h1>
        {data.metadata?.inventors && (
          <p className="text-sm text-muted-foreground">
            发明人：{(data.metadata.inventors as string[]).join('、')}
          </p>
        )}
      </div>

      <div className="prose max-w-none space-y-8 py-6">
        {sections.map((s) => (
          <section key={s.order} className="space-y-2">
            <h2 className="text-lg font-semibold">{s.title}</h2>
            {s.content ? (
              <TiptapEditor content={s.content} editable={false} />
            ) : (
              <p className="text-sm text-muted-foreground">（待填写）</p>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
