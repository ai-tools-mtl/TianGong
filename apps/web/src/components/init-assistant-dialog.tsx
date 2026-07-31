'use client'

import { Loader2, MessageSquarePlus, RotateCcw, Sparkles } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import ReactMarkdown from 'react-markdown'
import { useRouter } from 'next/navigation'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { queryKeys } from '@/lib/queries'
import { cn } from '@/lib/utils'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

type Phase = 'input' | 'chat' | 'generating'

interface ChapterProgress {
  index: number
  total: number
  title: string
  key: string
  status: 'pending' | 'generating' | 'ok' | 'failed'
  error: string | null
}

// 8 章固定结构（与后端 DEFAULT_STRUCTURE 一致）。生成前供用户勾选，控制 token 成本。
const ALL_CHAPTERS: { key: string; title: string }[] = [
  { key: 'name', title: '发明名称' },
  { key: 'field', title: '技术领域' },
  { key: 'background', title: '背景技术' },
  { key: 'problem', title: '发明目的与技术问题' },
  { key: 'solution', title: '技术方案' },
  { key: 'effect', title: '有益效果' },
  { key: 'drawings', title: '附图说明' },
  { key: 'embodiment', title: '具体实施方式' },
]

/**
 * 项目初始化助手：对话式新建项目。
 *
 * 流程：输入想法描述 → 建项目+8空章节 → 与助手对话理清思路 →
 * 一键生成 8 章初稿（流式进度）→ 跳转项目页微调。
 *
 * 详见 docs/superpowers/plans/2026-07-30-init-assistant.md。
 */
