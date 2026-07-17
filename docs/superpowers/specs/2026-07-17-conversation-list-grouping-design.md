# 会话列表时间分组与更新时间显示 — 设计契约

> 日期：2026-07-17
> 状态：已与用户确认，待编写实施计划
> 关联：主编辑区 AI 助手面板（`apps/web/src/components/ai-chat-panel.tsx`）

## 1. 背景与目标

主编辑区右侧 AI 助手面板的会话选择栏，当前是一个原生 `<select>` 下拉，仅显示会话标题，按 `updated_at` 倒序排列。随着会话增多，用户难以快速定位历史会话，也看不出每个会话「最近什么时候用过」。

**目标：**
1. 把会话按最后更新时间分到「今天 / 昨天 / 本周 / 本月 / 更早」五个分组，带分组标题展示。
2. 每个会话项旁显示相对的更新时间（如 `14:30`、`昨天`、`周二`、`07-10`）。

**非目标（YAGNI）：**
- 不做会话搜索、置顶、重命名内联编辑。
- 不做拖拽排序。
- 不引入 date-fns / dayjs 等时间库——用原生 `Intl` + 少量手写逻辑即可。

## 2. 交互形态：展开式面板

会话栏从原生 `<select>` 改为自定义展开式面板组件。

**收起态**（默认）：
```
┌─ AI 助手 ──────────────┐
│ 发名称咨询 ▾      [+] │   一行：当前会话标题 + 新建按钮
└────────────────────────┘
```
点击标题行或箭头展开。

**展开态**：
```
┌─ AI 助手 ──────────────┐
│ 发名称咨询 ▴      [+] │   标题行（点击折叠）
├────────────────────────┤
│ 今天                    │   分组标题
│  ● 发名称咨询    14:30 │   选中项：bg + 左侧圆点
│   权利要求讨论   11:20 │
│   背景技术    🗑 昨天  │   ← hover 时右侧出现删除按钮
│ 本周                    │
│   附图说明       周二  │
│ 更早                    │
│   选型对比      06-28  │
└────────────────────────┘
```

**展开/折叠行为：**
- 初始进入页面时，若已有会话，**默认展开**（让用户第一时间看到分组和当前选中项）。
- 会话数 ≤ 1 时，面板退化为单行（无展开必要），仍显示标题 + 时间 + 新建按钮。
- 切换会话（onSelect）后**不自动折叠**——保持当前展开态，避免每次点完就被收起。
- 删除最后一个会话后面板自动折叠为空态。

## 3. 时间分组逻辑

新增纯函数模块 `apps/web/src/lib/conversation-grouping.ts`。

### 3.1 `groupConversations(convs)`

输入：`Conversation[]`（已按 `updated_at` 倒序）。
输出：`Array<{ key: TimeGroupKey; label: string; items: Conversation[] }>`，按 `today → earlier` 顺序，**空组不出现在结果里**。

```typescript
type TimeGroupKey = 'today' | 'yesterday' | 'thisWeek' | 'thisMonth' | 'earlier'

const GROUP_LABELS: Record<TimeGroupKey, string> = {
  today: '今天',
  yesterday: '昨天',
  thisWeek: '本周',
  thisMonth: '本月',
  earlier: '更早',
}
```

**分组实现采用滚动天数，不用自然周/自然月。** 这是为了避免日历边界歧义（如「周三时，上周一的会话该算本周还是上周」）。文案对用户仍显示「本周 / 本月」，因为从用户语义上「这一周/这一个月内的会话」与滚动天数一致。判定规则（以「现在」为基准时刻 `now`）：

| 分组 key | 判定（`updated_at` 落在） | 文案 |
|---|---|---|
| `today` | 今天 00:00 之后 | 今天 |
| `yesterday` | 昨天 00:00 ~ 今天 00:00 | 昨天 |
| `thisWeek` | 7 天前 00:00 ~ 昨天 00:00（含往前第 2~7 天） | 本周 |
| `thisMonth` | 30 天前 00:00 ~ 7 天前 00:00 | 本月 |
| `earlier` | 30 天前以前 | 更早 |

