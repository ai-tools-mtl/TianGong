'use client'

/**
 * 项目术语表面板（T2 spec §3.5.4）：编辑器顶栏「术语」按钮打开的全屏 Dialog。
 *
 * 三区块：
 * ① 术语列表：CRUD + enabled Switch（停用不注入不检查）
 * ② AI 抽取：从已写章节抽候选（不入库，勾选后入库 source='ai'）
 * ③ 一致性检查：规则路误用提示（子串匹配可能含复合词误报，可选 LLM 复核）+
 *    LLM 表外漂移建议（一键加入术语表）；rule_issue「去修订」走统一修订管线。
 */
import { BookA, Loader2, Plus, RefreshCw, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { api } from '@/lib/api'
import {
  useCreateTerm,
  useDeleteTerm,
  useTerms,
  useUpdateTerm,
} from '@/lib/queries'
import { launchRevision } from '@/stores/revision-store'
import type {
  CheckResult,
  ExtractResult,
  Section,
  TermEntry,
} from '@/types/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'

interface TermsPanelProps {
  projectId: string
  sections: Section[]
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function TermsPanel({ projectId, sections, open, onOpenChange }: TermsPanelProps) {
  const router = useRouter()
  const { data: terms = [], isLoading } = useTerms(projectId)
  const createTerm = useCreateTerm(projectId)
  const updateTerm = useUpdateTerm(projectId)
  const deleteTerm = useDeleteTerm(projectId)

  // 添加表单
  const [newTerm, setNewTerm] = useState('')
  const [newVariants, setNewVariants] = useState('')

  // AI 抽取
  const [extracting, setExtracting] = useState(false)
  const [extractResult, setExtractResult] = useState<ExtractResult | null>(null)
  const [selectedCandidates, setSelectedCandidates] = useState<Record<number, boolean>>({})

  // 一致性检查
  const [checking, setChecking] = useState(false)
  const [llmVerify, setLlmVerify] = useState(false)
  const [checkResult, setCheckResult] = useState<CheckResult | null>(null)

  const keyTitleMap = new Map(sections.map((s) => [s.key, s.title]))

  function handleAdd() {
    const term = newTerm.trim()
    if (!term) return
    const variants = newVariants.split(/[、,，\s]+/).filter(Boolean)
    createTerm.mutate(
      { term, variants },
      {
        onSuccess: () => {
          setNewTerm('')
          setNewVariants('')
        },
        onError: (err: { message?: string }) => toast.error(err?.message || '添加失败'),
      },
    )
  }

  async function handleExtract() {
    setExtracting(true)
    setExtractResult(null)
    setSelectedCandidates({})
    try {
      const res = await api.extractTerms(projectId)
      setExtractResult(res)
      if (res.warning) toast.info(res.warning)
      if (!res.candidates.length && !res.warning) toast.info('未发现可统一的术语候选')
    } catch (err) {
      toast.error((err as { message?: string })?.message || '抽取失败')
    } finally {
      setExtracting(false)
    }
  }

  async function handleImportSelected() {
    const picked = (extractResult?.candidates ?? []).filter((_, i) => selectedCandidates[i])
    if (!picked.length) {
      toast.error('请先勾选候选术语')
      return
    }
    let ok = 0
    for (const c of picked) {
      try {
        await api.createTerm(projectId, {
          term: c.term, definition: c.definition, variants: c.variants, source: 'ai',
        })
        ok += 1
      } catch {
        // 单条失败（如重复）不阻断后续
      }
    }
    toast.success(`已入库 ${ok} 条`)
    setExtractResult(null)
    setSelectedCandidates({})
  }

  async function handleCheck() {
    setChecking(true)
    setCheckResult(null)
    try {
      const res = await api.checkTerms(projectId, llmVerify)
      setCheckResult(res)
      if (res.warning) toast.info(res.warning)
    } catch (err) {
      toast.error((err as { message?: string })?.message || '检查失败')
    } finally {
      setChecking(false)
    }
  }

  function handleReviseVariant(term: string, variant: string, sectionKeys: string[]) {
    const target = sectionKeys[0]
    if (!target || !keyTitleMap.has(target)) {
      toast.error('无法定位涉及章节')
      return
    }
    const ok = launchRevision(
      sections, target,
      [`将本章节中的「${variant}」统一替换为标准术语「${term}」，并保证语句通顺`],
      'terms', router, projectId,
    )
    if (ok) onOpenChange(false)
  }

  function handleAddDrift(concept: string, variants: string[]) {
    createTerm.mutate(
      { term: concept, variants },
      { onSuccess: () => toast.success(`已加入「${concept}」`) },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-1.5">
            <BookA className="size-4" />
            项目术语表
          </DialogTitle>
          <DialogDescription>
            标准术语与禁用变体将注入 AI 写作与修订上下文（写作必须使用标准术语）。
          </DialogDescription>
        </DialogHeader>

        {/* ① 添加 + 列表 */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Input
              value={newTerm}
              onChange={(e) => setNewTerm(e.target.value)}
              placeholder="标准术语（如：处理模块）"
              className="h-8 flex-1"
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            />
            <Input
              value={newVariants}
              onChange={(e) => setNewVariants(e.target.value)}
              placeholder="禁用变体（顿号分隔，可空）"
              className="h-8 flex-1"
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            />
            <Button size="sm" className="h-8 gap-1" onClick={handleAdd} disabled={createTerm.isPending}>
              <Plus className="size-3.5" />
              添加
            </Button>
          </div>

          {isLoading ? (
            <p className="py-4 text-center text-sm text-muted-foreground">加载中...</p>
          ) : terms.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              暂无术语。可手动添加，或用 AI 从已写章节抽取候选。
            </p>
          ) : (
            <ul className="space-y-1.5">
              {terms.map((t: TermEntry) => (
                <li
                  key={t.id}
                  className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    <span className="text-[13px] font-medium">{t.term}</span>
                    {t.source === 'ai' && (
                      <Badge variant="outline" className="ml-1.5 px-1 text-[10px]">AI</Badge>
                    )}
                    {t.variants?.length > 0 && (
                      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                        禁用：{t.variants.join('、')}
                      </p>
                    )}
                    {t.definition && (
                      <p className="truncate text-[11px] text-muted-foreground">{t.definition}</p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Switch
                      checked={t.enabled}
                      onCheckedChange={(v) => updateTerm.mutate({ id: t.id, enabled: v })}
                      aria-label="启用/停用"
                    />
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      aria-label="删除"
                      onClick={() =>
                        deleteTerm.mutate(t.id, { onSuccess: () => toast.success('已删除') })
                      }
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ② AI 抽取 */}
        <div className="space-y-2 border-t pt-3">
          <div className="flex items-center justify-between">
            <h4 className="flex items-center gap-1.5 text-[13px] font-semibold">
              <Sparkles className="size-3.5 text-ai" />
              AI 抽取候选
            </h4>
            <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={handleExtract} disabled={extracting}>
              {extracting ? <Loader2 className="size-3 animate-spin" /> : <Sparkles className="size-3" />}
              从已写章节抽取
            </Button>
          </div>
          {extractResult && extractResult.candidates.length > 0 && (
            <>
              <ul className="space-y-1">
                {extractResult.candidates.map((c, i) => {
                  const dup = terms.some((t: TermEntry) => t.term === c.term)
                  return (
                    <li key={i} className="flex items-start gap-2 rounded-lg border px-3 py-2">
                      <input
                        type="checkbox"
                        disabled={dup}
                        checked={Boolean(selectedCandidates[i]) && !dup}
                        onChange={(e) =>
                          setSelectedCandidates((m) => ({ ...m, [i]: e.target.checked }))
                        }
                        className="mt-1 size-3.5 shrink-0 accent-foreground"
                      />
                      <div className="min-w-0 flex-1 text-[12px]">
                        <span className={dup ? 'text-muted-foreground line-through' : 'font-medium'}>
                          {c.term}
                        </span>
                        {dup && <span className="ml-1 text-[11px] text-muted-foreground">（已存在）</span>}
                        {c.variants.length > 0 && (
                          <span className="ml-1 text-muted-foreground">变体：{c.variants.join('、')}</span>
                        )}
                        <span className="ml-1 text-[11px] text-muted-foreground">×{c.occurrences}</span>
                      </div>
                    </li>
                  )
                })}
              </ul>
              <Button size="sm" className="h-7 text-xs" onClick={handleImportSelected}>
                入库所选
              </Button>
            </>
          )}
        </div>

        {/* ③ 一致性检查 */}
        <div className="space-y-2 border-t pt-3">
          <div className="flex items-center justify-between">
            <h4 className="flex items-center gap-1.5 text-[13px] font-semibold">
              <RefreshCw className="size-3.5 text-muted-foreground" />
              一致性检查
            </h4>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <Switch checked={llmVerify} onCheckedChange={setLlmVerify} />
                LLM 复核误报
              </label>
              <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={handleCheck} disabled={checking}>
                {checking ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />}
                检查全文
              </Button>
            </div>
          </div>

          {checkResult && (
            <div className="space-y-2">
              {checkResult.rule_issues.length === 0 && checkResult.llm_suggestions.length === 0 && (
                <p className="text-[12px] text-muted-foreground">未发现术语一致性问题。</p>
              )}
              {checkResult.rule_issues.length > 0 && (
                <>
                  <p className="text-[11px] text-muted-foreground">
                    以下为子串匹配结果，可能包含误报（如复合词「存储单元」含「单元」），请结合上下文判断。
                  </p>
                  <ul className="space-y-1">
                    {checkResult.rule_issues.map((r, i) => (
                      <li key={i} className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-[12px]">
                        <span className={r.verified === false ? 'text-muted-foreground' : ''}>
                          <span className="font-medium">{r.term}</span>
                          <span className="mx-1 text-muted-foreground">←</span>
                          误用「{r.variant}」×{r.count}
                          <span className="ml-1 text-muted-foreground">
                            （{r.section_keys.map((k) => keyTitleMap.get(k) ?? k).join('、')}）
                          </span>
                          {r.verified === false && (
                            <Badge variant="outline" className="ml-1.5 px-1 text-[10px]">疑似误报</Badge>
                          )}
                        </span>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 shrink-0 gap-1 px-2 text-[11px]"
                          onClick={() => handleReviseVariant(r.term, r.variant, r.section_keys)}
                        >
                          <Wand2 className="size-3" />
                          去修订
                        </Button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {checkResult.llm_suggestions.length > 0 && (
                <>
                  <p className="text-[11px] text-muted-foreground">
                    以下概念在正文中有多种说法但未登记，建议加入术语表统一：
                  </p>
                  <ul className="space-y-1">
                    {checkResult.llm_suggestions.map((d, i) => (
                      <li key={i} className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-[12px]">
                        <span>
                          <span className="font-medium">{d.concept}</span>
                          <span className="ml-1 text-muted-foreground">变体：{d.variants.join('、')}</span>
                        </span>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 shrink-0 gap-1 px-2 text-[11px]"
                          onClick={() => handleAddDrift(d.concept, d.variants)}
                        >
                          <Plus className="size-3" />
                          加入术语表
                        </Button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
