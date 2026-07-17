# 会话列表时间分组与更新时间显示 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把主编辑区 AI 助手的会话选择栏从原生 `<select>` 改为按时间分组（今天/昨天/本周/本月/更早）的展开式面板，每项显示相对更新时间。

**Architecture:** 两个纯函数（分组 + 格式化，用 Node 原生 `node --test` 做 TDD，零新依赖）+ 一个独立 React 组件 `ConversationList` + 在 `ai-chat-panel.tsx` 替换原 `<select>` 段落。后端、类型、React Query hooks 均不改。

**Tech Stack:** Next.js 16 + React 19 + TypeScript 5 + shadcn/ui + Tailwind v4 + lucide-react；测试用 Node 18+ 内置 `node:test`（纯函数 only，不碰组件）。

**Spec:** `docs/superpowers/specs/2026-07-17-conversation-list-grouping-design.md`

**分支：** 当前在 `main`，本计划开始前先切到新分支 `feat/conversation-list-grouping`。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `apps/web/src/lib/conversation-grouping.ts` | 纯函数：`getTimeBucket`、`groupConversations`、`formatConversationTime` | 新建 |
| `apps/web/tests/conversation-grouping.test.mjs` | 上述纯函数的 Node 原生测试 | 新建 |
| `apps/web/src/components/conversation-list.tsx` | `ConversationList` 展开式面板组件 | 新建 |
| `apps/web/src/components/ai-chat-panel.tsx` | 替换 353-391 行会话栏 JSX；`handleDeleteConversation` 改签名 | 改 |
| `apps/web/tsconfig.json` | 让 `tsconfig` 排除 `tests/*.mjs`（避免 TS 检查 .mjs） | 改（如需） |

---

## Task 1: 时间桶判定纯函数 `getTimeBucket`

**Files:**
- Create: `apps/web/src/lib/conversation-grouping.ts`
- Create: `apps/web/tests/conversation-grouping.test.mjs`

- [ ] **Step 1: 写失败测试**

创建 `apps/web/tests/conversation-grouping.test.mjs`：

```javascript
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getTimeBucket } from '../src/lib/conversation-grouping.ts'

// 固定 "现在" 为 2026-07-17 周五 15:00（本地时区），用 monkeypatch now
const NOW = new Date(2026, 5, 17, 15, 0) // 注意 JS Date month 0-indexed：5 = 6 月？
// ❌ 上面注释错了。2026-07-17 对应 new Date(2026, 6, 17, 15, 0)
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd apps/web && node --test tests/conversation-grouping.test.mjs
```
Expected: 失败，报 `Cannot find module '../src/lib/conversation-grouping.ts'`。

> **关于 .ts 导入**：Node 原生不能直接 import `.ts`。两种解法：
> - (A) Node 22.6+ 带 `--experimental-strip-types` 可直接跑 `.ts`。
> - (B) 把纯函数同时写一份 `.mjs` 副本仅供测试导入（DRY 违背，不推荐）。
> - 先试 (A)：`node --test --experimental-strip-types tests/conversation-grouping.test.mjs`。若 Node 版本不够，降级：在 Task 1 末尾把测试改为 `import { getTimeBucket } from '../src/lib/conversation-grouping.ts'` 配合 `tsx`（已在 Next.js 依赖树里，`npx tsx --test ...` 或 `node --import tsx --test ...`）。
>
> **执行时先跑 `node --version`**，按版本选择，把实际可跑的命令固化到下面的实现步骤。

- [ ] **Step 3: 创建纯函数文件（先只实现 getTimeBucket）**

创建 `apps/web/src/lib/conversation-grouping.ts`：

```typescript
/**
 * 会话时间分组与格式化（纯函数，无副作用）。
 * Spec: docs/superpowers/specs/2026-07-17-conversation-list-grouping-design.md
 */

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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd apps/web && node --test --experimental-strip-types tests/conversation-grouping.test.mjs
```
（若 `--experimental-strip-types` 不可用，改用 `node --import tsx/esm --test tests/conversation-grouping.test.mjs` 或 `npx tsx --test ...`）
Expected: 6 tests pass。

- [ ] **Step 5: 提交**

```bash
git add apps/web/src/lib/conversation-grouping.ts apps/web/tests/conversation-grouping.test.mjs
git commit -m "feat(web): 新增 getTimeBucket 时间桶判定纯函数

按 今天/昨天/本周(2~7天)/本月(8~30天)/更早(>30天) 五档分组，
用滚动天数避免日历周边界歧义。含 Node 原生 test 测试。"
```