实现要点：
- 用「当天 00:00 的 `Date`」做边界比较，避免时分秒干扰。
- 每组内的 `items` 保持传入顺序（后端已倒序），不再二次排序。

### 3.2 `formatConversationTime(updatedAt)`

输入：ISO 时间字符串。
输出：相对时间字符串。

| `updated_at` 时刻 | 显示 |
|---|---|
| 今天 | `HH:MM`（如 `14:30`，24 小时制，零填充） |
| 昨天 | `昨天` |
| 本周（2~7 天前） | 周几（`周二`、`周日`） |
| 本月（8~30 天前） | `MM-DD`（如 `07-10`） |
| 更早（>30 天） | `MM-DD` |

实现要点：用原生 `Intl.DateTimeFormat`：
- `HH:MM`：`new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })`
- 周几：`new Intl.DateTimeFormat('zh-CN', { weekday: 'short' })`（zh-CN 的 short weekday 是「周二」格式）
- `MM-DD`：手写 `padStart` 或 `Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' })`

注：`formatConversationTime` 与 `groupConversations` 共享同一套时间区间判定（今天/昨天/本周/本月/更早），二者必须用同一个边界常量避免漂移——实现时抽一个 `getTimeBucket(date): TimeGroupKey` 供两者复用。

## 4. 组件结构

### 4.1 新文件 `apps/web/src/components/conversation-list.tsx`

```typescript
interface ConversationListProps {
  conversations: Conversation[]
  currentConvId: string | null
  loading: boolean
  onSelect: (convId: string) => void
  onNew: () => void
  onDelete: (convId: string) => void
  // createPending / deletePending 用于禁用对应按钮
  createPending: boolean
  deletePending: boolean
}
```

职责：
- 维护内部 `expanded: boolean` 状态。
- 调用 `groupConversations` 计算分组。
- 渲染收起态标题行 + 展开态分组列表。
- 每项 hover 显示删除按钮，点击触发 `onDelete(id)`。
- 列表 `overflow-y-auto`，`max-h-64`（约 8 项可视，超出滚动）。

### 4.2 改动 `apps/web/src/components/ai-chat-panel.tsx`

- 删除当前 353-389 行的原生 `<select>` 会话栏 JSX。
- 替换为 `<ConversationList ... />`，props 透传现有数据与回调：
  - `conversations`, `currentConvId`, `loading={convsLoading}`
  - `onSelect={handleSelectConversation}`, `onNew={handleNewConversation}`, `onDelete={(id) => deleteConv.mutate(id, {...})}`
  - `createPending={createConv.isPending}`, `deletePending={deleteConv.isPending}`
- `handleDeleteConversation` 当前直接用 `currentConvId`——需要改为接受 `convId` 参数（因为删除入口移到了每项）。

### 4.3 不变的部分

- 后端 `list_conversations` 已按 `updated_at` 倒序返回并包含 `created_at` / `updated_at`，**无需后端改动**。
- `Conversation` 类型已含 `updated_at`，**无需改类型**。
- React Query 的 `useConversations` / `useCreateConversation` / `useDeleteConversation` 逻辑不变。

## 5. UI / 样式细节

沿用项目现有 shadcn/ui + Tailwind 风格（与 `ai-chat-panel` 标题栏、消息列表一致）：

- 标题行：`h-8 flex items-center gap-1 px-2 border-b bg-muted/30`
  - 会话标题：`flex-1 truncate text-[12px] cursor-pointer hover:bg-muted`
  - 展开箭头：用 `ChevronDown` / `ChevronUp`（lucide-react，项目已用）
  - 新建按钮：现有 `Plus` icon-xs
- 分组标题：`px-3 py-1 text-[11px] font-medium text-muted-foreground sticky top-0 bg-background`
  - sticky 让滚动时分组标题保持可见
- 会话项：`group flex h-8 items-center gap-2 px-3 cursor-pointer hover:bg-muted`
  - 选中态：`bg-primary/10`，左侧 `size-1.5 rounded-full bg-primary` 圆点
  - 标题：`flex-1 truncate text-[12px]`
  - 时间：`text-[11px] text-muted-foreground tabular-nums`
  - 删除按钮：`opacity-0 group-hover:opacity-100` 的 `Trash2` icon-xs，hover 变 `text-destructive`
