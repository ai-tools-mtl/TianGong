'use client'

import { GitCompare, Loader2, PanelRight, Sparkles, Square, Trash2, Wand2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { toast } from 'sonner'

import { AgentSteps } from '@/components/ai/agent-steps'
import { Markdown } from '@/components/markdown'
import { Button } from '@/components/ui/button'
import { ConversationList } from '@/components/conversation-list'
import { DiffReviewPanel } from '@/components/diff-review-panel'
import { api } from '@/lib/api'
import { clearChatDefaultSource, getChatDefaultSource } from '@/lib/llm-source'
import {
  queryKeys,
  useApplyDiff,
  useComputeDiff,
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useMessages,
  useRewriteDiff,
} from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useRevisionStore } from '@/stores/revision-store'
import type { PendingRevision } from '@/stores/revision-store'
import { useUIStore } from '@/stores/ui'
import type { Conversation, Hunk, MessageMeta, Section, ToolEvent } from '@/types/api'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  /** 消息 id（历史回灌 / interrupt 事件回传；resume 端点按它定位 partial 消息） */
  id?: string | null
  /** resume 锚点：该 turn 的 user 消息 id（= checkpoint thread_id 约定） */
  threadId?: string | null
  /** agent 透明化：本轮思考过程（流式累积 / 历史回灌） */
  thinking?: string
  /** agent 透明化：本轮工具调用事件序列（流式累积 / 历史回灌） */
  toolEvents?: ToolEvent[]
  /** 回复被中断（历史回灌）：后端兜底落了半截内容，非正常结束。 */
  incomplete?: boolean
  /** HITL 工具确认中断：agent 停在断点等用户同意/拒绝（resume 恢复）。 */
  interrupted?: boolean
  /** interrupted 时待确认的工具动作。 */
  pendingActions?: { name: string; args: Record<string, unknown>; description?: string }[]
}

/**
 * 判定错误是否为“LLM 源失效”（全局 Key 授权被撤销 / 选中的自定义配置被删）。
 *
 * streamChat/streamGenerate 在初始 POST !res.ok 时抛出的 Error 携带 .status
 * 与 .code（见 api.ts _sseHttpError）；后端 ForbiddenError 序列化为
 * {code:"forbidden", message:...}（HTTP 403）。这里三路兜底：status / code / message。
 */
function isForbiddenSourceError(err: unknown): boolean {
  if (!(err instanceof Error)) return false
  if ((err as { status?: number }).status === 403) return true
  if ((err as { code?: string }).code === 'forbidden') return true
  return /未授权|全局 Key|授权/.test(err.message)
}

/** 选定的 LLM 源失效：清默认源 + 引导用户去设置重选。 */
function handleStaleSourceError() {
  clearChatDefaultSource()
  toast.error('当前 LLM 源已失效（授权被撤销或配置已删除），已清除默认源，请前往「设置」重新选择')
}

export type AIPhase = 'idle' | 'chatting' | 'generating' | 'revising' | 'done' | 'diff-review'

/**
 * 当前 DiffReviewPanel 展示的 hunks 来自哪条路径——决定 apply 时该把什么当作
 * ai_text 回传给后端（apply-diff 后端按 (original, ai_text) 重算 hunks）。
 * - 'full'：整章生成草稿走 compute_diff；apply 时传 aiDraft（整章 markdown）。
 * - 'rewrite'：选区重写走 rewrite-diff；apply 时传 rewriteAiFull（注入后的整章），
 *   必须与计算时一致，否则 accepted_hunk_ids 对不上 → 数据损坏。
 */
type DiffOrigin = 'full' | 'rewrite'

interface AIChatPanelProps {
  sectionId: string
  /** 当前 section（用于读取 expected_version 做乐观锁） */
  section: Section
  /** 用于 apply-diff 成功后刷新章节缓存 */
  projectId: string
  /** apply-diff 成功并 refetch 后，用最新 content 重置编辑器（TiptapEditor 不响应 content prop 变化，
   *  需显式 resetContent 同步；否则 apply 后编辑器仍显示旧内容） */
  onAppliedContent?: (content: object) => void
}

/**
 * 对外暴露的 imperative 方法。
 * 选区重写气泡（SelectionBubbleMenu）挂在 page.tsx 的 <TiptapEditor> 里，
 * 但 diff 审核状态（phase/hunks/DiffReviewPanel）在 AIChatPanel 内部——
 * 通过 ref 让 page.tsx 把气泡回调桥接到本组件的 handleRewriteComplete。
 */
export interface AIChatPanelRef {
  handleRewriteComplete: (aiOutput: string, selectedText: string) => void
  /** 当前相位（连续文档视图忙碌锁用，spec 2026-08-18 §3.2）：非 idle 即进行中/待审 */
  getPhase: () => AIPhase
}

