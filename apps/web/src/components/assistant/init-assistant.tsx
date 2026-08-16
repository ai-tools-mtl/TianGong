'use client'

import { Loader2, RotateCcw, Sparkles } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import ReactMarkdown from 'react-markdown'

import { AgentSteps } from '@/components/ai/agent-steps'
import { AssistantConversationList } from '@/components/assistant/assistant-conversation-list'
import { OutlinePreview } from '@/components/assistant/outline-preview'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import {
  useAssistantConversation,
  useAssistantConversations,
  useCreateAssistantConversation,
  useDeleteAssistantConversation,
  useInvalidateAssistantList,
} from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { MessageMeta, ToolEvent } from '@/types/api'

/** 维度覆盖率（后端 brief_dimensions.compute_coverage 输出）。 */
type Coverage = {
  covered: string[]
  missing: string[]
  ready: boolean
  core_filled: [number, number]
  aligned: boolean
  alignment_detail: Record<string, number>
}

const GUIDE = '描述你的发明想法，我帮你理清思路并生成交底书初稿。'

/** 三点呼吸：等待 AI 首 token 时的打字指示（init 助手）。三点半靠 delay 错峰。 */
function TypingDots() {
  return (
    <div className="flex items-center gap-1 py-0.5" aria-label="正在思考">
      {[0, 0.15, 0.3].map((d) => (
        <span
          key={d}
          className="typing-dot size-1.5 rounded-full bg-muted-foreground"
          style={{ animation: `typing-dot 0.75s ${d}s ease-in-out infinite` }}
        />
      ))}
    </div>
  )
}

/**
 * 拖拽调整右侧预览宽度的手柄。挂在预览面板左缘。
 * 用 Pointer Events + setPointerCapture 实现，拖拽中鼠标移出手柄也不丢事件。
 * 向左拖（dx 负）→ 面板变宽；clamp 在 [minW, maxW]。
 */
const PREVIEW_MIN_W = 240
const PREVIEW_MAX_W = 520

