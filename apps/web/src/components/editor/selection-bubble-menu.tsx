'use client'

import { Sparkles, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { getChatDefaultSource } from '@/lib/llm-source'
import { toast } from 'sonner'

interface SelectionBubbleMenuProps {
  sectionId: string
  /** 由 TiptapEditor 提供：实时读取选区文字 */
  getSelectionText: () => string
  /** 由 TiptapEditor 提供：实时读取选区视口坐标 */
  getSelectionCoords: () => { top: number; left: number; bottom: number } | null
  /** 流式重写完成（或停止）时回调，把 AI 输出 + 选中原文传回 page.tsx */
  onRewriteComplete: (aiOutput: string, selectedText: string) => void
}

type BubbleState = 'hidden' | 'ready' | 'prompting' | 'streaming'

export function SelectionBubbleMenu({
  sectionId, getSelectionText, getSelectionCoords, onRewriteComplete,
}: SelectionBubbleMenuProps) {
  const [state, setState] = useState<BubbleState>('hidden')
  const [coords, setCoords] = useState<{ top: number; left: number; bottom: number } | null>(null)
  const [instruction, setInstruction] = useState('')
  const [aiOutput, setAiOutput] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const selectedTextRef = useRef('')

  // 监听选区变化（轮询 ProseMirror selection，因为 onSelectionUpdate 在父组件配置）
  // 简化策略：用 setInterval 轮询选区状态（200ms 足够，避免高频）
  useEffect(() => {
    const tick = () => {
      const text = getSelectionText()
      const c = getSelectionCoords()
      if (text && c) {
        // 选区变化时更新坐标，但若正在 streaming 不打断
        if (state !== 'streaming') {
          setCoords(c)
          selectedTextRef.current = text
          setState((prev) => (prev === 'hidden' ? 'ready' : prev === 'ready' ? 'ready' : prev))
        }
      } else {
        // 选区清空：streaming 中保持（用户可能临时点了别处），其余态隐藏
        if (state !== 'streaming') {
          setState('hidden')
          setCoords(null)
        }
      }
    }
    const id = setInterval(tick, 200)
    return () => clearInterval(id)
  }, [getSelectionText, getSelectionCoords, state])

  // 滚动时清空坐标（让气泡暂时消失，下次 tick 重新定位）
  useEffect(() => {
    const onScroll = () => {
      if (state !== 'streaming') {
        const c = getSelectionCoords()
        setCoords(c)
        if (!c) setState('hidden')
      }
    }
    window.addEventListener('scroll', onScroll, true)
    return () => window.removeEventListener('scroll', onScroll, true)
  }, [getSelectionCoords, state])

  async function handleRewrite() {
    // source 为 null 走后端 fallback 链，不前端硬拦（同 ai-chat-panel）
    const source = getChatDefaultSource()
    const selectedText = selectedTextRef.current
    if (!selectedText) {
      toast.error('未选中文字')
      return
    }
    setState('streaming')
    setAiOutput('')
    abortRef.current = new AbortController()
    let output = ''
    try {
      await api.streamRewrite(
        sectionId,
        { selected_text: selectedText, instruction: instruction.trim() || undefined },
        (token) => {
          output += token
          setAiOutput(output)
        },
        abortRef.current.signal,
      )
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 用户停止：保留半截内容，继续走 diff
      } else {
        const e = err as { message?: string }
        toast.error(e?.message || '重写失败')
        setState('ready')
        return
      }
    }
    // 流式完成（含停止）：回调 + 隐藏
    onRewriteComplete(output, selectedText)
    setState('hidden')
    setInstruction('')
    setAiOutput('')
  }

  function handleStop() {
    abortRef.current?.abort()
  }

  function handleCollapse() {
    setState('ready')
    setInstruction('')
  }

  if (state === 'hidden' || !coords) return null

  // 定位：上方空间够就放上方，否则放下方
  const bubbleHeight = 200 // 估算（prompting/streaming 态）
  const showBelow = coords.top < bubbleHeight + 16
  const top = showBelow ? coords.bottom + 8 : coords.top - (state === 'ready' ? 44 : bubbleHeight) - 8
  const left = coords.left

  return (
    <div
      className="bubble-menu"
      style={{
        position: 'fixed',
        top: `${top}px`,
        left: `${left}px`,
        zIndex: 50,
      }}
    >
      {state === 'ready' && (
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5"
          onClick={() => setState('prompting')}
        >
          <Sparkles className="size-3.5" />
          AI 重写
        </Button>
      )}

      {state === 'prompting' && (
        <div className="flex flex-col gap-2 p-2" style={{ width: 320 }}>
          <textarea
            autoFocus
            placeholder="告诉 AI 怎么改..."
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') handleCollapse()
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleRewrite()
            }}
            style={{ minHeight: 60, resize: 'none' }}
            className="w-full rounded-md border border-black/[0.08] bg-white/80 px-2 py-1.5 text-sm outline-none"
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={handleCollapse}>
              取消
            </Button>
            <Button size="sm" onClick={handleRewrite} disabled={!instruction.trim()}>
              重写
            </Button>
          </div>
        </div>
      )}

      {state === 'streaming' && (
        <div className="flex flex-col gap-2 p-2" style={{ width: 360 }}>
          <div className="flex items-center justify-between">
            <span className="text-xs text-[#86868b]">AI 重写中...</span>
            <Button variant="ghost" size="icon-xs" onClick={handleStop}>
              <Square className="size-3" />
            </Button>
          </div>
          <div className="max-h-32 overflow-y-auto rounded-md bg-white/60 px-2 py-1.5 text-sm">
            {aiOutput || '（等待输出...）'}
          </div>
        </div>
      )}
    </div>
  )
}
