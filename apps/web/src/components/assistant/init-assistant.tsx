'use client'

import { Loader2, RotateCcw, Sparkles } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import ReactMarkdown from 'react-markdown'

import { AssistantConversationList } from '@/components/assistant/assistant-conversation-list'
import { OutlinePreview } from '@/components/assistant/outline-preview'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import {
  queryKeys,
  useAssistantConversation,
  useAssistantConversations,
  useCreateAssistantConversation,
  useDeleteAssistantConversation,
} from '@/lib/queries'
import { cn } from '@/lib/utils'

const READY_MARKER = '[READY_TO_CREATE]'
const GUIDE = '描述你的发明想法，我帮你理清思路并生成交底书初稿。'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  // assistant 消息是否触发过创建扳机（含 READY 标记）
  ready?: boolean
}

interface ChapterProgress {
  index: number; total: number; title: string; key: string
  status: 'generating' | 'ok' | 'failed'; error: string | null
}

export function InitAssistant() {
  const router = useRouter()
  const qc = useQueryClient()
  const { data: conversations, isLoading: listLoading } = useAssistantConversations()
  const createConv = useCreateAssistantConversation()
  const deleteConv = useDeleteAssistantConversation()

  const [currentId, setCurrentId] = useState<string | null>(null)
  const { data: current } = useAssistantConversation(currentId)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null)
  const [chapters, setChapters] = useState<ChapterProgress[]>([])
  // 右侧文档预览大纲：done 回调从后端 outline 更新；切会话从 draft_outline 恢复。
  const [outline, setOutline] = useState<Record<string, { title: string; content: string }> | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 首次加载：若无会话则建一个；有则选第一个
  useEffect(() => {
    if (!listLoading && conversations) {
      if (conversations.length === 0) {
        createConv.mutate(undefined, { onSuccess: (c) => setCurrentId(c.id) })
      } else if (!currentId) {
        setCurrentId(conversations[0].id)
      }
    }
  }, [listLoading, conversations, currentId, createConv])

  // 切换会话：加载历史消息
  useEffect(() => {
    if (current) {
      setMessages(current.messages.map((m: { id: string; role: string; content: string; created_at: string }) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        ready: m.role === 'assistant' && m.content.includes(READY_MARKER),
      })))
      setCreatedProjectId(current.project_id)
      setGenerating(false)
      setChapters([])
      // 恢复该会话已有的草稿大纲（后端每轮提取后写 draft_outline）
      setOutline((current as { draft_outline?: Record<string, { title: string; content: string }> | null }).draft_outline ?? null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id])

  // 自动滚底
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, chapters])

  function handleNew() {
    createConv.mutate(undefined, { onSuccess: (c) => setCurrentId(c.id) })
  }

  function handleDelete(id: string) {
    deleteConv.mutate(id, {
      onSuccess: () => { if (id === currentId) setCurrentId(null) },
    })
  }

  async function handleSend() {
    if (!input.trim() || !currentId || sending || generating) return
    const msg = input.trim()
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: msg }, { role: 'assistant', content: '' }])
    setSending(true)
    const ac = new AbortController()
    abortRef.current = ac
    let full = ''
    try {
      await api.streamAssistantChat(
        currentId, msg,
        (t) => {
          full += t
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = { role: 'assistant', content: full, ready: full.includes(READY_MARKER) }
            }
            return next
          })
        },
        ac.signal,
        (done) => {
          // 后端提取的 8 章草稿大纲回传 → 刷新右侧预览
          if (done.outline) setOutline(done.outline)
          if (done.ready_to_create) {
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              if (last && last.role === 'assistant') next[next.length - 1] = { ...last, ready: true }
              return next
            })
          }
        },
      )
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') {
        toast.error('回复失败：' + ((e as { message?: string })?.message ?? String(e)))
      }
    } finally {
      setSending(false)
    }
  }

  async function handleGenerate(isRetry = false) {
    if (!currentId) return
    const targetSections = isRetry ? chapters.filter((c) => c.status === 'failed').map((c) => c.key) : undefined
    setGenerating(true)
    if (!isRetry) {
      setChapters([])
      setCreatedProjectId(null)
    }
    const ac = new AbortController()
    abortRef.current = ac
    const failedKeys = new Set<string>()
    try {
      await api.streamAssistantGenerate(
        currentId,
        {
          onProjectCreated: (d) => setCreatedProjectId(d.project_id),
          onChapterStart: (d) => setChapters((prev) => {
            const exists = prev.find((c) => c.key === d.key)
            if (exists) return prev.map((c) => c.key === d.key ? { ...c, status: 'generating' } : c)
            return [...prev, { ...d, status: 'generating', error: null }]
          }),
          onToken: () => {},
          onChapterDone: (d) => {
            if (d.status === 'failed') failedKeys.add(d.key)
            else failedKeys.delete(d.key)
            setChapters((prev) => prev.map((c) => c.key === d.key ? { ...c, status: d.status as 'ok' | 'failed', error: d.error } : c))
          },
          onAllDone: () => {
            qc.invalidateQueries({ queryKey: queryKeys.assistant.conversations })
            if (!isRetry && failedKeys.size === 0) toast.success('项目初稿已生成')
            else if (failedKeys.size > 0) toast.warning('部分章节失败，可重试')
          },
        },
        ac.signal,
        targetSections,
      )
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') {
        toast.error('生成失败：' + ((e as { message?: string })?.message ?? String(e)))
      }
    } finally {
      setGenerating(false)
    }
  }

  const hasFailed = chapters.some((c) => c.status === 'failed')
  const showChapterProgress = chapters.length > 0
  // 扳机：assistant 标记 ready 且未在生成、未落地、未进入章节进度
  const showReadyButton =
    !generating && !showChapterProgress && !createdProjectId &&
    messages.some((m) => m.ready)

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <AssistantConversationList
        conversations={conversations ?? []}
        currentId={currentId}
        loading={listLoading}
        onSelect={setCurrentId}
        onNew={handleNew}
        onDelete={handleDelete}
      />
      <div className="flex flex-1 flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
            {messages.length === 0 && !showChapterProgress && (
              <div className="mt-20 text-center">
                <Sparkles className="mx-auto mb-3 size-8 text-primary" />
                <p className="text-lg font-medium">{GUIDE}</p>
                <p className="mt-1 text-sm text-muted-foreground">在下方输入框开始描述</p>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                <div className={cn(
                  'max-w-[85%] rounded-lg px-3 py-2 text-[13px] leading-relaxed',
                  m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted',
                )}>
                  {m.role === 'assistant' ? (
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown>{m.content.replace(READY_MARKER, '').trim() || '…'}</ReactMarkdown>
                    </div>
                  ) : (
                    <span className="whitespace-pre-wrap">{m.content}</span>
                  )}
                </div>
              </div>
            ))}

            {/* 创建扳机：agent 标记 ready 时 */}
            {showReadyButton && (
              <div className="flex justify-center">
                <Button onClick={() => handleGenerate(false)} className="gap-1.5">
                  <Sparkles className="size-3.5" /> 信息已理清，创建项目
                </Button>
              </div>
            )}

            {/* 章节生成进度 */}
            {showChapterProgress && (
              <div className="space-y-2 rounded-lg border p-3">
                <p className="text-xs font-medium text-muted-foreground">
                  {generating ? '生成项目初稿…' : '生成完成'}
                </p>
                {chapters.map((c) => (
                  <div key={c.key} className="flex items-center justify-between text-[13px]">
                    <span>{c.index}/{c.total} {c.title}</span>
                    {c.status === 'generating' && <Loader2 className="size-3.5 animate-spin text-primary" />}
                    {c.status === 'ok' && <span className="text-xs text-green-600">✓</span>}
                    {c.status === 'failed' && <span className="text-xs text-destructive">✗</span>}
                  </div>
                ))}
                {!generating && (
                  <div className="flex items-center justify-end gap-2 border-t pt-2">
                    {hasFailed && (
                      <Button variant="outline" size="sm" onClick={() => handleGenerate(true)} className="gap-1.5">
                        <RotateCcw className="size-3.5" /> 重试失败
                      </Button>
                    )}
                    {createdProjectId && (
                      <Button size="sm" onClick={() => router.push(`/projects/${createdProjectId}`)}>
                        进入项目
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* 已落地跳转卡片（非生成中、已建项目、未在进度展示时） */}
            {!generating && createdProjectId && !showChapterProgress && (
              <div className="flex justify-center">
                <div className="rounded-lg border bg-muted/50 px-4 py-2 text-center text-[13px]">
                  项目已创建{' '}
                  <Button variant="link" className="h-auto p-0" onClick={() => router.push(`/projects/${createdProjectId}`)}>
                    点此进入 →
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="border-t">
          <div className="mx-auto flex max-w-3xl gap-2 px-4 py-3">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="描述你的发明想法…（Enter 发送，Shift+Enter 换行）"
              className="min-h-[44px] resize-none"
              disabled={sending || generating || !!createdProjectId}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
              }}
            />
            <Button size="icon" onClick={handleSend} disabled={!input.trim() || sending || generating || !!createdProjectId}>
              <Sparkles className="size-4" />
            </Button>
          </div>
        </div>
      </div>
      {/* 右侧文档实时预览：每轮对话后由轻量 LLM 提取 8 章草稿，实时刷新。桌面端常驻。 */}
      <div className="hidden lg:block">
        <OutlinePreview outline={outline} extracting={sending} />
      </div>
    </div>
  )
}
