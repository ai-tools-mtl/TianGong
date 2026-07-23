/**
 * 默认 LLM 源 localStorage 持久化（Task 4.0）。
 *
 * source 取值（与后端 resolve_llm_config 对齐）：
 * - "global"：全局 Key（须被 admin 授权）
 * - "custom:{config_id}"：用户自配的某条自定义配置
 *
 * 仅在浏览器侧读写（settings 页与 ai-chat-panel 均为 'use client'）。
 * 调用方需自行处理 SSR 场景（typeof window === 'undefined' 时这些函数返回 null）。
 */

const KEY = 'tg_default_llm_source'

/** 读默认 source；SSR 或未设置返回 null。 */
export function getDefaultSource(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(KEY)
}

/** 写默认 source。 */
export function setDefaultSource(source: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(KEY, source)
}

/** 清除默认 source（配置失效/撤销时调用）。 */
export function clearDefaultSource(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(KEY)
}
