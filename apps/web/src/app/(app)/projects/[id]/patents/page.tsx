'use client'

import { ArrowLeft, ExternalLink, Scale, Search, Wand2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Markdown } from '@/components/markdown'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { getChatDefaultSource } from '@/lib/llm-source'
import { usePriorArt, useSearchPatents, useSections } from '@/lib/queries'
import { launchRevision } from '@/stores/revision-store'
import type { PatentResult, Section } from '@/types/api'

export default function PatentsPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const [query, setQuery] = useState('')
  // 新颖性评估：流式报告 + 进行中标记
  const [assessment, setAssessment] = useState('')
  const [assessing, setAssessing] = useState(false)
  const assessAbort = useRef<AbortController | null>(null)
  // T2 批4：手动兜底修订（无结构化建议时复制建议文本发起）
  const [manualOpen, setManualOpen] = useState(false)
  const [manualText, setManualText] = useState('')
  const [manualTarget, setManualTarget] = useState('')

  const { data: priorArt } = usePriorArt(params.id)
  const searchMut = useSearchPatents(params.id)
  const { data: sectionsData } = useSections(params.id)
  const sections: Section[] = sectionsData ?? []

  const onSearch = () => {
    if (!query.trim()) {
      toast.error('请输入检索关键词')
      return
    }
    searchMut.mutate(query, {
      onSuccess: (data) => toast.success(`检索到 ${data.results.length} 条专利`),
      onError: () => toast.error('检索失败'),
    })
  }

  const results: PatentResult[] = searchMut.data?.results ?? priorArt?.results ?? []
  const lastQuery = searchMut.data?.query ?? priorArt?.query
  const savedAssessment = priorArt?.assessment?.content ?? ''
  const suggestions = priorArt?.assessment?.suggestions

  // 目标章节前置校验（spec §3.5.5）：不存在或无内容的章节禁用「去修订」
  function sectionUsable(key: string): Section | undefined {
    const s = sections.find((x) => x.key === key)
    return s && s.content ? s : undefined
  }

  function handleRevise(key: string, text: string) {
    const ok = launchRevision(sections, key, [text], 'novelty', router, params.id)
    if (!ok) toast.error('目标章节不存在（可能已被调整）')
  }

  // 手动兜底：仅列出有内容的章节
  const contentSections = sections.filter((s) => s.content)

  async function onAssess() {
    const source = getChatDefaultSource()
    if (!source) {
      toast.error('请先在设置中选择 LLM 源')
      return
    }
    setAssessing(true)
    setAssessment('')
    assessAbort.current = new AbortController()
    try {
      await api.streamAssessNovelty(
        params.id,
        (t) => setAssessment((prev) => prev + t),
        assessAbort.current.signal,
        source,
      )
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 用户停止：保留半截展示
      } else {
        toast.error((err as { message?: string })?.message ?? '评估失败')
      }
    } finally {
      setAssessing(false)
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <Button variant="ghost" size="sm" className="mb-4 gap-1.5 px-2" asChild>
        <Link href={`/projects/${params.id}`}>
          <ArrowLeft className="size-3.5" />
          返回编辑
        </Link>
      </Button>

      <div className="border-b pb-4">
        <h1 className="text-xl font-bold tracking-tight">专利检索</h1>
        <p className="mt-1 text-[13px] text-muted-foreground">
          检索现有技术专利，辅助撰写背景技术与技术方案
        </p>
      </div>

      {/* 搜索框 */}
      <div className="flex gap-2 py-6">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && onSearch()}
          placeholder="输入技术关键词，如「深度学习 图像识别」"
          className="flex-1"
          maxLength={500}
        />
        <Button onClick={onSearch} disabled={searchMut.isPending} className="gap-1.5">
          <Search className="size-3.5" />
          {searchMut.isPending ? '检索中…' : '检索'}
        </Button>
      </div>

      {/* AI 新颖性评估（有检索结果才可用） */}
      {results.length > 0 && (
        <Card className="mb-4">
          <CardContent className="space-y-3 py-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 text-[14px] font-medium">
                <Scale className="size-4" />
                AI 新颖性评估
              </div>
              {assessing ? (
                <Button variant="destructive" size="sm" onClick={() => assessAbort.current?.abort()}>
                  停止
                </Button>
              ) : (
                <Button size="sm" onClick={onAssess}>
                  {savedAssessment || assessment ? '重新评估' : '开始评估'}
                </Button>
              )}
            </div>
            <p className="text-[12px] text-muted-foreground">
              对比检索到的专利与本交底书核心章节，生成逐篇对比分析、总体风险与差异化撰写建议。
              AI 辅助参考，不构成法律意见。
            </p>
            {(assessment || savedAssessment) && (
              <div className="rounded-lg border bg-muted/30 px-3 py-2.5">
                <Markdown className="prose prose-sm max-w-none dark:prose-invert">
                  {assessment || savedAssessment}
                </Markdown>
              </div>
            )}

            {/* T2 批4：结构化建议卡（spec §3.5.5）——逐条「去修订」走统一修订管线 */}
            {!assessing && suggestions && suggestions.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-[12px] font-medium text-muted-foreground">
                  差异化撰写建议（点击逐条修订）
                </p>
                {suggestions.map((s: { section_key: string; text: string }, i: number) => {
                  const target = sectionUsable(s.section_key)
                  const title = sections.find((x) => x.key === s.section_key)?.title ?? s.section_key
                  return (
                    <div
                      key={i}
                      className="flex items-center justify-between gap-2 rounded-lg border border-amber-300/50 bg-amber-50/60 px-3 py-2 dark:border-amber-700/40 dark:bg-amber-950/20"
                    >
                      <span className="min-w-0 flex-1 text-[12px]">
                        <span className="mr-1 font-medium">{title}</span>
                        <span className="text-muted-foreground">{s.text}</span>
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 shrink-0 gap-1 px-2 text-xs"
                        disabled={!target}
                        title={target ? `修订「${title}」章节` : '目标章节不存在或尚无内容'}
                        onClick={() => handleRevise(s.section_key, s.text)}
                      >
                        <Wand2 className="size-3" />
                        去修订
                      </Button>
                    </div>
                  )
                })}
              </div>
            )}

            {/* T2 批4：手动兜底（无结构化建议：旧数据/解析失败） */}
            {!assessing && (assessment || savedAssessment) && (!suggestions || suggestions.length === 0) && (
              <div className="space-y-2">
                <button
                  className="text-[12px] text-muted-foreground underline-offset-2 hover:underline"
                  onClick={() => {
                    setManualOpen((v) => !v)
                    setManualTarget(contentSections[0]?.key ?? '')
                  }}
                >
                  {manualOpen ? '收起手动修订' : '手动复制建议去修订'}
                </button>
                {manualOpen && (
                  <div className="space-y-2 rounded-lg border p-3">
                    <Textarea
                      value={manualText}
                      onChange={(e) => setManualText(e.target.value)}
                      placeholder="粘贴评估报告中的建议要点（如：突出特征X的连接方式…）"
                      className="min-h-[64px] text-[13px]"
                    />
                    <div className="flex items-center gap-2">
                      <select
                        value={manualTarget}
                        onChange={(e) => setManualTarget(e.target.value)}
                        className="h-8 rounded-md border border-input bg-background px-2 text-xs"
                      >
                        {contentSections.map((s) => (
                          <option key={s.key} value={s.key}>{s.title}</option>
                        ))}
                      </select>
                      <Button
                        size="sm"
                        className="h-8 gap-1 text-xs"
                        disabled={!manualText.trim() || !manualTarget}
                        onClick={() => handleRevise(manualTarget, manualText.trim())}
                      >
                        <Wand2 className="size-3" />
                        开始修订
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* 结果列表 */}
      {results.length > 0 ? (
        <div className="space-y-3">
          {lastQuery && (
            <p className="text-[13px] text-muted-foreground">
              关键词「{lastQuery}」· {results.length} 条结果
            </p>
          )}
          {results.map((p, i) => (
            <Card key={i} className="apple-lift">
              <CardContent className="space-y-2 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[14px] font-medium hover:underline"
                    >
                      {p.title}
                    </a>
                    <p className="mt-0.5 text-[12px] text-muted-foreground">
                      {p.applicant} · {p.patent_number} · {p.publication_date}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {p.legal_status && (
                      <Badge
                        variant="outline"
                        className={
                          p.legal_status.includes('失效')
                            ? 'text-muted-foreground'
                            : 'text-success'
                        }
                      >
                        {p.legal_status}
                      </Badge>
                    )}
                    <Badge variant="outline" className="tabular-nums">
                      相关度 {(p.relevance * 100).toFixed(0)}%
                    </Badge>
                  </div>
                </div>
                {p.abstract && (
                  <p className="line-clamp-3 text-[13px] text-muted-foreground">
                    {p.abstract}
                  </p>
                )}
                <a
                  href={p.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
                >
                  <ExternalLink className="size-3" />
                  查看原文
                </a>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        !searchMut.isPending && (
          <div className="grid place-items-center py-20 text-center">
            <p className="text-sm text-muted-foreground">
              尚未检索。输入关键词开始查找相关专利
            </p>
          </div>
        )
      )}
    </div>
  )
}