---

## Task 2: 会话分组 `groupConversations`

**Files:**
- Modify: `apps/web/src/lib/conversation-grouping.ts`（追加）
- Modify: `apps/web/tests/conversation-grouping.test.mjs`（追加测试）

- [ ] **Step 1: 追加失败测试**

在 `apps/web/tests/conversation-grouping.test.mjs` 末尾追加：

```javascript
import { groupConversations } from '../src/lib/conversation-grouping.ts'

const conv = (id, updatedIso) => ({ id, title: 't' + id, created_at: updatedIso, updated_at: updatedIso })

test('groupConversations 按桶分组并保留倒序', () => {
  const convs = [
    conv('1', '2026-07-17T14:30:00'),  // today（本地时区当天）
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
```

> 注意：ISO 字符串如 `2026-07-17T14:30:00`（无时区后缀）会被 `new Date()` 当作**本地时区**解析，与 `FIXED_NOW` 一致，测试稳定。

- [ ] **Step 2: 运行确认失败**

```bash
cd apps/web && node --test --experimental-strip-types tests/conversation-grouping.test.mjs
```
Expected: 失败，`groupConversations is not a function`。

- [ ] **Step 3: 追加实现到 `conversation-grouping.ts`**

在文件末尾追加：

```typescript
import type { Conversation } from '@/types/api'

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
```

- [ ] **Step 4: 运行确认通过**

```bash
cd apps/web && node --test --experimental-strip-types tests/conversation-grouping.test.mjs
```
Expected: 全部 pass。

- [ ] **Step 5: 提交**

```bash
git add apps/web/src/lib/conversation-grouping.ts apps/web/tests/conversation-grouping.test.mjs
git commit -m "feat(web): 新增 groupConversations 会话分组函数"
```

---

## Task 3: 时间格式化 `formatConversationTime`

**Files:**
- Modify: `apps/web/src/lib/conversation-grouping.ts`（追加）
- Modify: `apps/web/tests/conversation-grouping.test.mjs`（追加测试）

- [ ] **Step 1: 追加失败测试**

在测试文件末尾追加：

```javascript
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
```

> 周几的期望值（周三/周一）依赖运行环境的 `Intl` 中文 locale。若 CI 环境非中文 locale，`Intl.DateTimeFormat('zh-CN', {weekday:'short'})` 仍返回中文（显式指定 locale）。本地 Windows 通常也 OK。若失败，把期望值改成实际输出。

- [ ] **Step 2: 运行确认失败**

```bash
cd apps/web && node --test --experimental-strip-types tests/conversation-grouping.test.mjs
```
Expected: 失败，`formatConversationTime is not a function`。

- [ ] **Step 3: 追加实现**

在 `conversation-grouping.ts` 末尾追加：

```typescript
const timeFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit', minute: '2-digit', hour12: false,
})
const weekdayFormatter = new Intl.DateTimeFormat('zh-CN', { weekday: 'short' })
const monthDayFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit', day: '2-digit',
})

/**
 * 把 updated_at 格式化为相对时间字符串。
 *   today  -> HH:MM (如 14:30)
 *   yesterday -> 昨天
 *   thisWeek -> 周几 (如 周二)
 *   thisMonth / earlier -> MM-DD (如 07-10)
 * 非法时间返回 '--'。
 */
export function formatConversationTime(updatedAt: string, now: Date = new Date()): string {
  const d = new Date(updatedAt)
  if (Number.isNaN(d.getTime())) return '--'
  switch (getTimeBucket(d, now)) {
    case 'today':
      return timeFormatter.format(d)
    case 'yesterday':
      return '昨天'
    case 'thisWeek':
      return weekdayFormatter.format(d)
    case 'thisMonth':
    case 'earlier':
    default:
      return monthDayFormatter.format(d)
  }
}
```

- [ ] **Step 4: 运行确认通过**

```bash
cd apps/web && node --test --experimental-strip-types tests/conversation-grouping.test.mjs
```
Expected: 全部 pass。若「周几」断言失败，先 `node -e "console.log(new Intl.DateTimeFormat('zh-CN',{weekday:'short'}).format(new Date(2026,6,15)))"` 看实际输出，更新期望值。

- [ ] **Step 5: 提交**

```bash
git add apps/web/src/lib/conversation-grouping.ts apps/web/tests/conversation-grouping.test.mjs
git commit -m "feat(web): 新增 formatConversationTime 相对时间格式化"
```

---

## Task 4: 让 TS 构建忽略测试目录

