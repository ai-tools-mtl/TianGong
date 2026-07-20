import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** 右栏宽度上下限（px）。用户可在此范围内拖拽调整。 */
const RIGHT_WIDTH_MIN = 320
const RIGHT_WIDTH_MAX = 720
/** 右栏默认宽度。AI 助手内容（消息气泡 + markdown 草稿 + 代码块）需要的最小可读宽度。 */
const RIGHT_WIDTH_DEFAULT = 480

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
 *
 * 版本 1：把右栏默认宽度从 360 提到 480、范围从 [280,600] 放宽到 [320,720]。
 * 老用户 localStorage 里仍是旧值，用 migrate 强制刷新到新默认（避免老值过窄）。
 */
export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      leftCollapsed: false,
      rightCollapsed: false,
      rightWidth: RIGHT_WIDTH_DEFAULT,
      toggleLeft: () => set((s) => ({ leftCollapsed: !s.leftCollapsed })),
      toggleRight: () => set((s) => ({ rightCollapsed: !s.rightCollapsed })),
      setLeftCollapsed: (v) => set({ leftCollapsed: v }),
      setRightCollapsed: (v) => set({ rightCollapsed: v }),
      setRightWidth: (w) =>
        set({ rightWidth: Math.min(Math.max(w, RIGHT_WIDTH_MIN), RIGHT_WIDTH_MAX) }),
    }),
    {
      name: 'tiangong-ui',
      version: 1,
      migrate: (persisted, version) => {
        // v0 → v1：右栏宽度从旧的 [280,600]/默认 360 切到新的 [320,720]/默认 480。
        // 老用户的 localStorage 里存的是 v0，强制覆盖到新默认（用户后续可自行拖拽）。
        const s = (persisted ?? {}) as Partial<UIState>
        if (version < 1) {
          s.rightWidth = RIGHT_WIDTH_DEFAULT
        }
        return s as UIState
      },
    },
  ),
)
