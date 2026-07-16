import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UIState {
  /** 左栏（章节大纲）折叠态 */
  leftCollapsed: boolean
  /** 右栏（AI 对话）折叠态 */
  rightCollapsed: boolean
  /** 右栏宽度（px），可拖拽调整，持久化 */
  rightWidth: number
  toggleLeft: () => void
  toggleRight: () => void
  setLeftCollapsed: (v: boolean) => void
  setRightCollapsed: (v: boolean) => void
  setRightWidth: (w: number) => void
}

/**
 * 项目工作区三栏的折叠记忆 + 右栏宽度。
 * 持久化到 localStorage，跨刷新/跨项目保持用户偏好。
 */
export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      leftCollapsed: false,
      rightCollapsed: false,
      rightWidth: 360,
      toggleLeft: () => set((s) => ({ leftCollapsed: !s.leftCollapsed })),
      toggleRight: () => set((s) => ({ rightCollapsed: !s.rightCollapsed })),
      setLeftCollapsed: (v) => set({ leftCollapsed: v }),
      setRightCollapsed: (v) => set({ rightCollapsed: v }),
      setRightWidth: (w) => set({ rightWidth: Math.min(Math.max(w, 280), 600) }),
    }),
    { name: 'tiangong-ui' },
  ),
)