export function InitAssistantDialog() {
  const router = useRouter()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState<Phase>('input')
  const [description, setDescription] = useState('')
  const [projectId, setProjectId] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [chatSending, setChatSending] = useState(false)
  const [chapters, setChapters] = useState<ChapterProgress[]>([])
  const [currentChapterDraft, setCurrentChapterDraft] = useState('')
  const [selectedSections, setSelectedSections] = useState<string[]>(ALL_CHAPTERS.map((c) => c.key))
  const [showPicker, setShowPicker] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  // 跟踪本轮生成中失败的章节 key（避开 stale closure：异步 SSE 回调里读 state 是旧快照）
  const failedKeysRef = useRef<Set<string>>(new Set())
  const scrollRef = useRef<HTMLDivElement>(null)

  // 对话区自动滚到底
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, currentChapterDraft])

  // 关闭对话框时重置状态（下次打开是干净的）
  function handleOpenChange(next: boolean) {
    if (!next) {
      abortRef.current?.abort()
      setOpen(false)
      // 延迟重置，避免关闭动画中闪烁
      setTimeout(() => {
        setPhase('input')
        setDescription('')
        setProjectId(null)
        setConversationId(null)
        setMessages([])
        setInput('')
        setChapters([])
        setCurrentChapterDraft('')
        setSelectedSections(ALL_CHAPTERS.map((c) => c.key))
        setShowPicker(false)
      }, 200)
    } else {
      setOpen(true)
    }
  }

  // 第 1 步：从描述建项目，进入对话
  async function handleStart() {
    if (!description.trim()) return
    try {
      const res = await api.createProjectFromChat(description.trim())
      setProjectId(res.project_id)
      setPhase('chat')
      // 把用户的描述作为第一条 user 消息展示，并立即让助手回复
      await sendFirstMessage(res.project_id, description.trim())
    } catch (e) {
      toast.error('创建项目失败：' + ((e as { message?: string })?.message ?? String(e)))
    }
  }

  // 首条消息：把描述发给助手，展示流式回复
  async function sendFirstMessage(pid: string, msg: string) {
    setMessages([{ role: 'user', content: msg }])
    setChatSending(true)
    const ac = new AbortController()
    abortRef.current = ac
    let assistantText = ''
    try {
      await api.streamInitChat(
        pid, msg,
        (t) => {
          assistantText += t
          setMessages([{ role: 'user', content: msg }, { role: 'assistant', content: assistantText }])
        },
        ac.signal,
        undefined,
        (done) => {
          if (done.conversation_id) setConversationId(done.conversation_id)
        },
      )
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') {
        toast.error('AI 回复失败：' + ((e as { message?: string })?.message ?? String(e)))
      }
    } finally {
      setChatSending(false)
    }
  }

  // 后续对话：发送消息
  async function handleSend() {
    if (!input.trim() || !projectId || chatSending) return
    const msg = input.trim()
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: msg }])
    setChatSending(true)
    const ac = new AbortController()
    abortRef.current = ac
    let assistantText = ''
    try {
      await api.streamInitChat(
        projectId, msg,
        (t) => {
          assistantText += t
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = { role: 'assistant', content: assistantText }
            } else {
              next.push({ role: 'assistant', content: assistantText })
            }
            return next
          })
        },
        ac.signal,
        conversationId ?? undefined,
        (done) => {
          if (done.conversation_id) setConversationId(done.conversation_id)
        },
      )
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') {
        toast.error('AI 回复失败：' + ((e as { message?: string })?.message ?? String(e)))
      }
    } finally {
      setChatSending(false)
    }
  }

  // 第 3 步：批量生成章节初稿。
  // - 首次生成：按 selectedSections 过滤，重置 chapters。
  // - 重试（isRetry=true）：只跑当前 failed 的 key，复用已有 chapters 进度（不重置），
  //   且不自动跳转（让用户看到重试结果后再手动进项目）。
  async function handleGenerate(isRetry = false) {
    if (!projectId) return
    const targetSections = isRetry
      ? chapters.filter((c) => c.status === 'failed').map((c) => c.key)
      : selectedSections
    if (targetSections.length === 0) {
      toast.error('请至少选择一个章节')
      return
    }
    setPhase('generating')
    setCurrentChapterDraft('')
    if (!isRetry) setChapters([])
    failedKeysRef.current = new Set()  // 本轮重置失败跟踪
    const ac = new AbortController()
    abortRef.current = ac
    try {
      await api.streamInitGenerate(
        projectId,
        {
          onChapterStart: (d) => {
            setCurrentChapterDraft('')
            setChapters((prev) => {
              const exists = prev.find((c) => c.key === d.key)
              if (exists) {
                // 重试场景：复用原 index，置 generating
                return prev.map((c) => (c.key === d.key ? { ...c, status: 'generating', error: null } : c))
              }
              return [...prev, {
                index: d.index, total: d.total, title: d.title, key: d.key,
                status: 'generating', error: null,
              }]
            })
          },
          onToken: (t) => setCurrentChapterDraft((prev) => prev + t),
          onChapterDone: (d) => {
            setCurrentChapterDraft('')
            // ref 跟踪失败（onAllDone 用，避开 stale closure）
            if (d.status === 'failed') failedKeysRef.current.add(d.key)
            else failedKeysRef.current.delete(d.key)
            setChapters((prev) => prev.map((c) =>
              c.key === d.key ? { ...c, status: d.status as 'ok' | 'failed', error: d.error } : c
            ))
          },
          onAllDone: () => {
            qc.invalidateQueries({ queryKey: queryKeys.projects })
            // 重试场景：不自动跳转，留在进度页让用户确认结果
            if (isRetry) return
            // 首次生成：全 ok 才自动跳转；有 failed 留着让用户重试
            if (failedKeysRef.current.size === 0) {
              toast.success('项目初稿已生成')
              handleOpenChange(false)
              router.push(`/projects/${projectId}`)
            } else {
              toast.warning('部分章节生成失败，可点击「重试失败章节」')
            }
          },
        },
        ac.signal,
        conversationId ?? undefined,
        targetSections,
      )
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') {
        toast.error('生成失败：' + ((e as { message?: string })?.message ?? String(e)))
        setPhase('chat')
      }
    }
  }

  function toggleSection(key: string) {
    setSelectedSections((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    )
  }

  // 生成完成后是否留在 generating 阶段（有失败需重试，或重试后供用户确认）
  const hasFailedChapters = chapters.some((c) => c.status === 'failed')

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" className="gap-1.5">
          <Sparkles className="size-3.5" /> AI 对话新建
        </Button>
      </DialogTrigger>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4" />
            AI 对话新建项目
          </DialogTitle>
          <DialogDescription>
            {phase === 'input' && '用一段话描述你的发明想法，助手会引导你理清思路，再一键生成 8 章初稿。'}
            {phase === 'chat' && '继续和助手聊清楚技术细节，准备好后点「生成项目骨架」。'}
            {phase === 'generating' && '正在生成各章节初稿，请勿关闭…'}
          </DialogDescription>
        </DialogHeader>

        {/* 阶段 1：输入描述 */}
        {phase === 'input' && (
          <div className="space-y-3 py-2">
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="例如：我想做一个基于大模型的智能客服路由方法，根据用户问题意图自动分发到合适的客服坐席或自助方案……"
              className="min-h-[140px] resize-none"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleStart()
              }}
            />
            <div className="flex justify-end">
              <Button onClick={handleStart} disabled={!description.trim()}>
                开始对话
              </Button>
            </div>
          </div>
        )}

        {/* 阶段 2：对话 */}
        {phase === 'chat' && (
          <>
            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto pr-1">
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={cn(
                    'flex',
                    m.role === 'user' ? 'justify-end' : 'justify-start',
                  )}
                >
                  <div
                    className={cn(
                      'max-w-[85%] rounded-lg px-3 py-2 text-[13px] leading-relaxed',
                      m.role === 'user'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted',
                    )}
                  >
                    {m.role === 'assistant' ? (
                      <div className="prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown>{m.content || '…'}</ReactMarkdown>
                      </div>
                    ) : (
                      <span className="whitespace-pre-wrap">{m.content}</span>
                    )}
                  </div>
                </div>
              ))}
              {chatSending && messages[messages.length - 1]?.role === 'user' && (
                <div className="flex justify-start">
                  <div className="rounded-lg bg-muted px-3 py-2 text-[13px] text-muted-foreground">
                    <Loader2 className="size-3.5 animate-spin" />
                  </div>
                </div>
              )}
            </div>
            <div className="space-y-2 border-t pt-3">
              <div className="flex gap-2">
                <Textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="补充技术细节…（Enter 发送，Shift+Enter 换行）"
                  className="min-h-[44px] resize-none"
                  disabled={chatSending}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      handleSend()
                    }
                  }}
                />
                <Button size="icon" onClick={handleSend} disabled={!input.trim() || chatSending}>
                  <MessageSquarePlus className="size-4" />
                </Button>
              </div>
              <div className="space-y-2">
                {/* 章节选择（控制生成范围 / token 成本） */}
                <div className="rounded-md border bg-muted/30 p-2">
                  <button
                    type="button"
                    onClick={() => setShowPicker((v) => !v)}
                    className="flex w-full items-center justify-between text-xs text-muted-foreground"
                  >
                    <span>
                      生成章节（已选 {selectedSections.length}/{ALL_CHAPTERS.length}）
                    </span>
                    <span>{showPicker ? '收起 ▲' : '选择 ▼'}</span>
                  </button>
                  {showPicker && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {ALL_CHAPTERS.map((c) => (
                        <button
                          key={c.key}
                          type="button"
                          onClick={() => toggleSection(c.key)}
                          className={cn(
                            'rounded-full border px-2 py-0.5 text-[11px] transition-colors',
                            selectedSections.includes(c.key)
                              ? 'border-primary bg-primary text-primary-foreground'
                              : 'bg-background text-muted-foreground hover:bg-muted',
                          )}
                        >
                          {c.title}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex justify-end">
                  <Button
                    onClick={() => handleGenerate(false)}
                    disabled={chatSending || selectedSections.length === 0}
                    className="gap-1.5"
                  >
                    <Sparkles className="size-3.5" /> 生成项目骨架
                  </Button>
                </div>
              </div>
            </div>
          </>
        )}

        {/* 阶段 3：生成进度 */}
        {phase === 'generating' && (
          <>
            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto pr-1">
              {chapters.length === 0 && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> 准备生成…
                </div>
              )}
              {chapters.map((c) => (
                <div key={c.index} className="rounded-lg border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[13px] font-medium">
                      {c.index}/{c.total} {c.title}
                    </span>
                    {c.status === 'generating' && <Loader2 className="size-3.5 animate-spin text-primary" />}
                    {c.status === 'ok' && <span className="text-xs text-green-600">✓ 完成</span>}
                    {c.status === 'failed' && (
                      <span className="text-xs text-destructive" title={c.error ?? undefined}>
                        ✗ 失败
                      </span>
                    )}
                  </div>
                  {c.status === 'generating' && currentChapterDraft && (
                    <p className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">
                      {currentChapterDraft.slice(-120)}
                    </p>
                  )}
                </div>
              ))}
            </div>
            {/* 底部操作栏：全部生成结束（无 generating）后显示。
                - 有失败：可「重试失败章节」或先「进入项目」（已成功的章节已落库）
                - 全成功：首次已在 onAllDone 自动跳转；重试场景留在原地供确认 */}
            {chapters.length > 0 && !chapters.some((c) => c.status === 'generating') && (
              <div className="flex items-center justify-between gap-2 border-t pt-3">
                <span className="text-xs text-muted-foreground">
                  {hasFailedChapters
                    ? `${chapters.filter((c) => c.status === 'failed').length} 章失败，可重试或先进入项目`
                    : '全部章节已生成'}
                </span>
                <div className="flex gap-2">
                  {hasFailedChapters && (
                    <Button variant="outline" onClick={() => handleGenerate(true)} className="gap-1.5">
                      <RotateCcw className="size-3.5" /> 重试失败章节
                    </Button>
                  )}
                  <Button
                    onClick={() => {
                      handleOpenChange(false)
                      router.push(`/projects/${projectId}`)
                    }}
                    className="gap-1.5"
                  >
                    进入项目
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
