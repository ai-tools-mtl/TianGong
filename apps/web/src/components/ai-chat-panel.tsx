'use client'

import { PanelRight, Sparkles } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { queryKeys } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/ui'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface AIChatPanelProps {
  sectionId: string
  /** 用于草稿生成后精确刷新当前项目的章节缓存（替代 window.location.reload） */
  projectId: string
}

export function AIChatPanel({ sectionId, projectId }: AIChatPanelProps) {
  const qc = useQueryClient()
  const toggleRight = useUIStore((s) => s.toggleRight)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  async function handleSend() {
    if (!input.trim() || loading) return
    const userMsg: ChatMessage = { role: 'user', content: input }
    setMessages((m) => [...m, userMsg, { role: 'assistant', content: '' }])
    setInput('')
    setLoading(true)
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
      // abort 不报错（用户主动停止），其他错误提示
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        toast.error('AI 回复失败')
      }
    } finally {
      setLoading(false)
    }
  }

  function handleStop() {
    abortRef.current?.abort()
    setGenerating(false)
    setMessages((m) => {
      const copy = [...m]
      // AI 气泡若为空或 '...'，移除占位
      const last = copy[copy.length - 1]
      if (last && last.role === 'assistant' && (!last.content || last.content === '...')) {
        copy.pop()
      }
      return copy
    })
  }

  async function handleGenerate() {
    setGenerating(true)
    toast.info('正在生成草稿...')
    abortRef.current = new AbortController()
    try {
      let md = ''
      await api.streamGenerate(sectionId, (token) => {
        md += token
      }, abortRef.current.signal)
      toast.success('草稿已生成并填入编辑器')
      // 刷新章节缓存，编辑器会自动拿到新内容——不再整页重载，保留三栏滚动状态
      await qc.invalidateQueries({ queryKey: queryKeys.sections(projectId) })
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        toast.info('已停止，已生成内容已保留')
        await qc.invalidateQueries({ queryKey: queryKeys.sections(projectId) })
      } else {
        toast.error('生成失败')
      }
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div
      className={cn(
        'flex h-full flex-col',
        generating && 'ai-generating',
      )}
    >
      <div className="flex items-center justify-between gap-1 border-b px-2 py-1.5">
        <h3 className="flex items-center gap-1.5 px-1 text-[13px] font-semibold">
          <Sparkles className="size-3.5 text-ai" />
          AI 助手
        </h3>
        <div className="flex items-center gap-1">
          {generating ? (
            <Button size="xs" variant="destructive" onClick={handleStop}>
              停止
            </Button>
          ) : (
            <Button size="xs" variant="outline" onClick={handleGenerate}>
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

      <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
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
            // AI 气泡：淡紫底 + 紫色字 + 紫色左边框，是 AI 身份的视觉锚点
            <div key={i} className="flex justify-start">
              <div className="inline-block max-w-[90%] rounded-md border-l-2 border-ai bg-ai-muted px-3 py-2 text-[13px] text-foreground whitespace-pre-wrap">
                {m.content || '...'}
              </div>
            </div>
          ),
        )}
      </div>

      <div className="flex gap-2 border-t p-3">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) =>
            e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSend())
          }
          placeholder="问 AI..."
          disabled={loading}
          className="h-8 text-[13px]"
        />
        <Button size="sm" onClick={handleSend} disabled={loading || !input.trim()}>
          发送
        </Button>
      </div>
    </div>
  )
}
