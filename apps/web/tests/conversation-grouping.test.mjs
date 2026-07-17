// 会话时间分组纯函数测试（Node 原生 node:test，零依赖）
// 注意 JS Date 的 month 是 0-indexed：2026-07-17 → new Date(2026, 6, 17)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getTimeBucket } from '../src/lib/conversation-grouping.ts'

// 固定基准时刻：2026-07-17（周五）15:00 本地时区
const FIXED_NOW = new Date(2026, 6, 17, 15, 0)

test('今天的会话归 today', () => {
  assert.equal(getTimeBucket(new Date(2026, 6, 17, 14, 30), FIXED_NOW), 'today')
  assert.equal(getTimeBucket(new Date(2026, 6, 17, 0, 0), FIXED_NOW), 'today')
})

test('昨天归 yesterday', () => {
  assert.equal(getTimeBucket(new Date(2026, 6, 16, 23, 59), FIXED_NOW), 'yesterday')
  assert.equal(getTimeBucket(new Date(2026, 6, 16, 0, 0), FIXED_NOW), 'yesterday')
})

test('2~7 天前归 thisWeek', () => {
  assert.equal(getTimeBucket(new Date(2026, 6, 15, 10, 0), FIXED_NOW), 'thisWeek') // 2 天前
  assert.equal(getTimeBucket(new Date(2026, 6, 10, 10, 0), FIXED_NOW), 'thisWeek') // 7 天前
})

test('8~30 天前归 thisMonth', () => {
  assert.equal(getTimeBucket(new Date(2026, 6, 9, 10, 0), FIXED_NOW), 'thisMonth') // 8 天前
  assert.equal(getTimeBucket(new Date(2026, 5, 17, 10, 0), FIXED_NOW), 'thisMonth') // 30 天前
})

test('超过 30 天归 earlier', () => {
  assert.equal(getTimeBucket(new Date(2026, 5, 16, 10, 0), FIXED_NOW), 'earlier') // 31 天前
})

test('非法日期归 earlier', () => {
  assert.equal(getTimeBucket(new Date('invalid'), FIXED_NOW), 'earlier')
})

import { groupConversations } from '../src/lib/conversation-grouping.ts'

const conv = (id, updatedIso) => ({ id, title: 't' + id, created_at: updatedIso, updated_at: updatedIso })

test('groupConversations 按桶分组并保留倒序', () => {
  const convs = [
    conv('1', '2026-07-17T14:30:00'),  // today
    conv('2', '2026-07-16T10:00:00'),  // yesterday
    conv('3', '2026-07-15T10:00:00'),  // thisWeek
    conv('4', '2026-07-17T09:00:00'),  // today
  ]
  const grouped = groupConversations(convs, FIXED_NOW)
  assert.equal(grouped[0].key, 'today')
  assert.deepEqual(grouped[0].items.map(c => c.id), ['1', '4'])
  assert.equal(grouped[1].key, 'yesterday')
  assert.deepEqual(grouped[1].items.map(c => c.id), ['2'])
  assert.equal(grouped[2].key, 'thisWeek')
  assert.deepEqual(grouped[2].items.map(c => c.id), ['3'])
})

test('groupConversations 空桶不出现', () => {
  const convs = [conv('1', '2026-07-17T14:30:00')]
  const grouped = groupConversations(convs, FIXED_NOW)
  assert.equal(grouped.length, 1)
  assert.equal(grouped[0].key, 'today')
})

test('groupConversations 空数组返回空数组', () => {
  assert.deepEqual(groupConversations([], FIXED_NOW), [])
})

test('groupConversations 用 label 字段', () => {
  const grouped = groupConversations([conv('1', '2026-07-17T14:30:00')], FIXED_NOW)
  assert.equal(grouped[0].label, '今天')
})

import { formatConversationTime } from '../src/lib/conversation-grouping.ts'

test('今天的会话显示 HH:MM', () => {
  assert.equal(formatConversationTime('2026-07-17T14:30:00', FIXED_NOW), '14:30')
  assert.equal(formatConversationTime('2026-07-17T09:05:00', FIXED_NOW), '09:05')
})

test('昨天显示 昨天', () => {
  assert.equal(formatConversationTime('2026-07-16T18:00:00', FIXED_NOW), '昨天')
})

test('本周显示周几', () => {
  // 2026-07-15 是周三，2 天前
  assert.equal(formatConversationTime('2026-07-15T10:00:00', FIXED_NOW), '周三')
  // 2026-07-13 是周一，4 天前
  assert.equal(formatConversationTime('2026-07-13T10:00:00', FIXED_NOW), '周一')
})

test('本月显示 MM-DD', () => {
  assert.equal(formatConversationTime('2026-07-09T10:00:00', FIXED_NOW), '07-09')
})

test('更早显示 MM-DD', () => {
  assert.equal(formatConversationTime('2026-06-15T10:00:00', FIXED_NOW), '06-15')
})

test('非法时间显示 --', () => {
  assert.equal(formatConversationTime('', FIXED_NOW), '--')
  assert.equal(formatConversationTime('not-a-date', FIXED_NOW), '--')
})
