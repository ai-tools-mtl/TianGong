'use client'

import { GitCompare, Loader2, PanelRight, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import ReactMarkdown from 'react-markdown'

import { Button } from '@/components/ui/button'
import { DiffReviewPanel } from '@/components/diff-review-panel'
import { api } from '@/lib/api'
import {
  queryKeys,
  useApplyDiff,
  useComputeDiff,
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useMessages,
} from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/ui'
import type { Conversation, Hunk, Section } from '@/types/api'

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
  const [aiDraft, setAiDraft] = useState('')
  const [hunks, setHunks] = useState<Hunk[]>([])
  const [currentConvId, setCurrentConvId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const msgLoadedForConv = useRef<string | null>(null)

  const computeDiff = useComputeDiff(sectionId)
  const applyDiff = useApplyDiff(sectionId, projectId)
  const { data: conversations, isLoading: convsLoading } = useConversations(sectionId)
  const createConv = useCreateConversation(sectionId)
  const deleteConv = useDeleteConversation(sectionId)
  const { data: history } = useMessages(sectionId, currentConvId ?? undefined)

  // 首次加载会话列表：自动选中最新（第一个）
  useEffect(() => {
    if (conversations && conversations.length > 0 && !currentConvId) {
      setCurrentConvId(conversations[0].id)
    }
  }, [conversations, currentConvId])

  // 会话或 section 变化时加载历史消息
  useEffect(() => {
    const loadKey = currentConvId ?? '__null__'
    if (history && msgLoadedForConv.current !== loadKey) {
      msgLoadedForConv.current = loadKey
      setMessages(
        history.map((m: { role: string; content: string }) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
        })),
      )
    }
  }, [history, currentConvId])

  // section 变化时重置
  useEffect(() => {
    setCurrentConvId(null)
    msgLoadedForConv.current = null
    setMessages([])
    setPhase('idle')
  }, [sectionId])

  // 自动滚到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, phase, aiDraft])

  // Textarea 自动高度
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`
  }, [input])

  // 切换会话时重置消息加载标记
  function handleSelectConversation(convId: string) {
    if (convId === currentConvId) return
    msgLoadedForConv.current = null
    setCurrentConvId(convId)
    setMessages([])
    setPhase('idle')
  }

  function handleNewConversation() {
    msgLoadedForConv.current = null
    setCurrentConvId(null)
    setMessages([])
    setPhase('idle')
    // 创建会话后由 conversations query 自动刷新
    createConv.mutate('新对话', {
      onSuccess: (conv: Conversation) => {
        setCurrentConvId(conv.id)
      },
    })
  }

  function handleDeleteConversation() {
    if (!currentConvId) return
    const convId = currentConvId
    deleteConv.mutate(convId, {
      onSuccess: () => {
        msgLoadedForConv.current = null
        setCurrentConvId(null)
        setMessages([])
        setPhase('idle')
        toast.success('会话已删除')
      },
    })
  }

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
      }, abortRef.current.signal, currentConvId ?? undefined)
      // chat 后刷新会话列表（标题可能更新）
      qc.invalidateQueries({ queryKey: ['conversations', sectionId] })
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

  function handleClearChat() {
    setMessages([])
    setPhase('idle')
    msgLoadedForConv.current = '__force__'
    toast.info('已清空当前显示')
  }

  async function handleGenerate() {
    setPhase('generating')
    setAiDraft('')
    abortRef.current = new AbortController()
    try {
      let md = ''
      await api.streamGenerate(sectionId, (token) => {
        md += token
        setAiDraft(md)
      }, abortRef.current.signal)
      setPhase('done')
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
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
      setPhase('idle')
      setAiDraft('')
      setHunks([])
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
      <div className="flex h-10 shrink-0 items-center justify-between gap-1 border-b px-2">
        <h3 className="flex items-center gap-1.5 px-1 text-[13px] font-semibold">
          <Sparkles className="size-3.5 text-ai" />
          AI 助手
        </h3>
        <div className="flex items-center gap-0.5">
          {messages.length > 0 && phase !== 'generating' && phase !== 'done' && (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={handleClearChat}
              aria-label="清空对话"
              title="清空对话"
            >
              <Trash2 className="size-3.5" />
            </Button>
          )}
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
            aria-label="收起"
            title="收起"
          >
            <PanelRight className="size-3.5" />
          </Button>
        </div>
      </div>

      {/* 会话选择栏 */}
      {phase !== 'generating' && phase !== 'done' && (
        <div className="flex h-8 shrink-0 items-center gap-1 border-b bg-muted/30 px-2">
          <select
            value={currentConvId ?? ''}
            onChange={(e) => handleSelectConversation(e.target.value)}
            className="h-6 flex-1 truncate rounded border-none bg-transparent text-[12px] outline-none cursor-pointer hover:bg-muted"
            disabled={convsLoading || createConv.isPending}
          >
            {convsLoading && <option>加载中...</option>}
            {!convsLoading && (conversations?.length ?? 0) === 0 && <option value="">新对话</option>}
            {conversations?.map((c: Conversation) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={handleNewConversation}
            disabled={createConv.isPending}
            title="新建会话"
          >
            <Plus className="size-3.5" />
          </Button>
          {currentConvId && (conversations?.length ?? 0) > 1 && (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={handleDeleteConversation}
              disabled={deleteConv.isPending}
              title="删除当前会话"
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      )}

      {/* 内容区 */}
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-3 py-3">
        {phase === 'generating' || phase === 'done' ? (
          // 生成草稿的 markdown 预览
          <div className="space-y-3">
            <div className="rounded-lg border border-ai/20 bg-ai-muted/50 px-3 py-2.5">
              {phase === 'generating' && (
                <div className="mb-2 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span className="flex gap-0.5">
                    <span className="size-1.5 animate-bounce rounded-full bg-ai [animation-delay:0ms]" />
                    <span className="size-1.5 animate-bounce rounded-full bg-ai [animation-delay:150ms]" />
                    <span className="size-1.5 animate-bounce rounded-full bg-ai [animation-delay:300ms]" />
                  </span>
                  AI 正在生成...
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
              <div className="flex flex-col items-center gap-2 py-8 text-center">
                <Sparkles className="size-6 text-ai/50" />
                <p className="text-[13px] text-muted-foreground">
                  向 AI 描述你的想法<br />或直接点「生成草稿」
                </p>
              </div>
            )}
            {messages.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-[13px] leading-relaxed text-primary-foreground">
                    {m.content}
                  </div>
                </div>
              ) : (
                <div key={i} className="flex justify-start">
                  <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-ai/20 bg-ai-muted/40 px-3 py-2 text-[13px] leading-relaxed text-foreground">
                    {m.content ? (
                      <div className="prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown>{m.content}</ReactMarkdown>
                      </div>
                    ) : (
                      <span className="flex items-center gap-1 text-muted-foreground">
                        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:0ms]" />
                        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:150ms]" />
                        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:300ms]" />
                      </span>
                    )}
                  </div>
                </div>
              ),
            )}
          </>
        )}
      </div>

      {/* 输入栏（生成阶段隐藏） */}
      {phase !== 'generating' && phase !== 'done' && (
        <div className="shrink-0 border-t p-2.5">
          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="问 AI...（Shift+Enter 换行）"
              disabled={busy}
              rows={1}
              className="flex-1 resize-none rounded-lg border bg-background px-3 py-2 text-[13px] leading-relaxed outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              style={{ minHeight: '36px', maxHeight: '120px' }}
            />
            <Button size="sm" onClick={handleSend} disabled={busy || !input.trim()} className="shrink-0">
              发送
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