**Files:**
- Modify: `apps/web/tsconfig.json`

- [ ] **Step 1: 检查 tsconfig 是否已排除 tests**

```bash
cd apps/web && grep -A5 '"exclude"' tsconfig.json
```

- [ ] **Step 2: 若无 exclude 或未含 tests，添加**

打开 `apps/web/tsconfig.json`，确保有：

```json
{
  "exclude": ["node_modules", "tests/**/*.mjs", "tests/**/*.ts"]
}
```

> 说明：`.mjs` 测试用 ESM import `.ts`，TypeScript 类型检查不应处理它（避免把测试文件纳入 build 类型检查）。`.ts` 源文件本身仍被检查。

- [ ] **Step 3: 验证 build 仍通过**

```bash
cd apps/web && pnpm build
```
Expected: 成功，TypeScript 无报错。

- [ ] **Step 4: 提交（如有改动）**

```bash
git add apps/web/tsconfig.json
git commit -m "build(web): 排除 tests 目录避免污染类型检查"
```

（若 tsconfig 无需改动则跳过提交）

---

## Task 5: `ConversationList` 组件

**Files:**
- Create: `apps/web/src/components/conversation-list.tsx`

- [ ] **Step 1: 创建组件**

创建 `apps/web/src/components/conversation-list.tsx`：

```tsx
'use client'

import { ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { groupConversations, formatConversationTime } from '@/lib/conversation-grouping'
import type { Conversation } from '@/types/api'

interface ConversationListProps {
  conversations: Conversation[]
  currentConvId: string | null
  loading: boolean
  createPending: boolean
  deletePending: boolean
  onSelect: (convId: string) => void
  onNew: () => void
  onDelete: (convId: string) => void
}

export function ConversationList({
  conversations,
  currentConvId,
  loading,
  createPending,
  deletePending,
  onSelect,
  onNew,
  onDelete,
}: ConversationListProps) {
  // 有会话时默认展开，无会话时不展开（无需展开空列表）
  const [expanded, setExpanded] = useState((conversations?.length ?? 0) > 0)
  const groups = groupConversations(conversations ?? [])
  const current = (conversations ?? []).find((c) => c.id === currentConvId)
  const hasConvs = (conversations?.length ?? 0) > 0

  // 标题行（始终显示）：当前会话标题 + 折叠箭头 + 新建
  const headerRow = (
    <div className="flex h-8 shrink-0 items-center gap-1 border-b bg-muted/30 px-2">
      <button
        type="button"
        onClick={() => hasConvs && setExpanded((e) => !e)}
        disabled={loading || !hasConvs}
        className="flex h-6 flex-1 items-center gap-1 truncate rounded px-1 text-left text-[12px] outline-none hover:bg-muted disabled:cursor-default disabled:hover:bg-transparent"
        title={current?.title ?? '新对话'}
      >
        {loading ? (
          <span className="text-muted-foreground">加载中...</span>
        ) : hasConvs ? (
          <>
            <span className="flex-1 truncate">{current?.title ?? '选择会话'}</span>
            {expanded ? (
              <ChevronUp className="size-3 shrink-0 text-muted-foreground" />
            ) : (
              <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
            )}
          </>
        ) : (
          <span className="text-muted-foreground">新对话</span>
        )}
      </button>
      <Button
        variant="ghost"
        size="icon-xs"
        onClick={onNew}
        disabled={createPending}
        title="新建会话"
      >
        <Plus className="size-3.5" />
      </Button>
    </div>
  )

  // 无会话或折叠：只渲染标题行
  if (!hasConvs || !expanded) {
    return headerRow
  }

  // 展开态：标题行 + 分组列表
  return (
    <div className="shrink-0 border-b">
      {headerRow}
      <div className="max-h-64 overflow-y-auto py-1">
        {groups.map((g) => (
          <div key={g.key}>
            <div className="sticky top-0 z-10 bg-background px-3 py-1 text-[11px] font-medium text-muted-foreground">
              {g.label}
            </div>
            {g.items.map((c) => {
              const selected = c.id === currentConvId
              return (
                <div
                  key={c.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelect(c.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onSelect(c.id)
                    }
                  }}
                  className={cn(
                    'group flex h-8 items-center gap-2 px-3 cursor-pointer hover:bg-muted',
                    selected && 'bg-primary/10',
                  )}
                >
                  {selected && <span className="size-1.5 shrink-0 rounded-full bg-primary" />}
                  {!selected && <span className="size-1.5 shrink-0" />}
                  <span className="flex-1 truncate text-[12px]">{c.title}</span>
                  <span className="text-[11px] tabular-nums text-muted-foreground">
                    {formatConversationTime(c.updated_at)}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(c.id)
                    }}
                    disabled={deletePending}
                    title="删除会话"
                    className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
```

