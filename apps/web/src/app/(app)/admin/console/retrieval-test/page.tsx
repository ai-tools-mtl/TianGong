'use client'

import { useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { useRetrievalTest } from '@/lib/queries'

type Result = {
  content: string
  score: number
  section_key: string | null
  project_title: string | null
}

/**
 * /admin/console/retrieval-test — G2 检索测试页。
 *
 * 输入 query 看 RAG 召回，为 G3/G4 调参闭环铺路。
 * scope 可选 全部(global+personal) / 仅全局 / 仅个人；top_k 档位 3/5/10/20。
 * 注：本站 Select 是原生 <select> 封装（见 components/ui/select.tsx），
 * 用 <option> 而非 Radix 的 SelectItem。
 */
export default function RetrievalTestPage() {
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [scope, setScope] = useState<'global' | 'personal' | 'all'>('all')
  const [results, setResults] = useState<Result[]>([])
  const [threshold, setThreshold] = useState<number | null>(null)
  const search = useRetrievalTest()

  function handleSearch() {
    if (!query.trim()) {
      toast.error('请输入检索内容')
      return
    }
    search.mutate(
      { query, top_k: topK, scope: scope === 'all' ? null : scope },
      {
        onSuccess: (data) => {
          setResults(data.results)
          setThreshold(data.threshold)
          toast.success(`召回 ${data.results.length} 条`)
        },
        onError: (err: { message?: string }) =>
          toast.error(err?.message ?? '检索失败'),
      },
    )
  }

  return (
    <PageShell>
      <PageHeader
        title="检索测试"
        description="输入查询语句，验证 RAG 召回质量。用于 G3/G4 调参闭环。"
      />
      <div className="space-y-4 py-6">
        <div className="flex flex-wrap gap-2">
          <Input
            className="min-w-[16rem] flex-1"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="如：权利要求1的技术特征"
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <Select
            className="w-32"
            value={scope}
            onChange={(e) => setScope(e.target.value as 'global' | 'personal' | 'all')}
          >
            <option value="all">全部</option>
            <option value="global">仅全局</option>
            <option value="personal">仅个人</option>
          </Select>
          <Select
            className="w-28"
            value={String(topK)}
            onChange={(e) => setTopK(Number(e.target.value))}
          >
            {[3, 5, 10, 20].map((n) => (
              <option key={n} value={String(n)}>
                top_{n}
              </option>
            ))}
          </Select>
          <Button onClick={handleSearch} disabled={search.isPending}>
            {search.isPending ? '检索中...' : '检索'}
          </Button>
        </div>

        <p className="text-sm text-muted-foreground">
          {threshold !== null ? `当前相似度阈值：${threshold}` : '检索后展示当前相似度阈值'}
        </p>

        {search.isPending && <Skeleton className="h-64" />}

        {!search.isPending && results.length === 0 && (
          <p className="text-sm text-muted-foreground">无召回结果（或未检索）</p>
        )}

        <div className="space-y-3">
          {results.map((r, i) => (
            <div key={i} className="space-y-2 rounded border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">#{i + 1}</Badge>
                <Badge>score: {r.score}</Badge>
                {r.project_title && (
                  <Badge variant="outline">{r.project_title}</Badge>
                )}
                {r.section_key && (
                  <Badge variant="outline">{r.section_key}</Badge>
                )}
              </div>
              <p className="whitespace-pre-wrap text-sm">{r.content}</p>
            </div>
          ))}
        </div>
      </div>
    </PageShell>
  )
}