export const AIChatPanel = forwardRef<AIChatPanelRef, AIChatPanelProps>(
  function AIChatPanel({ sectionId, section, projectId, onAppliedContent }, ref) {
  const qc = useQueryClient()
  const router = useRouter()
  const toggleRight = useUIStore((s) => s.toggleRight)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [phase, setPhase] = useState<AIPhase>('idle')
  // phase 的 ref 镜像：getPhase 经 useImperativeHandle 对外读，闭包会过期，读 ref 才准。
  const phaseRef = useRef<AIPhase>('idle')
  const [aiDraft, setAiDraft] = useState('')
  // generate 场景的 agent 透明化状态（思考/工具），展示在草稿预览区上方
  const [genSteps, setGenSteps] = useState<{ thinking?: string; toolEvents?: ToolEvent[] }>({})
  const [hunks, setHunks] = useState<Hunk[]>([])
  // diff 审核的来源 + 选区重写路径专用的整章 ai 文本（apply 时必须原样回传）。
  const [diffOrigin, setDiffOrigin] = useState<DiffOrigin>('full')
  const [rewriteAiFull, setRewriteAiFull] = useState('')
  // T2 修订确认卡片：状态放 revision-store（跨重挂载存活——?section= 深链定位
  // 过程中本地 state 会随重挂载丢失，pending 已被消费则卡片永远不弹）。
  // 报告页/新颖性页/术语面板 launch 后跳转过来，目标章节匹配时消费 pending 弹卡片。
  const reviseCard = useRevisionStore((s) => s.card)
  const setReviseCard = useRevisionStore((s) => s.setCard)
  const clearReviseCard = useRevisionStore((s) => s.clearCard)
  // 一键修订队列剩余（确认卡片上展示进度 + 取消入口）
  const revisionQueue = useRevisionStore((s) => s.queue)
  const [currentConvId, setCurrentConvId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const msgLoadedForConv = useRef<string | null>(null)

  const computeDiff = useComputeDiff(sectionId)
  const applyDiff = useApplyDiff(sectionId, projectId)
  // 选区重写气泡触发的整章 diff（方案 B：后端代算拼接）。
  // 与 computeDiff 同走 setHunks/setPhase('diff-review') 落到 DiffReviewPanel，
  // 只是数据源换成 {selected_text, ai_text}（气泡的选区原文 + AI 重写文本）。
  const rewriteDiff = useRewriteDiff(sectionId)
  const { data: conversations, isLoading: convsLoading } = useConversations(sectionId)
  const createConv = useCreateConversation(sectionId)
  const deleteConv = useDeleteConversation(sectionId)
  // useMessages 在无 conversationId 时禁用（后端强制要求 conversation_id）
  const { data: history } = useMessages(sectionId, currentConvId ?? undefined)

  // 首次加载会话列表：自动选中最新（第一个）
  useEffect(() => {
    if (conversations && conversations.length > 0 && !currentConvId) {
      setCurrentConvId(conversations[0].id)
    }
  }, [conversations, currentConvId])

  // 会话变化时加载历史消息（currentConvId 为 null 时不加载，保持空白新会话态）
  useEffect(() => {
    if (!currentConvId) {
      // 草稿新会话：清空显示，等待首条消息
      msgLoadedForConv.current = null
      setMessages([])
      return
    }
    if (history && msgLoadedForConv.current !== currentConvId) {
      msgLoadedForConv.current = currentConvId
      // threadId 回灌：assistant 消息的 resume 锚点是它前面最近一条 user 消息的 id
      let lastUserId: string | null = null
      setMessages(
        history.map((m: { id: string; role: string; content: string; meta?: MessageMeta | null }) => {
          if (m.role === 'user') {
            lastUserId = m.id
            return { id: m.id, role: 'user' as const, content: m.content, threadId: null }
          }
          return {
            id: m.id,
            role: 'assistant' as const,
            content: m.content,
            threadId: lastUserId,
            // 历史回灌：从 Message.meta 恢复思考过程 + 工具调用（刷新后仍可见）
            thinking: m.meta?.thinking,
            toolEvents: m.meta?.tool_events,
            // 历史回灌：恢复中断标记（后端兜底落的半截回复）与 HITL 待确认动作
            incomplete: m.meta?.incomplete,
            interrupted: m.meta?.interrupted,
            pendingActions: m.meta?.pending_interrupt,
          }
        }),
      )
    }
  }, [history, currentConvId])

  // section 变化时重置
  useEffect(() => {
    setCurrentConvId(null)
    msgLoadedForConv.current = null
    setMessages([])
    setPhase('idle')
    setHunks([])
    setRewriteAiFull('')
    setDiffOrigin('full')
    // 不清 store 卡片：面板在 ?section 深链定位过程中会重挂载（sections 加载→current
    // 变化），重挂载的 reset 若清卡会把「已消费 pending 换来的卡片」永久丢掉
    // （pending 已 null，无法二次消费）。卡片归属改为渲染时按 sectionKey 匹配。
  }, [sectionId])

  // phase ref 同步（getPhase 经 imperative handle 对外读）
  useEffect(() => {
    phaseRef.current = phase
  }, [phase])

  // T2 修订任务消费（spec §3.5.2）：store 有 pending 且 sectionKey 匹配当前章节时
  // 取出弹确认卡片。不匹配则留在 store（page.tsx 顶部提示条引导切换章节）。
  const sectionKey = section.key
  useEffect(() => {
    const pending = useRevisionStore.getState().pending
    if (pending && pending.sectionKey === sectionKey) {
      const p = useRevisionStore.getState().consume()
      if (p) {
        setReviseCard({ ...p, checked: p.directives.map(() => true) })
      }
    }
  }, [sectionKey])

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
    // 切会话前 abort 在途的流式请求，避免旧会话的 token 回调污染新会话的 messages（丢对话根因）。
    abortRef.current?.abort()
    msgLoadedForConv.current = null
    setCurrentConvId(convId)
    setMessages([])
    setPhase('idle')
  }

  function handleNewConversation() {
    // 立即建草稿会话（后端 status=draft），列表可见、有反馈。
    // 首条对话完成后，后端同步总结标题并转 active。
    // 切会话前 abort（同上）。
    abortRef.current?.abort()
    msgLoadedForConv.current = null
    setMessages([])
    setPhase('idle')
    createConv.mutate(undefined, {
      onSuccess: (conv: Conversation) => {
        setCurrentConvId(conv.id)
      },
      onError: () => {
        toast.error('创建会话失败')
      },
    })
  }

  function handleDeleteConversation(convId: string) {
    // 删除当前会话会触发显示清空（等同切会话），先 abort 在途请求。
    if (convId === currentConvId) abortRef.current?.abort()
    deleteConv.mutate(convId, {
      onSuccess: () => {
        // 删除的是当前会话才清空显示
        if (convId === currentConvId) {
          msgLoadedForConv.current = null
          setCurrentConvId(null)
          setMessages([])
          setPhase('idle')
        }
        toast.success('会话已删除')
      },
    })
  }

  async function handleSend() {
    if (!input.trim() || phase === 'chatting' || phase === 'generating') return
    const source = getChatDefaultSource()
    if (!source) {
      toast.error('请先在设置中选择 LLM 源')
      return
    }
    // currentConvId 为空也放行：后端 streamChat 会兜底建会话，
    // 并在 done 事件回传真实 conversation_id（见下方 onDone 回填）。
    // 全新 section 列表为 []、自动选中 effect 不触发时，靠这条路首条对话即可建会话。
    const userMsg: ChatMessage = { role: 'user', content: input }
    setMessages((m) => [...m, userMsg, { role: 'assistant', content: '' }])
    setInput('')
    setPhase('chatting')
    abortRef.current = new AbortController()

    let aiText = ''
    // agent 透明化累积器（流式期间逐事件累加，合并进最后一条 assistant 消息）
    let aiThinking = ''
    const aiToolEvents: ToolEvent[] = []
    /** 把累积的 thinking/toolEvents 合并进最后一条 assistant 消息。 */
    const mergeAgentState = () => {
      setMessages((m) => {
        const copy = [...m]
        const last = copy[copy.length - 1]
        if (last && last.role === 'assistant') {
          copy[copy.length - 1] = {
            ...last,
            thinking: aiThinking || undefined,
            toolEvents: aiToolEvents.length ? [...aiToolEvents] : undefined,
          }
        }
        return copy
      })
    }
    try {
      await api.streamChat(
        sectionId,
        userMsg.content,
        (token) => {
          aiText += token
          setMessages((m) => {
            const copy = [...m]
            const last = copy[copy.length - 1]
            // 保留已累积的 thinking/toolEvents（思考阶段写入），仅更新 content。
            // 此前用 { role, content } 全新对象替换会丢掉 agent 透明化字段。
            copy[copy.length - 1] = { ...last, role: 'assistant', content: aiText }
            return copy
          })
        },
        abortRef.current.signal,
        source,
        currentConvId ?? undefined,
        (doneData) => {
          // done 事件：后端兜底新建会话时回传 conversation_id（currentConvId 为空的场景），
          // 这里回填 + 刷新会话列表，避免后续每条消息各建一个新会话。
          if (doneData.conversation_id && doneData.conversation_id !== currentConvId) {
            setCurrentConvId(doneData.conversation_id)
          }
          qc.invalidateQueries({ queryKey: ['conversations', sectionId] })
        },
        {
          onThinking: (t) => { aiThinking += t; mergeAgentState() },
          onToolCall: (e) => { aiToolEvents.push({ kind: 'call', name: e.name, args: e.args }); mergeAgentState() },
          onToolResult: (e) => { aiToolEvents.push({ kind: 'result', name: e.name, result: e.result }); mergeAgentState() },
          // HITL 工具确认：流到此结束（无 done）。把断点信息挂到流式中的 assistant
          // 消息上（message_id 由后端落 partial 后回传），渲染确认卡片等用户决策。
          onInterrupt: (e) => {
            setMessages((m) => {
              const copy = [...m]
              const last = copy[copy.length - 1]
              if (last && last.role === 'assistant') {
                copy[copy.length - 1] = {
                  ...last,
                  id: e.message_id ?? last.id,
                  threadId: e.thread_id,
                  interrupted: true,
                  pendingActions: e.actions,
                }
              }
              return copy
            })
          },
        },
      )
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 用户主动停止：保留已生成的半截内容，不弹错
      } else if (isForbiddenSourceError(err)) {
        // LLM 源失效（全局 Key 授权被撤销 / 自定义配置被删）：清默认源 + 引导重选
        handleStaleSourceError()
        setMessages((m) => {
          const last = m[m.length - 1]
          if (last && last.role === 'assistant' && !last.content) {
            return m.slice(0, -1)
          }
          return m
        })
      } else {
        // SSE error 事件抛出的 ApiError 带 message；其它异常降级提示
        const e = err as { message?: string }
        toast.error(e?.message || 'AI 回复失败')
        // 移除空的 assistant 占位（若有）
        setMessages((m) => {
          const last = m[m.length - 1]
          if (last && last.role === 'assistant' && !last.content) {
            return m.slice(0, -1)
          }
          return m
        })
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

  /**
   * 续跑（Checkpoint 断点恢复）：
   * - 崩溃/断连的半截回复：无 decision，后端 input=None 从 checkpoint 续跑；
   * - HITL 工具确认：decision=approve/reject，后端 Command(resume=...) 恢复。
   * token 续接在目标消息上；done 带权威全文整体替换（中断节点整段重放，
   * 本地拼接会有重复前缀）。
   */
  async function handleResume(target: ChatMessage, decision?: 'approve' | 'reject') {
    if (!target.id || !target.threadId) {
      toast.error('缺少续跑锚点，请刷新页面后重试')
      return
    }
    const source = getChatDefaultSource()
    if (!source) {
      toast.error('请先在设置中选择 LLM 源')
      return
    }
    const targetId = target.id
    setPhase('chatting')
    abortRef.current = new AbortController()
    // 思考/工具事件续接在该消息上（从 partial 已有内容继续累积）
    let thinking = target.thinking ?? ''
    const toolEvents: ToolEvent[] = [...(target.toolEvents ?? [])]
    const patchMsg = (patch: Partial<ChatMessage>) => {
      setMessages((m) => m.map((msg) => (msg.id === targetId ? { ...msg, ...patch } : msg)))
    }
    try {
      await api.streamResume(
        sectionId,
        targetId,
        {
          thread_id: target.threadId,
          ...(decision ? { decision } : {}),
          chat_source: source,
        },
        (token) => {
          setMessages((m) =>
            m.map((msg) => (msg.id === targetId ? { ...msg, content: msg.content + token } : msg)),
          )
        },
        abortRef.current.signal,
        (doneData) => {
          // 权威全文替换：清除 incomplete/interrupted/待确认标记
          if (typeof doneData.content === 'string') {
            patchMsg({
              content: doneData.content,
              incomplete: false,
              interrupted: false,
              pendingActions: undefined,
            })
          }
          if (doneData.conversation_id && doneData.conversation_id !== currentConvId) {
            setCurrentConvId(doneData.conversation_id)
          }
          qc.invalidateQueries({ queryKey: ['conversations', sectionId] })
        },
        {
          onThinking: (t) => { thinking += t; patchMsg({ thinking }) },
          onToolCall: (e) => { toolEvents.push({ kind: 'call', name: e.name, args: e.args }); patchMsg({ toolEvents: [...toolEvents] }) },
          onToolResult: (e) => { toolEvents.push({ kind: 'result', name: e.name, result: e.result }); patchMsg({ toolEvents: [...toolEvents] }) },
          // 链式确认：续跑中再次停在工具断点，更新断点信息继续等决策
          onInterrupt: (e) => {
            patchMsg({
              interrupted: true,
              pendingActions: e.actions,
              id: e.message_id ?? targetId,
              threadId: e.thread_id || target.threadId,
            })
          },
        },
      )
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 主动停止：保留内容；后端同款落 incomplete
        patchMsg({ incomplete: true, interrupted: false, pendingActions: undefined })
      } else if (isForbiddenSourceError(err)) {
        handleStaleSourceError()
      } else {
        const e = err as { message?: string }
        toast.error(e?.message || '续跑失败')
      }
    } finally {
      setPhase('idle')
    }
  }

  function handleClearChat() {
    setMessages([])
    setPhase('idle')
    msgLoadedForConv.current = '__force__'
    toast.info('已清空当前显示')
  }

  async function handleGenerate() {
    const source = getChatDefaultSource()
    if (!source) {
      toast.error('请先在设置中选择 LLM 源')
      return
    }
    setPhase('generating')
    setAiDraft('')
    abortRef.current = new AbortController()
    let md = ''
    // generate 场景同样透传 agent 透明化事件（思考/工具），用于生成预览区展示
    let genThinking = ''
    const genToolEvents: ToolEvent[] = []
    setGenSteps({ thinking: '', toolEvents: [] })
    try {
      await api.streamGenerate(
        sectionId,
        (token) => {
          md += token
          setAiDraft(md)
        },
        abortRef.current.signal,
        source,
        {
          onThinking: (t) => { genThinking += t; setGenSteps({ thinking: genThinking, toolEvents: [...genToolEvents] }) },
          onToolCall: (e) => { genToolEvents.push({ kind: 'call', name: e.name, args: e.args }); setGenSteps({ thinking: genThinking, toolEvents: [...genToolEvents] }) },
          onToolResult: (e) => { genToolEvents.push({ kind: 'result', name: e.name, result: e.result }); setGenSteps({ thinking: genThinking, toolEvents: [...genToolEvents] }) },
        },
      )
      setPhase('done')
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 已有部分内容则进 done 态供审查；否则回 idle
        setPhase(md ? 'done' : 'idle')
      } else if (isForbiddenSourceError(err)) {
        // LLM 源失效：清默认源 + 引导重选
        handleStaleSourceError()
        setPhase('idle')
      } else {
        const e = err as { message?: string }
        toast.error(e?.message || '生成失败')
        setPhase('idle')
      }
    }
  }

  // T2 修订流（spec §3.5.2）：确认卡片勾选 directives → streamRevise 流式渲染
  // （复用 generating 的预览样式与 AgentSteps）→ done 的权威全文替换本地拼接
  // → 自动进 diff 审核（diffOrigin='full'，复用 generate 的「审查差异」链路）。
  async function handleStartRevise(card: PendingRevision & { checked: boolean[] }) {
    const source = getChatDefaultSource()
    if (!source) {
      toast.error('请先在设置中选择 LLM 源')
      return
    }
    // 超 500 字的 directive 截断（后端 422，前端先截+提示，spec 边界 #2）
    const directives = card.directives
      .filter((_, i) => card.checked[i])
      .map((d) => {
        if (d.length > 500) {
          toast.info('部分修订指令过长，已截断至 500 字')
          return d.slice(0, 500)
        }
        return d
      })
    if (directives.length === 0) {
      toast.error('请至少勾选一条修订建议')
      return
    }
    clearReviseCard() // 单飞：revising 中不显示卡片（spec 边界 #16）
    setPhase('revising')
    setAiDraft('')
    abortRef.current = new AbortController()
    let md = ''
    let revThinking = ''
    const revToolEvents: ToolEvent[] = []
    setGenSteps({ thinking: '', toolEvents: [] })
    try {
      await api.streamRevise(
        sectionId,
        { directives, origin: card.origin, chat_source: source },
        (token) => {
          md += token
          setAiDraft(md)
        },
        abortRef.current.signal,
        {
          onThinking: (t) => { revThinking += t; setGenSteps({ thinking: revThinking, toolEvents: [...revToolEvents] }) },
          onToolCall: (e) => { revToolEvents.push({ kind: 'call', name: e.name, args: e.args }); setGenSteps({ thinking: revThinking, toolEvents: [...revToolEvents] }) },
          onToolResult: (e) => { revToolEvents.push({ kind: 'result', name: e.name, result: e.result }); setGenSteps({ thinking: revThinking, toolEvents: [...revToolEvents] }) },
        },
        (done) => {
          // done.content 为后端权威全文（spec §3.1.1）：整体替换本地拼接缓冲
          if (done?.content) {
            md = done.content
            setAiDraft(done.content)
          }
        },
      )
      // 候选稿产出 → 直接进人工 diff 审核（spec D8：不提供跳过审核的路径）
      await handleOpenDiff(md)
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 中断：丢弃缓冲，恢复确认卡片可重新发起（spec 边界 #3）
        setAiDraft('')
        setPhase('idle')
        setReviseCard(card) // 恢复原卡片（含勾选），可重新发起（spec 边界 #3）
      } else if (isForbiddenSourceError(err)) {
        handleStaleSourceError()
        setPhase('idle')
      } else {
        const e = err as { message?: string }
        toast.error(e?.message || '修订失败')
        setPhase('idle')
      }
    }
  }

  async function handleOpenDiff(explicitText?: string) {
    // explicitText：revising 流程在 done 回调里拿到权威全文后立即审查——
    // 此时 setAiDraft 尚未反映到本闭包（React state 异步），须显式传入。
    const text = explicitText ?? aiDraft
    if (!text.trim()) {
      toast.error('没有可审查的内容')
      return
    }
    setPhase('diff-review')
    setDiffOrigin('full')
    try {
      const res = await computeDiff.mutateAsync(text)
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

  // 一键修订队列推进：本章 diff 应用后进入下一章。失效章节（模板变更/被删）
  // 自动跳过继续取；队列空则无事发生（普通单章修订路径不受影响）。
  function proceedQueue() {
    let next = useRevisionStore.getState().advanceQueue()
    while (next) {
      const secs = qc.getQueryData<Section[]>(queryKeys.sections(projectId)) ?? []
      const target = secs.find((s) => s.key === next!.sectionKey)
      if (target) {
        const remaining = useRevisionStore.getState().queue.length
        toast.success(
          `已进入下一章修订：${target.title}${remaining > 0 ? `（剩余 ${remaining} 章）` : '（最后一章）'}`,
        )
        // 编辑器页深链 effect 只在挂载时读一次 URL，已挂载状态下的 push 不会触发
        // 章节切换——用事件即时通知；router.push 保留（刷新/直开场景仍走深链）。
        window.dispatchEvent(new CustomEvent('tiangong:goto-section', { detail: next.sectionKey }))
        router.push(`/projects/${projectId}?section=${encodeURIComponent(next.sectionKey)}`)
        return
      }
      next = useRevisionStore.getState().advanceQueue()
    }
  }

  async function handleApplyDiff(acceptedHunkIds: string[]) {
    if (acceptedHunkIds.length === 0) {
      toast.info('未选择任何变更')
      return
    }
    // apply 的 ai_text 必须与计算 diff 时一致（后端按 (original, ai_text) 重算 hunks）：
    // - 整章路径：aiDraft（整章 markdown 草稿）
    // - 选区重写路径：rewriteAiFull（首次出现被 ai_text 替换后的整章，由 rewrite-diff 回传）
    const applyAiText = diffOrigin === 'rewrite' ? rewriteAiFull : aiDraft
    try {
      const updated = await applyDiff.mutateAsync({
        ai_text: applyAiText,
        accepted_hunk_ids: acceptedHunkIds,
        expected_version: section.version,
      })
      toast.success(`已应用 ${acceptedHunkIds.length} 项更改`)
      setPhase('idle')
      setAiDraft('')
      setHunks([])
      setRewriteAiFull('')
      // 立即用响应里的新 content 重置编辑器（不等 refetch，避免编辑器显示滞后）。
      // emitUpdate:false 的 resetContent 不会触发 onChange→save 回环。
      if (updated?.content) {
        onAppliedContent?.(updated.content)
      }
      await qc.invalidateQueries({ queryKey: queryKeys.sections(projectId) })
      // 一键修订队列：本章应用完成，自动进入下一章（人工 diff 审核节奏不变）
      proceedQueue()
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
    // 关闭回到哪个阶段按来源区分：整章路径回 done（保留草稿供重新审查），
    // 选区重写路径回 idle（气泡是临时入口，无草稿态可回）。
    setPhase(diffOrigin === 'rewrite' ? 'idle' : 'done')
    setHunks([])
    setRewriteAiFull('')
  }

  // 选区重写气泡（SelectionBubbleMenu）流式完成后回调：复用已有的 diff 审核
  // 流程——气泡只是给 setHunks + setPhase('diff-review') 提供"选区重写"这条
  // 新数据源，DiffReviewPanel 零改动复用（spec §3.3）。apply 步骤按 diffOrigin
  // 分支（见 handleApplyDiff）传 rewriteAiFull 作为 ai_text。
  async function handleRewriteComplete(aiOutput: string, selectedText: string) {
    setPhase('diff-review')
    setDiffOrigin('rewrite')
    try {
      const res = await rewriteDiff.mutateAsync({
        selected_text: selectedText,
        ai_text: aiOutput,
      })
      setHunks(res.hunks)
      // 缓存 ai_full：apply-diff 时必须把它作为 ai_text 原样回传，
      // 后端按 (original, ai_text) 重算的 hunks 才与计算时生成的 id 对齐。
      setRewriteAiFull(res.ai_full ?? '')
      if (res.hunks.length === 0) {
        toast.info('AI 输出与原文无差异')
        setPhase('idle')
      }
    } catch (err: unknown) {
      const e = err as { code?: string; message?: string }
      toast.error(e?.message || '差异计算失败')
      setPhase('idle')
    }
  }

  // 把 handleRewriteComplete 暴露给 page.tsx——气泡在 page.tsx 的 <TiptapEditor>
  // 内触发 onRewriteComplete，page.tsx 通过 aiChatRef.current.handleRewriteComplete
  // 桥接到本组件，从而驱动本组件的 phase/hunks/DiffReviewPanel。
  // getPhase 供连续文档视图的 AI 忙碌锁读取（spec 2026-08-18 §3.2）。
  useImperativeHandle(ref, () => ({
    handleRewriteComplete,
    getPhase: () => phaseRef.current,
  }))


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

  const busy = phase === 'chatting' || phase === 'generating' || phase === 'revising'

  return (
    <div className={cn('flex min-h-0 w-full flex-1 flex-col', (phase === 'generating' || phase === 'revising') && 'ai-generating')}>
      {/* 标题栏 */}
      <div className="flex h-10 shrink-0 items-center justify-between gap-1 border-b px-2">
        <h3 className="flex items-center gap-1.5 px-1 text-[13px] font-semibold">
          <Sparkles className={cn('size-3.5 text-ai', convsLoading && 'animate-pulse')} />
          AI 助手
        </h3>
        <div className="flex items-center gap-0.5">
          {messages.length > 0 && phase !== 'generating' && phase !== 'revising' && phase !== 'done' && (
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
          {phase === 'generating' || phase === 'revising' ? (
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
      {phase !== 'generating' && phase !== 'revising' && phase !== 'done' && (
        <ConversationList
          conversations={conversations ?? []}
          currentConvId={currentConvId}
          loading={convsLoading}
          createPending={createConv.isPending}
          deletePending={deleteConv.isPending}
          onSelect={handleSelectConversation}
          onNew={handleNewConversation}
          onDelete={handleDeleteConversation}
        />
      )}

      {/* 内容区 */}
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3">
        {/* 卡片归属匹配当前章节（store 卡片跨重挂载存活，切章后旧章节卡片不在此显示） */}
        {reviseCard && reviseCard.sectionKey === section.key && (
          // T2 修订确认卡片（spec §3.5.2）：顶部卡片而非聊天消息——修订不是对话行为。
          // 勾选将要应用的 directives（用户可见可控，D3），可关闭丢弃。
          <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2.5 dark:border-amber-700/50 dark:bg-amber-950/30">
            <div className="flex items-center justify-between">
              <h4 className="flex items-center gap-1.5 text-[13px] font-semibold">
                <Wand2 className="size-3.5 text-amber-600 dark:text-amber-400" />
                AI 修订本章
                <span className="text-[11px] font-normal text-muted-foreground">
                  （来源：
                  {reviseCard.origin === 'review' ? '审查报告' : reviseCard.origin === 'novelty' ? '新颖性评估' : '术语检查'}）
                </span>
              </h4>
              <Button variant="ghost" size="icon-xs" aria-label="放弃修订" onClick={() => clearReviseCard()}>
                ×
              </Button>
            </div>
            <div className="mt-1.5 space-y-1">
              {reviseCard.directives.map((d, i) => (
                <label key={i} className="flex cursor-pointer items-start gap-1.5 text-xs leading-relaxed">
                  <input
                    type="checkbox"
                    checked={reviseCard.checked[i]}
                    onChange={() => {
                      const cur = useRevisionStore.getState().card
                      if (!cur) return
                      setReviseCard({ ...cur, checked: cur.checked.map((v, j) => (j === i ? !v : v)) })
                    }}
                    className="mt-0.5 size-3.5 shrink-0 accent-amber-600"
                  />
                  <span className={cn('text-ellipsis', reviseCard.checked[i] ? '' : 'text-muted-foreground line-through')}>
                    {d.length > 500 ? `${d.slice(0, 500)}…` : d}
                  </span>
                </label>
              ))}
            </div>
            <Button
              size="sm"
              className="mt-2 gap-1.5"
              disabled={!reviseCard.checked.some(Boolean)}
              onClick={() => handleStartRevise(reviseCard)}
            >
              <Wand2 className="size-3.5" />
              开始修订
            </Button>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              修订产出经差异审核后应用，未勾选的部分不会改动。
            </p>
            {revisionQueue.length > 0 && (
              <div className="mt-1.5 flex items-center justify-between text-[11px] text-muted-foreground">
                <span>批量修订：本章之后还有 {revisionQueue.length} 章待修</span>
                <button
                  className="underline underline-offset-2 hover:text-foreground"
                  onClick={() => {
                    useRevisionStore.getState().clearQueue()
                    toast.info('已取消剩余章节的批量修订')
                  }}
                >
                  取消剩余
                </button>
              </div>
            )}
          </div>
        )}
        {/* 批量修订队列滞留条：用户关闭确认卡片 / 放弃本章后，剩余章节仍可手动继续 */}
        {!reviseCard && revisionQueue.length > 0 && (
          <div className="flex items-center justify-between rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-[12px] dark:border-amber-700/50 dark:bg-amber-950/30">
            <span className="text-amber-900 dark:text-amber-200">
              批量修订队列中还有 {revisionQueue.length} 章待修
            </span>
            <span className="flex items-center gap-2">
              <Button variant="outline" size="sm" className="h-6 gap-1 px-2 text-[11px]" onClick={proceedQueue}>
                继续下一章
              </Button>
              <button
                className="text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
                onClick={() => {
                  useRevisionStore.getState().clearQueue()
                  toast.info('已取消剩余章节的批量修订')
                }}
              >
                取消
              </button>
            </span>
          </div>
        )}
        {phase === 'generating' || phase === 'revising' || phase === 'done' ? (
          // 生成草稿 / 修订的 markdown 预览
          <div className="space-y-3">
            <div className="rounded-lg border border-ai/20 bg-ai-muted/50 px-3 py-2.5">
              {/* agent 透明化：生成/修订阶段的思考过程 + 工具调用 */}
              <AgentSteps
                thinking={genSteps.thinking}
                toolEvents={genSteps.toolEvents}
                streaming={(phase === 'generating' || phase === 'revising') && !aiDraft}
              />
              {(phase === 'generating' || phase === 'revising') && !genSteps.thinking && !genSteps.toolEvents?.length && !aiDraft && (
                <div className="mb-2 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span className="flex gap-0.5">
                    <span className="size-1.5 animate-bounce rounded-full bg-ai [animation-delay:0ms]" />
                    <span className="size-1.5 animate-bounce rounded-full bg-ai [animation-delay:150ms]" />
                    <span className="size-1.5 animate-bounce rounded-full bg-ai [animation-delay:300ms]" />
                  </span>
                  {phase === 'revising' ? 'AI 正在按建议修订...' : 'AI 正在生成...'}
                </div>
              )}
              <Markdown className="prose prose-sm max-w-none dark:prose-invert">
                {aiDraft || '（空）'}
              </Markdown>
            </div>
            {phase === 'done' && (
              <div className="flex items-center gap-2">
                <Button size="sm" onClick={() => handleOpenDiff()} disabled={computeDiff.isPending} className="gap-1.5">
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
                  <div className="w-full whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-[13px] leading-relaxed text-primary-foreground">
                    {m.content}
                  </div>
                </div>
              ) : (
                <div key={i} className="flex justify-start">
                  <div className="w-full rounded-2xl rounded-bl-sm border border-ai/20 bg-ai-muted/40 px-3 py-2 text-[13px] leading-relaxed text-foreground">
                    {/* agent 透明化：思考过程 + 工具调用（正文之前；流式时 streaming=true） */}
                    <AgentSteps
                      thinking={m.thinking}
                      toolEvents={m.toolEvents}
                      streaming={phase === 'chatting' && i === messages.length - 1 && !m.content}
                    />
                    {m.content ? (
                      <>
                        <Markdown className="prose prose-sm max-w-none dark:prose-invert">
                          {m.content}
                        </Markdown>
                        {/* 中断标记：后端兜底落的半截回复（切会话/断连/异常），提示非正常结束。
                            有锚点（历史回灌带 id/threadId）时提供「继续」走 checkpoint 续跑 */}
                        {m.incomplete && (
                          <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted-foreground/70">
                            <span className="flex items-center gap-1">
                              <span className="inline-block size-1.5 rounded-full bg-muted-foreground/40" />
                              回复已中断
                            </span>
                            {m.id && m.threadId && phase !== 'chatting' && (
                              <Button
                                size="xs"
                                variant="outline"
                                className="h-5 px-1.5 text-[11px]"
                                onClick={() => handleResume(m)}
                              >
                                继续
                              </Button>
                            )}
                          </div>
                        )}
                      </>
                    ) : !m.thinking && !m.toolEvents?.length ? (
                      <span className="flex items-center gap-1 text-muted-foreground">
                        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:0ms]" />
                        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:150ms]" />
                        <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground/50 [animation-delay:300ms]" />
                      </span>
                    ) : null}
                    {/* HITL 工具确认卡片：agent 停在断点等同意/拒绝（如 generate_figure） */}
                    {m.interrupted && m.pendingActions && m.pendingActions.length > 0 && (
                      <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-2.5 py-2">
                        <div className="text-[11px] font-medium text-amber-600 dark:text-amber-400">
                          AI 请求执行以下工具，等待确认
                        </div>
                        {m.pendingActions.map((a, ai) => (
                          <div key={ai} className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
                            {a.name}
                            {a.args && Object.keys(a.args).length > 0 && (
                              <span className="ml-1">{JSON.stringify(a.args)}</span>
                            )}
                          </div>
                        ))}
                        {phase !== 'chatting' && (
                          <div className="mt-2 flex gap-2">
                            <Button size="xs" onClick={() => handleResume(m, 'approve')}>
                              同意执行
                            </Button>
                            <Button size="xs" variant="outline" onClick={() => handleResume(m, 'reject')}>
                              拒绝
                            </Button>
                          </div>
                        )}
                      </div>
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
              className="flex-1 resize-none rounded-xl border bg-background px-3 py-2 text-[13px] leading-relaxed outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              style={{ minHeight: '36px', maxHeight: '120px' }}
            />
            {phase === 'chatting' ? (
              <Button
                size="sm"
                variant="destructive"
                onClick={handleStop}
                className="shrink-0 gap-1.5"
                title="停止生成"
              >
                <Square className="size-3 fill-current" />
                停止
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={handleSend}
                disabled={busy || !input.trim()}
                className="shrink-0"
              >
                发送
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  )
  },
)
