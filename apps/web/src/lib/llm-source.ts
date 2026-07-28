/**
 * 默认 LLM 源 localStorage 持久化（仅 chat）。
 *
 * embedding 已改走固定 bge-m3 微服务，不再有用户可选源，故只保留 chat 一套。
 * - chat 走 KEY_CHAT，取值：`"global"` / `"custom-chat:{config_id}"` / null
 *
 * `"global"`：使用全局 chat Key（须被 admin 授权）。
 * 仅在浏览器侧读写（settings 页与 ai-chat-panel 均为 'use client'）。
 * SSR 场景（typeof window === 'undefined'）下读函数返回 null、写函数 no-op。
 */

const KEY_CHAT = 'tg_default_chat_source'

// ── Chat 默认源 ──

/** 读 chat 默认 source；SSR 或未设置返回 null。 */
export function getChatDefaultSource(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(KEY_CHAT)
}

/** 写 chat 默认 source。 */
export function setChatDefaultSource(source: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(KEY_CHAT, source)
}

/** 清除 chat 默认 source（chat 配置失效/撤销时调用）。 */
export function clearChatDefaultSource(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(KEY_CHAT)
}

/** chat 当前默认是否为全局 Key。 */
export function isChatGlobalDefault(): boolean {
  return getChatDefaultSource() === 'global'
}

/** 设/取消「全局 Key 作为 chat 默认」。set(true) → 'global'；set(false) 且当前是 global → 清空。 */
export function setChatGlobalDefault(value: boolean): void {
  if (value) {
    setChatDefaultSource('global')
  } else if (isChatGlobalDefault()) {
    clearChatDefaultSource()
  }
}