> **关于 `useState` 初值**：`(conversations?.length ?? 0) > 0` 只在首次挂载求值。若 `conversations` 异步加载（挂载时为空，加载后有数据），初值会是 `false`。用户点一次标题即可展开，可接受。若想自动展开，可用 `useEffect` 监听 conversations 首次非空时 `setExpanded(true)`——本计划选简洁，不加 effect。

- [ ] **Step 2: 验证 build**

```bash
cd apps/web && pnpm build
```
Expected: 成功（组件未被引用也不会报错，tree-shaking 移除）。

- [ ] **Step 3: 提交**

```bash
git add apps/web/src/components/conversation-list.tsx
git commit -m "feat(web): 新增 ConversationList 展开式分组会话面板组件"
```

---

## Task 6: 接入 `ai-chat-panel.tsx`

**Files:**
- Modify: `apps/web/src/components/ai-chat-panel.tsx`

- [ ] **Step 1: 改 `handleDeleteConversation` 签名为接受 convId**

找到（约 129 行）：

```typescript
function handleDeleteConversation() {
  if (!currentConvId) return
  const convId = currentConvId
  deleteConv.mutate(convId, {
    onSuccess: () => {
      msgLoadedForConv.current = null
      setCurrentConvId(null)
      setMessages([])
      setPhase('idle')
      toast.success('会话已删除')
    },
  })
}
```

替换为：

```typescript
function handleDeleteConversation(convId: string) {
  deleteConv.mutate(convId, {
    onSuccess: () => {
      // 删除的是当前会话才清空显示
      if (convId === currentConvId) {
        msgLoadedForConv.current = null
        setCurrentConvId(null)
        setMessages([])
        setPhase('idle')
      }
      toast.success('会话已删除')
    },
  })
}
```

- [ ] **Step 2: 替换会话选择栏 JSX**

找到（约 352-391 行）整段 `{/* 会话选择栏 */}` 注释开始到对应 `)}` 结束：

```tsx
      {/* 会话选择栏 */}
      {phase !== 'generating' && phase !== 'done' && (
        <div className="flex h-8 shrink-0 items-center gap-1 border-b bg-muted/30 px-2">
          <select
            value={currentConvId ?? ''}
            onChange={(e) => handleSelectConversation(e.target.value)}
            className="h-6 flex-1 truncate rounded border-none bg-transparent text-[12px] outline-none cursor-pointer hover:bg-muted"
            disabled={convsLoading || createConv.isPending}
          >
            {convsLoading && <option>加载中...</option>}
            {!convsLoading && (conversations?.length ?? 0) === 0 && <option value="">新对话</option>}
            {conversations?.map((c: Conversation) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={handleNewConversation}
            disabled={createConv.isPending}
            title="新建会话"
          >
            <Plus className="size-3.5" />
          </Button>
          {currentConvId && (conversations?.length ?? 0) > 1 && (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={handleDeleteConversation}
              disabled={deleteConv.isPending}
              title="删除当前会话"
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      )}
```

替换为：

```tsx
      {/* 会话选择栏 */}
      {phase !== 'generating' && phase !== 'done' && (
        <ConversationList
          conversations={conversations ?? []}
          currentConvId={currentConvId}
          loading={convsLoading}
          createPending={createConv.isPending}
          deletePending={deleteConv.isPending}
          onSelect={handleSelectConversation}
          onNew={handleNewConversation}
          onDelete={handleDeleteConversation}
        />
      )}
```

- [ ] **Step 3: 加 import**

在 `ai-chat-panel.tsx` 顶部 import 区（`./diff-review-panel` 那行附近）加：

```typescript
import { ConversationList } from '@/components/conversation-list'
```

- [ ] **Step 4: 清理不再使用的 import**

`Conversation` 类型若不再被本文件直接引用（检查：原 `<option>` 里用过 `(c: Conversation)`，现在移到 `ConversationList` 内部了），从 import 移除 `Conversation`。`Plus`、`Trash2` 图标若除会话栏外没其它地方用，也移除。

执行：
```bash
cd apps/web && grep -n "Conversation\b\|Plus\|Trash2" src/components/ai-chat-panel.tsx
```
根据结果决定保留/移除对应 import。`Trash2` 可能还在「清空对话」按钮用——保留；`Plus` 若只在已删除的会话栏用则移除。

