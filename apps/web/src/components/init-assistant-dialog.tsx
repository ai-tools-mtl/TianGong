'use client'

import { Loader2, MessageSquarePlus, Sparkles } from 'lucide-react'
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
  const abortRef = useRef<AbortController | null>(null)
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

  // 第 3 步：批量生成 8 章初稿
  async function handleGenerate() {
    if (!projectId) return
    setPhase('generating')
    setChapters([])
    setCurrentChapterDraft('')
    const ac = new AbortController()
    abortRef.current = ac
    try {
      await api.streamInitGenerate(
        projectId,
        {
          onChapterStart: (d) => {
            setCurrentChapterDraft('')
            setChapters((prev) => {
              const exists = prev.find((c) => c.index === d.index)
              if (exists) {
                return prev.map((c) => (c.index === d.index ? { ...c, status: 'generating' } : c))
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
            setChapters((prev) => prev.map((c) =>
              c.index === d.index ? { ...c, status: d.status as 'ok' | 'failed', error: d.error } : c
            ))
          },
          onAllDone: () => {
            // 失效项目列表（新项目 + 章节已填充），跳转项目页
            qc.invalidateQueries({ queryKey: queryKeys.projects })
            toast.success('项目初稿已生成')
            handleOpenChange(false)
            router.push(`/projects/${projectId}`)
          },
        },
        ac.signal,
        conversationId ?? undefined,
      )
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') {
        toast.error('生成失败：' + ((e as { message?: string })?.message ?? String(e)))
        setPhase('chat')
      }
    }
  }

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
              <div className="flex justify-end">
                <Button onClick={handleGenerate} disabled={chatSending} className="gap-1.5">
                  <Sparkles className="size-3.5" /> 生成项目骨架
                </Button>
              </div>
            </div>
          </>
        )}

        {/* 阶段 3：生成进度 */}
        {phase === 'generating' && (
          <div className="flex-1 space-y-3 overflow-y-auto pr-1">
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
        )}
      </DialogContent>
    </Dialog>
  )
}
