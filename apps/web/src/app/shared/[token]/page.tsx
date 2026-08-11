'use client'

import { useQuery } from '@tanstack/react-query'
import { useParams } from 'next/navigation'

import { TiptapEditor } from '@/components/editor/tiptap-editor'
import { api } from '@/lib/api'
import type { SharedProject, SharedSection } from '@/types/api'

/**
 * 游客浏览页（公开，无需登录）。
 *
 * owner 在 ShareDialog 生成的 /shared/{token} 链接即指向本页。
 * 后端 GET /shared/{token}/sections 返回全篇章节只读视图，附图 src 已
 * 在服务端改写为 base64 data URI，故本页 TiptapEditor 渲染无需任何鉴权。
 * token 不存在/过期/项目不存在 → 后端 404 → 本页展示失效提示。
 */
export default function SharedProjectPage() {
  const params = useParams<{ token: string }>()
  const token = params.token
  const { data, isLoading, isError } = useQuery<SharedProject>({
    queryKey: ['shared-project', token],
    queryFn: () => api.getSharedProject(token),
    retry: false, // 404 不重试（token 失效无意义重试）
  })

  if (isError) {
    return (
      <div className="grid place-items-center py-32 text-center">
        <div className="space-y-2">
          <p className="text-lg font-medium">链接不存在或已失效</p>
          <p className="text-sm text-muted-foreground">
            该分享链接可能已被撤销、已过期，或地址有误。
          </p>
        </div>
      </div>
    )
  }

  if (isLoading || !data) {
    return (
      <div className="grid place-items-center py-20 text-sm text-muted-foreground">
        加载中...
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="space-y-1 border-b pb-6">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold tracking-tight">{data.title}</h1>
          <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            只读
          </span>
        </div>
        <p className="text-xs text-muted-foreground">这是分享的只读视图，无需登录。</p>
      </div>

      <div className="prose max-w-none space-y-8 py-6">
        {data.sections.map((s: SharedSection) => (
          <section key={s.order} className="space-y-2">
            <h2 className="text-lg font-semibold tracking-tight">{s.title}</h2>
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