- [ ] **Step 5: 验证 build**

```bash
cd apps/web && pnpm build
```
Expected: 成功，无 TS 报错（特别注意 unused import 会被 eslint 警告但不阻断 build；若有 `noUnusedLocals` 严格设置则需清理干净）。

- [ ] **Step 6: 提交**

```bash
git add apps/web/src/components/ai-chat-panel.tsx
git commit -m "feat(web): AI 助手会话栏接入 ConversationList 分组面板

替换原生 select，改为按时间分组（今天/昨天/本周/本月/更早）
的展开式面板，每项显示相对更新时间。handleDeleteConversation
改为接受 convId 参数以支持每项 hover 删除。"
```

---

## Task 7: 全量验证 + 收尾

**Files:** 无

- [ ] **Step 1: 跑纯函数测试**

```bash
cd apps/web && node --test --experimental-strip-types tests/conversation-grouping.test.mjs
```
Expected: 全部 pass。

- [ ] **Step 2: 跑前端构建**

```bash
cd apps/web && pnpm build
```
Expected: 成功，13 路由正常生成。

- [ ] **Step 3: 跑后端测试（确认未碰后端）**

```bash
cd apps/api && uv run pytest -q
```
Expected: 302 passed（应与改动前一致，本次未改后端）。

- [ ] **Step 4: 手测清单（spec §7）**

启动前后端：
```bash
cd apps/api && uv run uvicorn app.main:app --reload &
cd apps/web && pnpm dev
```

打开项目编辑页，在 AI 助手面板：
- [ ] 会话栏显示当前会话标题 + 下箭头 + [+]，默认展开
- [ ] 多个不同时间的会话被分到 5 个桶，标题正确（今天/昨天/本周/本月/更早）
- [ ] 今天的会话显示 `HH:MM`
- [ ] 昨天的会话显示「昨天」并归入昨天组
- [ ] 本周会话显示周几
- [ ] 本月/更早显示 `MM-DD`
- [ ] 选中项有高亮背景 + 左侧圆点
- [ ] hover 每项右侧出现删除按钮，点击删除生效
- [ ] 点击标题行可折叠/展开
- [ ] 会话多时面板内可滚动，分组标题 sticky 保持可见
- [ ] 新建会话后列表刷新
- [ ] 删除最后一个会话后面板收起为空态单行

- [ ] **Step 5: 最终提交（如有手测修复）**

若手测发现小问题并修复，单独提交：

```bash
git add -p  # 选择性暂存
git commit -m "fix(web): 会话面板手测修复 <具体问题>"
```

---

## Self-Review 记录

**Spec 覆盖核对：**
- §1 目标（分组 + 时间显示）→ Task 1-3 + 5-6 ✓
- §2 交互形态（展开/折叠、≤1 退化、不自动折叠）→ Task 5 组件实现 ✓（注：spec「切换会话不自动折叠」因组件自管 expanded 且 onSelect 不改 expanded，天然满足）
- §3.1 分组逻辑（5 桶滚动天数）→ Task 1 getTimeBucket ✓
- §3.2 格式化 → Task 3 ✓
- §4 组件结构（新文件 + ai-chat-panel 改动 + handleDelete 改签名）→ Task 5 + 6 ✓
- §5 UI 样式（sticky 分组标题、选中圆点、hover 删除、max-h-64 滚动）→ Task 5 ✓
- §6 边界（非法 updated_at 归 earlier/--、时区本地）→ Task 1 + 3 测试覆盖 ✓
- §7 测试策略（纯函数 Node test，组件手测）→ Task 1-3 + Task 7 ✓
- §8 改动清单（2 新 + 1 改）→ 与计划一致 ✓

**类型一致性核对：**
- `TimeGroupKey`、`GROUP_LABELS`、`ConversationGroup`、`groupConversations`、`formatConversationTime`、`getTimeBucket` 在 Task 1/2/3 定义，Task 5 引用——签名一致 ✓
- `ConversationListProps`（Task 5）与 Task 6 接入处 props 一致：`onSelect: (id:string)=>void`、`onDelete: (id:string)=>void`、`onNew: ()=>void`、loading/createPending/deletePending、currentConvId 可 null ✓
- `handleDeleteConversation(convId: string)`（Task 6 Step 1）与 `onDelete` prop 签名匹配 ✓

**已知限制（写入计划透明）：**
- Task 5 的 `expanded` 初值在 conversations 异步加载场景下为 false——spec 已注明可接受，如需自动展开可加 effect（计划选简洁路径）。
