'use client'

import { GitCompare, Loader2, PanelRight, Sparkles } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import ReactMarkdown from 'react-markdown'

import { Button } from '@/components/ui/button'
import { DiffReviewPanel } from '@/components/diff-review-panel'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { queryKeys, useApplyDiff, useComputeDiff } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/ui'
import type { Hunk, Section } from '@/types/api'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

type AIPhase = 'idle' | 'chatting' | 'generating' | 'done' | 'diff-review'

interface AIChatPanelProps {
  sectionId: string
  /** 当前 section（用于读取 expected_version 做乐观锁） */
  section: Section
  /** 用于 apply-diff 成功后刷新章节缓存 */
  projectId: string
}

export function AIChatPanel({ sectionId, section, projectId }: AIChatPanelProps) {
  const qc = useQueryClient()
  const toggleRight = useUIStore((s) => s.toggleRight)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [phase, setPhase] = useState<AIPhase>('idle')
  /** 最近一次 generate 累积的 markdown 文本（用于 diff 计算） */
  const [aiDraft, setAiDraft] = useState('')
  const [hunks, setHunks] = useState<Hunk[]>([])
  const abortRef = useRef<AbortController | null>(null)

  const computeDiff = useComputeDiff(sectionId)
  const applyDiff = useApplyDiff(sectionId, projectId)

  async function handleSend() {
    if (!input.trim() || phase === 'chatting' || phase === 'generating') return
    const userMsg: ChatMessage = { role: 'user', content: input }
    setMessages((m) => [...m, userMsg, { role: 'assistant', content: '' }])
    setInput('')
    setPhase('chatting')
    abortRef.current = new AbortController()

    let aiText = ''
    try {
      await api.streamChat(sectionId, userMsg.content, (token) => {
        aiText += token
        setMessages((m) => {
          const copy = [...m]
          copy[copy.length - 1] = { role: 'assistant', content: aiText }
          return copy
        })
      }, abortRef.current.signal)
    } catch (err: unknown) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        toast.error('AI 回复失败')
      }
    } finally {
      setPhase('idle')
    }
  }

  function handleStop() {
    abortRef.current?.abort()
    setPhase((p) => (p === 'generating' ? 'done' : 'idle'))
    setMessages((m) => {
      const copy = [...m]
      const last = copy[copy.length - 1]
      if (last && last.role === 'assistant' && (!last.content || last.content === '...')) {
        copy.pop()
      }
      return copy
    })
  }

  async function handleGenerate() {
    setPhase('generating')
    setAiDraft('')
    toast.info('正在生成草稿...')
    abortRef.current = new AbortController()
    try {
      let md = ''
      await api.streamGenerate(sectionId, (token) => {
        md += token
        setAiDraft(md)
      }, abortRef.current.signal)
      toast.success('草稿已生成，点击「审查差异」预览变更')
      setPhase('done')
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        toast.info('已停止，已生成内容已保留')
        // 中断后仍有部分内容，进入 done 态供用户审查已生成部分
        setPhase('done')
      } else {
        toast.error('生成失败')
        setPhase('idle')
      }
    }
  }

  async function handleOpenDiff() {
    if (!aiDraft.trim()) {
      toast.error('没有可审查的内容')
      return
    }
    setPhase('diff-review')
    try {
      const res = await computeDiff.mutateAsync(aiDraft)
      setHunks(res.hunks)
      if (res.hunks.length === 0) {
        toast.info('AI 内容与当前章节无差异')
      }
    } catch (err: unknown) {
      const e = err as { code?: string; message?: string }
      toast.error(e?.message || '差异计算失败')
      setPhase('done')
    }
  }

  async function handleApplyDiff(acceptedHunkIds: string[]) {
    if (acceptedHunkIds.length === 0) {
      toast.info('未选择任何变更')
      return
    }
    try {
      await applyDiff.mutateAsync({
        ai_text: aiDraft,
        accepted_hunk_ids: acceptedHunkIds,
        expected_version: section.version,
      })
      toast.success(`已应用 ${acceptedHunkIds.length} 项更改`)
      // 应用成功：关闭审查面板，回到 idle，清空草稿
      setPhase('idle')
      setAiDraft('')
      setHunks([])
      // apply-diff 改写了章节内容与版本号，刷新章节缓存，编辑器自动拿到新内容
      await qc.invalidateQueries({ queryKey: queryKeys.sections(projectId) })
    } catch (err: unknown) {
      const e = err as { code?: string; message?: string }
      if (e?.code === 'conflict') {
        toast.error('章节已被修改，请重新审查差异')
      } else {
        toast.error(e?.message || '应用失败')
      }
    }
  }

  function handleCloseDiff() {
    setPhase('done')
    setHunks([])
  }

  // diff-review 阶段：全屏覆盖审查面板
  if (phase === 'diff-review') {
    return (
      <div className="h-full">
        <DiffReviewPanel
          hunks={hunks}
          sectionTitle={section.title}
          onApply={handleApplyDiff}
          onClose={handleCloseDiff}
          applying={applyDiff.isPending}
        />
      </div>
    )
  }

  const busy = phase === 'chatting' || phase === 'generating'

  return (
    <div className={cn('flex h-full flex-col', phase === 'generating' && 'ai-generating')}>
      {/* 标题栏 */}
      <div className="flex items-center justify-between gap-1 border-b px-2 py-1.5">
        <h3 className="flex items-center gap-1.5 px-1 text-[13px] font-semibold">
          <Sparkles className="size-3.5 text-ai" />
          AI 助手
        </h3>
        <div className="flex items-center gap-1">
          {phase === 'generating' ? (
            <Button size="xs" variant="destructive" onClick={handleStop}>
              停止
            </Button>
          ) : (
            <Button size="xs" variant="outline" onClick={handleGenerate} disabled={busy}>
              生成草稿
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={toggleRight}
            aria-label="收起 AI 面板"
            title="收起 AI 面板"
          >
            <PanelRight className="size-3.5" />
          </Button>
        </div>
      </div>

      {/* 内容区：生成阶段显示 markdown 预览，否则显示对话 */}
      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {phase === 'generating' || phase === 'done' ? (
          // 生成草稿的 markdown 预览
          <div className="space-y-2">
            <div className="rounded-md border-l-2 border-ai bg-ai-muted px-3 py-2">
              {phase === 'generating' && (
                <div className="mb-2 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <Loader2 className="size-3 animate-spin" />
                  生成中...
                </div>
              )}
              <div className="prose prose-sm max-w-none dark:prose-invert">
                <ReactMarkdown>{aiDraft || '（空）'}</ReactMarkdown>
              </div>
            </div>
            {phase === 'done' && (
              <div className="flex items-center gap-2">
                <Button size="sm" onClick={handleOpenDiff} disabled={computeDiff.isPending} className="gap-1.5">
                  {computeDiff.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <GitCompare className="size-3.5" />}
                  审查差异
                </Button>
                <Button size="sm" variant="outline" onClick={handleGenerate}>
                  重新生成
                </Button>
              </div>
            )}
          </div>
        ) : (
          // 对话模式
          <>
            {messages.length === 0 && (
              <div className="rounded-md bg-ai-muted px-3 py-3 text-[13px] text-ai-muted-foreground">
                向 AI 描述你的想法，或直接点「生成草稿」
              </div>
            )}
            {messages.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="flex justify-end">
                  <div className="inline-block max-w-[90%] rounded-md bg-primary px-3 py-2 text-[13px] text-primary-foreground">
                    {m.content}
                  </div>
                </div>
              ) : (
                <div key={i} className="flex justify-start">
                  <div className="inline-block max-w-[90%] rounded-md border-l-2 border-ai bg-ai-muted px-3 py-2 text-[13px] text-foreground">
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown>{m.content || '...'}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              ),
            )}
          </>
        )}
      </div>

      {/* 输入栏（生成阶段隐藏） */}
      {phase !== 'generating' && phase !== 'done' && (
        <div className="flex gap-2 border-t p-3">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) =>
              e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSend())
            }
            placeholder="问 AI..."
            disabled={busy}
            className="h-8 text-[13px]"
          />
          <Button size="sm" onClick={handleSend} disabled={busy || !input.trim()}>
            发送
          </Button>
        </div>
      )}
    </div>
  )
}
