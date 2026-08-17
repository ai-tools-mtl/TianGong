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
  /** 从报告页/新颖性页/术语面板发起修订：写入 pending 并跳转编辑器目标章节 */
  launch: (p: PendingRevision) => void
  /** 编辑器挂载/切章时取走并清空（目标章节的 AIChatPanel 消费弹确认卡片） */
  consume: () => PendingRevision | null
  /** 用户关闭确认卡片 / 丢弃滞留任务 */
  clear: () => void
}

export const useRevisionStore = create<RevisionState>((set, get) => ({
  pending: null,
  launch: (p) => set({ pending: p }),
  consume: () => {
    const p = get().pending
    set({ pending: null })
    return p
  },
  clear: () => set({ pending: null }),
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
