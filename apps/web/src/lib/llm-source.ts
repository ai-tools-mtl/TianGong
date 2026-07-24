/**
 * 默认 LLM 源 localStorage 持久化（feat/llm-chat-embedding-split：chat / embedding 双 key）。
 *
 * chat 与 embedding 各自独立记默认源，互不影响：
 * - chat 走 KEY_CHAT，取值：`"global"` / `"custom-chat:{config_id}"` / null
 * - embedding 走 KEY_EMB，取值：`"global"` / `"custom-emb:{config_id}"` / null
 *
 * `"global"`：使用全局 Key（chat 侧须被 admin 授权；后端 chat/embedding 各自查授权与全局配置）。
 * 仅在浏览器侧读写（settings 页与 ai-chat-panel 均为 'use client'）。
 * SSR 场景（typeof window === 'undefined'）下读函数返回 null、写函数 no-op。
 */

const KEY_CHAT = 'tg_default_chat_source'
const KEY_EMB = 'tg_default_embedding_source'

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

// ── Embedding 默认源 ──

/** 读 embedding 默认 source；SSR 或未设置返回 null。 */
export function getEmbeddingDefaultSource(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(KEY_EMB)
}

/** 写 embedding 默认 source。 */
export function setEmbeddingDefaultSource(source: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(KEY_EMB, source)
}

/** 清除 embedding 默认 source（embedding 配置失效/撤销时调用）。 */
export function clearEmbeddingDefaultSource(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(KEY_EMB)
}

/** embedding 当前默认是否为全局 Key。 */
export function isEmbeddingGlobalDefault(): boolean {
  return getEmbeddingDefaultSource() === 'global'
}

/** 设/取消「全局 Key 作为 embedding 默认」。set(true) → 'global'；set(false) 且当前是 global → 清空。 */
export function setEmbeddingGlobalDefault(value: boolean): void {
  if (value) {
    setEmbeddingDefaultSource('global')
  } else if (isEmbeddingGlobalDefault()) {
    clearEmbeddingDefaultSource()
  }
}
