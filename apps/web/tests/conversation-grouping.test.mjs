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
