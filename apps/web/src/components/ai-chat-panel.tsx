'use client'

import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface AIChatPanelProps {
  sectionId: string
}

export function AIChatPanel({ sectionId }: AIChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)

  async function handleSend() {
    if (!input.trim() || loading) return
    const userMsg: ChatMessage = { role: 'user', content: input }
    setMessages((m) => [...m, userMsg, { role: 'assistant', content: '' }])
    setInput('')
    setLoading(true)

    let aiText = ''
    try {
      await api.streamChat(sectionId, userMsg.content, (token) => {
        aiText += token
        setMessages((m) => {
          const copy = [...m]
          copy[copy.length - 1] = { role: 'assistant', content: aiText }
          return copy
        })
      })
    } catch {
      toast.error('AI 回复失败')
    } finally {
      setLoading(false)
    }
  }

  async function handleGenerate() {
    setGenerating(true)
    toast.info('正在生成草稿...')
    try {
      let md = ''
      await api.streamGenerate(sectionId, (token) => {
        md += token
      })
      toast.success('草稿已生成并填入编辑器')
      setTimeout(() => window.location.reload(), 500)
    } catch {
      toast.error('生成失败')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="flex h-full flex-col border-l pl-4" style={{ width: 320 }}>
      <div className="flex items-center justify-between pb-2">
        <h3 className="text-sm font-semibold">AI 助手</h3>
        <Button size="sm" variant="outline" onClick={handleGenerate} disabled={generating}>
          {generating ? '生成中...' : '生成草稿'}
        </Button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto py-2" style={{ maxHeight: '400px' }}>
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">向 AI 描述你的想法，或直接点「生成草稿」</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
            <div className={`inline-block max-w-[90%] rounded-lg px-3 py-2 text-sm ${
              m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
            }`}>
              {m.content || '...'}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-2 pt-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSend())}
          placeholder="问 AI..."
          disabled={loading}
        />
        <Button size="sm" onClick={handleSend} disabled={loading || !input.trim()}>
          发送
        </Button>
      </div>
    </div>
  )
}