function ResizeHandle({ onResize }: { onResize: (dx: number) => void }) {
  function handlePointerDown(e: ReactPointerEvent<HTMLDivElement>) {
    e.preventDefault()
    const target = e.currentTarget
    target.setPointerCapture(e.pointerId)
    let lastX = e.clientX
    function move(ev: PointerEvent) {
      onResize(lastX - ev.clientX) // 向左拖 dx>0 → 变宽
      lastX = ev.clientX
    }
    function up(ev: PointerEvent) {
      target.releasePointerCapture(ev.pointerId)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="拖动调整预览宽度"
      onPointerDown={handlePointerDown}
      className="absolute -left-[3px] top-0 z-10 h-full w-[6px] cursor-col-resize group/handle"
    >
      {/* 实际可见的握把条：默认极淡，hover/拖拽时显形 */}
      <span className="absolute left-1/2 top-1/2 h-8 w-[2px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted-foreground/20 transition-colors group-hover/handle:bg-primary/50" />
    </div>
  )
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  // assistant 消息是否触发过创建扳机（覆盖率达标）
  ready?: boolean
  /** agent 透明化：本轮思考过程（流式累积 / 历史回灌） */
  thinking?: string
  /** agent 透明化：本轮工具调用事件序列（流式累积 / 历史回灌） */
  toolEvents?: ToolEvent[]
  /** 回复被中断（历史回灌）：后端兜底落了半截内容，非正常结束。 */
  incomplete?: boolean
}

interface ChapterProgress {
  index: number; total: number; title: string; key: string
  status: 'generating' | 'ok' | 'failed'; error: string | null
}

export function InitAssistant() {
  const router = useRouter()
  const { data: conversations, isLoading: listLoading } = useAssistantConversations()
  const createConv = useCreateAssistantConversation()
  const deleteConv = useDeleteAssistantConversation()
  // 收敛的列表失效器（exact:true 内置），杜绝内联调用漏写 flag 导致丢对话回归。
  const invalidateAssistantList = useInvalidateAssistantList()

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
  // 右侧预览面板宽度（px），可拖拽手柄调整。clamp 在 [240, 520]。
  const [previewWidth, setPreviewWidth] = useState(320)
  // 维度覆盖率：done 回调从后端 coverage 更新；驱动 ready 判断（替代旧的标记字符串扫描）。
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  // 自动建会话只跑一次的守卫：避免 React StrictMode（dev 下 effect 双触发）与
  // React Query invalidate 期间的瞬时空态重复建出大量「新对话」。
  const autoCreatedRef = useRef(false)

  // 首次加载：若无会话则建一个；有则选第一个
  useEffect(() => {
    if (!listLoading && conversations) {
      if (conversations.length === 0) {
        // 列表为空才建，且只建一次（autoCreatedRef 守卫）。删除最后一个会话后不再自动建，
        // 避免删除即重生、以及 StrictMode 双触发重复建会话。
        if (!autoCreatedRef.current) {
          autoCreatedRef.current = true
          createConv.mutate(undefined, { onSuccess: (c) => setCurrentId(c.id) })
        }
      } else if (!currentId) {
        setCurrentId(conversations[0].id)
      }
    }
  }, [listLoading, conversations, currentId, createConv])

  // 切换会话：用服务端历史初始化本地 messages。只在会话 id 真正变化时跑一次——
  // 用 lastLoadedIdRef 守卫，确保对话进行中（current 因重拉/refetch 引用变化但 id 不变）
  // 不会用服务端快照覆盖本地流式渲染的 messages（那是「丢对话」的根因）。
  const lastLoadedIdRef = useRef<string | null>(null)
  useEffect(() => {
    const id = current?.id ?? null
    if (id === lastLoadedIdRef.current) return // 同一会话，不重复初始化（防覆盖）
    lastLoadedIdRef.current = id
    if (current) {
      setMessages(current.messages.map((m: { id: string; role: string; content: string; meta?: MessageMeta | null; created_at: string }) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        // 历史回灌：从 Message.meta 恢复思考过程 + 工具调用（刷新后仍可见）
        thinking: m.meta?.thinking,
        toolEvents: m.meta?.tool_events,
        // 历史回灌：恢复中断标记（后端兜底落的半截回复）
        incomplete: m.meta?.incomplete,
      })))
      setCreatedProjectId(current.project_id)
      setGenerating(false)
      setChapters([])
      // 恢复该会话已有的草稿大纲 + 覆盖率（后端每轮提取后写 draft_outline，并据此算 coverage）
      setOutline((current as { draft_outline?: Record<string, { title: string; content: string }> | null }).draft_outline ?? null)
      setCoverage((current as { coverage?: Coverage | null }).coverage ?? null)
    } else {
      // 会话被删除/清空：清掉残留的本地状态，避免显示已删会话的内容
      setMessages([])
      setCreatedProjectId(null)
      setOutline(null)
      setCoverage(null)
      setChapters([])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id])

  // 自动滚底
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, chapters])

  function handleNew() {
    // 切会话前 abort 在途的流式请求，避免旧会话的 token 回调污染新会话的 messages（丢对话根因）。
    abortRef.current?.abort()
    createConv.mutate(undefined, { onSuccess: (c) => setCurrentId(c.id) })
  }

  function handleDelete(id: string) {
    // 同上：删/切会话前 abort。
    abortRef.current?.abort()
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
    // agent 透明化累积器（思考过程 + 工具调用，合并进最后一条 assistant 消息）
    let aiThinking = ''
    const aiToolEvents: ToolEvent[] = []
    /** 把累积的 thinking/toolEvents 合并进最后一条 assistant 消息。 */
    const mergeAgentState = () => {
      setMessages((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (last && last.role === 'assistant') {
          next[next.length - 1] = {
            ...last,
            thinking: aiThinking || undefined,
            toolEvents: aiToolEvents.length ? [...aiToolEvents] : undefined,
          }
        }
        return next
      })
    }
    try {
      await api.streamAssistantChat(
        currentId, msg,
        (t) => {
          full += t
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              // 保留已累积的 thinking/toolEvents（思考阶段写入），仅更新 content。
              next[next.length - 1] = { ...last, content: full }
            }
            return next
          })
        },
        ac.signal,
        (done) => {
          // 后端在首轮生成总结性标题后回传 title。失效列表缓存使左侧显示新名称。
          // 用收敛的 helper（内置 exact:true），避免误伤单会话详情子 key → 重拉 → 覆盖本地流式 messages（丢对话）。
          if (done.title) {
            invalidateAssistantList()
          }
          // 后端提取的 8 章草稿大纲 + 维度覆盖率回传 → 刷新右侧预览 + ready 判断
          if (done.outline) setOutline(done.outline)
          if (done.coverage) {
            setCoverage(done.coverage)
            // ready 由覆盖率决定（替代旧的标记字符串扫描）
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              if (last && last.role === 'assistant' && done.coverage?.ready) {
                next[next.length - 1] = { ...last, ready: true }
              }
              return next
            })
          }
        },
        undefined,
        {
          onThinking: (t) => { aiThinking += t; mergeAgentState() },
          onToolCall: (e) => { aiToolEvents.push({ kind: 'call', name: e.name, args: e.args }); mergeAgentState() },
          onToolResult: (e) => { aiToolEvents.push({ kind: 'result', name: e.name, result: e.result }); mergeAgentState() },
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
            // 落地后会话从列表消失，用 helper 刷新列表（不重拉/覆盖单会话详情，避免丢对话）。
            invalidateAssistantList()
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
        onSelect={(id) => { abortRef.current?.abort(); setCurrentId(id) }}
        onNew={handleNew}
        onDelete={handleDelete}
      />
      <div className="flex flex-1 flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
            {messages.length === 0 && !showChapterProgress && (
              <div className="mt-20 text-center">
                <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-full bg-muted">
                  <Sparkles className="size-7 text-primary" />
                </div>
                <p className="text-lg font-medium tracking-tight">{GUIDE}</p>
                <p className="mt-1 text-sm text-muted-foreground">在下方输入框开始描述</p>
              </div>
            )}
            {messages.map((m, i) => {
              // 等待态：发送中、最后一条 assistant 消息、尚无 token 且无思考/工具 → 三点呼吸
              const isWaiting =
                sending &&
                i === messages.length - 1 &&
                m.role === 'assistant' &&
                !m.content &&
                !m.thinking &&
                !m.toolEvents?.length
              return (
                <div key={i} className={cn('flex bubble-in', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <div
                    className={cn(
                      'max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed',
                      m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted',
                    )}
                    style={{ boxShadow: 'var(--shadow-card)' }}
                  >
                    {isWaiting ? (
                      <TypingDots />
                    ) : m.role === 'assistant' ? (
                      <>
                        {/* agent 透明化：思考过程 + 工具调用（正文之前；流式时 streaming=true） */}
                        <AgentSteps
                          thinking={m.thinking}
                          toolEvents={m.toolEvents}
                          streaming={sending && i === messages.length - 1 && !m.content}
                        />
                        <div className="prose prose-sm max-w-none dark:prose-invert">
                          <ReactMarkdown>{m.content.trim()}</ReactMarkdown>
                        </div>
                        {/* 中断标记：后端兜底落的半截回复（切会话/断连/异常），提示非正常结束 */}
                        {m.incomplete && (
                          <div className="mt-1.5 flex items-center gap-1 text-[11px] text-muted-foreground/70">
                            <span className="inline-block size-1.5 rounded-full bg-muted-foreground/40" />
                            回复已中断
                          </div>
                        )}
                      </>
                    ) : (
                      <span className="whitespace-pre-wrap">{m.content}</span>
                    )}
                  </div>
                </div>
              )
            })}

            {/* 创建扳机：agent 标记 ready 时 */}
            {showReadyButton && (
              <div className="flex justify-center">
                <Button onClick={() => handleGenerate(false)} disabled={generating} className="apple-lift gap-1.5" style={{ boxShadow: 'var(--shadow-cta)' }}>
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
      {/* 右侧文档实时预览：每轮对话后由轻量 LLM 提取 8 章草稿 + 维度覆盖率，实时刷新。桌面端常驻。
          外层 relative 给拖拽手柄（absolute 定位）做参照。 */}
      <div className="relative hidden lg:block">
        <ResizeHandle
          onResize={(dx) => setPreviewWidth((w) => Math.min(PREVIEW_MAX_W, Math.max(PREVIEW_MIN_W, w + dx)))}
        />
        <OutlinePreview outline={outline} coverage={coverage} extracting={sending} width={previewWidth} />
      </div>
    </div>
  )
}
