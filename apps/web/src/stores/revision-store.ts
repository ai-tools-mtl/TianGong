'use client'

import { create } from 'zustand'

import type { Section } from '@/types/api'

/** 修订任务来源（T2 spec §3.5.1）：仅用于确认卡片展示与 LLMCallLog 记账标注。 */
export type RevisionOrigin = 'review' | 'novelty' | 'terms'

export interface PendingRevision {
  /** 目标章节 key（Section.key，如 problem/solution） */
  sectionKey: string
  /** 修订指令（用户在确认卡片上勾选后发出） */
  directives: string[]
  origin: RevisionOrigin
}

interface RevisionState {
  /** 单值覆盖语义（spec D 一致约定）：新 launch 覆盖旧 pending，一次只持有一个任务 */
  pending: PendingRevision | null
  /** 顺序队列（一键修订）：pending 之外待处理的章节。apply-diff 成功后逐个推进
   * （advanceQueue 取队首成为 pending 并跳转），不并发——T2「候选稿必经人工 diff」
   * 的节奏保留，只是省去回报告页找下一章的点击。 */
  queue: PendingRevision[]
  /** 从报告页/新颖性页/术语面板发起修订：写入 pending 并跳转编辑器目标章节 */
  launch: (p: PendingRevision) => void
  /** 一键修订：首项进 pending（跳转由 launchRevisionQueue 处理），其余排队 */
  launchQueue: (items: PendingRevision[]) => void
  /** 推进：队首出队成为 pending，返回它；队列空返回 null（pending 置空） */
  advanceQueue: () => PendingRevision | null
  /** 编辑器挂载/切章时取走并清空（目标章节的 AIChatPanel 消费弹确认卡片） */
  consume: () => PendingRevision | null
  /** 待确认卡片（dogfood 2026-08-20：卡片原是 AIChatPanel 本地 state，?section=
   * 深链定位过程中面板重挂载/时序竞争会把已消费的 pending 弄丢——卡片永远不弹。
   * 提升到 store 跨重挂载存活，用户关闭/发起修订时清除。） */
  card: (PendingRevision & { checked: boolean[] }) | null
  /** 消费 pending 弹卡片（全选默认勾选） */
  setCard: (c: PendingRevision & { checked: boolean[] }) => void
  /** 用户关闭卡片 / 发起修订后清除 */
  clearCard: () => void
  /** 用户关闭确认卡片 / 丢弃滞留任务（只清当前，不动队列） */
  clear: () => void
  /** 取消批量修订的剩余队列（当前章照常进行） */
  clearQueue: () => void
}

export const useRevisionStore = create<RevisionState>((set, get) => ({
  pending: null,
  queue: [],
  launch: (p) => set({ pending: p }),
  launchQueue: (items) => {
    if (items.length === 0) return
    const [first, ...rest] = items
    set({ pending: first, queue: rest })
  },
  advanceQueue: () => {
    const [next, ...rest] = get().queue
    set({ pending: next ?? null, queue: rest })
    return next ?? null
  },
  consume: () => {
    const p = get().pending
    set({ pending: null })
    return p
  },
  card: null,
  setCard: (c) => set({ card: c }),
  clearCard: () => set({ card: null }),
  clear: () => set({ pending: null }),
  clearQueue: () => set({ queue: [] }),
}))

/**
 * 发起修订 + 跳转编辑器目标章节（各建议源页面的统一入口）。
 * 编辑器页会读取 ?section= query param 定位章节（读后清除，spec §3.5.1）。
 */
export function launchRevision(
  sections: Pick<Section, 'key'>[] | undefined,
  sectionKey: string,
  directives: string[],
  origin: RevisionOrigin,
  router: { push: (url: string) => void },
  projectId: string,
): boolean {
  // 边界 #17：章节不存在（模板变更/章节被删）不发起，提示由调用方处理
  if (sections && !sections.some((s) => s.key === sectionKey)) return false
  useRevisionStore.getState().launch({ sectionKey, directives, origin })
  router.push(`/projects/${projectId}?section=${encodeURIComponent(sectionKey)}`)
  return true
}

/**
 * 一键修订（顺序队列）：过滤失效章节后首项进 pending + 跳转，其余排队。
 * 返回实际发起的章节数（0 = 没有可修订章节，提示由调用方处理）。
 */
export function launchRevisionQueue(
  sections: Pick<Section, 'key'>[] | undefined,
  items: PendingRevision[],
  router: { push: (url: string) => void },
  projectId: string,
): number {
  const valid = sections
    ? items.filter((it) => sections.some((s) => s.key === it.sectionKey))
    : items
  if (valid.length === 0) return 0
  useRevisionStore.getState().launchQueue(valid)
  router.push(`/projects/${projectId}?section=${encodeURIComponent(valid[0].sectionKey)}`)
  return valid.length
}
