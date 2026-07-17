/**
 * 会话时间分组与格式化（纯函数，无副作用）。
 * Spec: docs/superpowers/specs/2026-07-17-conversation-list-grouping-design.md
 */

import type { Conversation } from '@/types/api'

export type TimeGroupKey = 'today' | 'yesterday' | 'thisWeek' | 'thisMonth' | 'earlier'

export const GROUP_LABELS: Record<TimeGroupKey, string> = {
  today: '今天',
  yesterday: '昨天',
  thisWeek: '本周',
  thisMonth: '本月',
  earlier: '更早',
}

/** 计算从 baseDate 零点起往前 n 天的零点 Date（本地时区）。n=0 是今天零点。 */
function daysAgoStart(baseDate: Date, n: number): Date {
  const d = new Date(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate(), 0, 0, 0, 0)
  d.setDate(d.getDate() - n)
  return d
}

/**
 * 判定给定日期属于哪个时间桶。以 now 为基准。
 * 边界（按本地时区当天零点）：
 *   today: 今天 00:00 ~ now
 *   yesterday: 昨天 00:00 ~ 今天 00:00
 *   thisWeek: 7 天前 00:00 ~ 昨天 00:00（含往前第 2~7 天）
 *   thisMonth: 30 天前 00:00 ~ 7 天前 00:00
 *   earlier: 30 天前 00:00 之前
 */
export function getTimeBucket(date: Date, now: Date = new Date()): TimeGroupKey {
  const t = date.getTime()
  if (Number.isNaN(t)) return 'earlier'

  const todayStart = daysAgoStart(now, 0)
  const yesterdayStart = daysAgoStart(now, 1)
  const weekStart = daysAgoStart(now, 7)
  const monthStart = daysAgoStart(now, 30)

  if (t >= todayStart.getTime()) return 'today'
  if (t >= yesterdayStart.getTime()) return 'yesterday'
  if (t >= weekStart.getTime()) return 'thisWeek'
  if (t >= monthStart.getTime()) return 'thisMonth'
  return 'earlier'
}

export interface ConversationGroup {
  key: TimeGroupKey
  label: string
  items: Conversation[]
}

const GROUP_ORDER: TimeGroupKey[] = ['today', 'yesterday', 'thisWeek', 'thisMonth', 'earlier']

/**
 * 把会话按 updated_at 分到 5 个时间桶。
 * 输入应已按 updated_at 倒序（后端 list_conversations 保证）；每组内保持原顺序。
 * 空桶不会出现在结果里。顺序固定为 today → earlier。
 */
export function groupConversations(conversations: Conversation[], now: Date = new Date()): ConversationGroup[] {
  const buckets: Record<TimeGroupKey, Conversation[]> = {
    today: [], yesterday: [], thisWeek: [], thisMonth: [], earlier: [],
  }
  for (const c of conversations) {
    const d = new Date(c.updated_at)
    buckets[getTimeBucket(d, now)].push(c)
  }
  return GROUP_ORDER
    .filter((k) => buckets[k].length > 0)
    .map((k) => ({ key: k, label: GROUP_LABELS[k], items: buckets[k] }))
}