- 空态（无会话）：显示「点击 + 开始新对话」提示，隐藏分组区域
- 加载态：`loading` 时标题行显示「加载中...」

## 6. 边界与降级

- `updated_at` 缺失或非法（解析失败）：归入 `earlier`，时间显示 `--`。
- 时区：用浏览器本地时区（用户期望看到的是「自己今天的会话」）。后端返回的 ISO 字符串带时区信息，`new Date()` 正确解析。
- 会话数极大（>100）：前端全量分组渲染，依赖 `max-h-64 + overflow-y-auto` 滚动。暂不做虚拟列表（YAGNI，MVP 阶段单 section 会话量不会破百）。

## 7. 测试策略

**纯函数（`conversation-grouping.ts`）：**
- 项目当前**无前端测试框架**（无 vitest/jest 配置）。本设计的两个函数是纯函数、零外部依赖，理论上可测。
- 决策：**不为加这两个函数的测试而引入 vitest**（违背「不扩大 scope」原则）。改用以下替代验证：
  1. 在 `conversation-grouping.ts` 底部用条件导出方式留一个可被 Node 直接 `node -e` 跑的 smoke 脚本（仅开发用，不进 bundle）——若实现复杂度上升再考虑正式测试。
  2. `pnpm build` 通过 TypeScript 类型检查。
  3. 实现时在 spec 附件里附一组「输入 → 期望输出」的样例表，供手测对照。

**组件（`conversation-list.tsx`）：**
- 无组件测试框架，靠手测验证：展开/折叠、分组正确、选中态、删除、滚动、空态。

**全量验证：**
- `cd apps/web && pnpm build` 通过。
- 手测清单：
  - [ ] 多个不同时间的会话被正确分到 5 个桶
  - [ ] 今天的会话显示 `HH:MM`
  - [ ] 昨天的会话显示「昨天」并归入「昨天」组
  - [ ] 本周会话显示周几
  - [ ] 选中项有高亮 + 圆点
  - [ ] hover 每项出现删除按钮，点击删除生效
  - [ ] 新建会话后列表刷新
  - [ ] 删除最后一个会话后面板折叠为空态
  - [ ] 会话多时面板内可滚动，分组标题 sticky

## 8. 实施改动清单

**新增（2 文件）：**
- `apps/web/src/lib/conversation-grouping.ts` — `groupConversations` + `formatConversationTime` + 共享 `getTimeBucket`
- `apps/web/src/components/conversation-list.tsx` — `ConversationList` 组件

**改动（1 文件）：**
- `apps/web/src/components/ai-chat-panel.tsx` — 替换会话栏 JSX 为 `<ConversationList>`，`handleDeleteConversation` 改为接受 `convId` 参数

**不改：**
- 后端、类型、React Query hooks、diff-review 链路。

## 9. 附：分组样例（实现/手测对照）

基准时刻假设为 `2026-07-17（周五）15:00`（浏览器本地时区）：

| `updated_at` | 距今 | 分组 | 显示 |
|---|---|---|---|
| 2026-07-17 14:30 | 当天 | 今天 | `14:30` |
| 2026-07-17 09:15 | 当天 | 今天 | `09:15` |
| 2026-07-16 18:00 | 1 天 | 昨天 | `昨天` |
| 2026-07-15 10:00 | 2 天 | 本周 | `周三` |
| 2026-07-13 10:00 | 4 天 | 本周 | `周一` |
| 2026-07-10 10:00 | 7 天 | 本周 | `周四` |
| 2026-07-09 10:00 | 8 天 | 本月 | `07-09` |
| 2026-07-01 10:00 | 16 天 | 本月 | `07-01` |
| 2026-06-15 10:00 | 32 天 | 更早 | `06-15` |
| `''`（非法） | — | 更早 | `--` |

> 注：周几按真实日历计算，不依赖分组。上表「周三/周一/周四」对应 2026-07-15/13/10 的实际星期。
