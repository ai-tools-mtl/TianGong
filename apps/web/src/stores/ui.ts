import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UIState {
  /** 左栏（章节大纲）折叠态 */
  leftCollapsed: boolean
  /** 右栏（AI 对话）折叠态 */
  rightCollapsed: boolean
  toggleLeft: () => void
  toggleRight: () => void
  setLeftCollapsed: (v: boolean) => void
  setRightCollapsed: (v: boolean) => void
}

/**
 * 项目工作区三栏的折叠记忆。
 * 持久化到 localStorage，跨刷新/跨项目保持用户偏好。
 */
export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      leftCollapsed: false,
      rightCollapsed: false,
      toggleLeft: () => set((s) => ({ leftCollapsed: !s.leftCollapsed })),
      toggleRight: () => set((s) => ({ rightCollapsed: !s.rightCollapsed })),
      setLeftCollapsed: (v) => set({ leftCollapsed: v }),
      setRightCollapsed: (v) => set({ rightCollapsed: v }),
    }),
    { name: 'tiangong-ui' },
  ),
)
