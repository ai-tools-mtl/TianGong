# 连续文档视图（单章/全文双模式）— TDD 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 工作区中栏加「单章 / 全文」双模式。全文模式 = 连续文档视图：各章按 `order` 纵向堆叠、激活章唯一可编辑、AI 右栏与顶栏操作跟随激活章，解决「浏览全文难、写作不全局」。

**Architecture:** 纯前端增量。中栏按模式分支渲染（单章路径原样保留）；连续模式 = 章头（标题+状态徽标+图章动作）+ N-1 只读 TiptapEditor + 1 可编辑实例（`key` 强制重挂载）；「激活章」复用现有 `currentId` 与整套保存/防抖/乐观锁机制；AI 面板 `sectionId` 绑定激活章零 props 改动，新增 `getPhase()` 供忙碌锁；IntersectionObserver 滚动停稳跟随 + 编辑锁/AI 忙碌锁两把锁。

**Tech Stack:** Next.js 15 / React / TypeScript / TanStack Query / Zustand / Tiptap 3 / Tailwind / lucide-react。前端无单测框架（package.json 无 vitest/jest），验证 = `pnpm build` + `tsc --noEmit` + `pnpm lint` + 手工 dogfood 清单。后端零改动。

**Spec:** `docs/superpowers/specs/2026-08-18-continuous-document-view-design.md`（v1.1，grill 10 钉已定 + 自查修订 4 项——本计划直接引用其 § 编号，不复述依据）

**分支策略（每批独立分支，完成后 `--no-ff` 合并 main）:**

| 批次 | 分支 | 内容 | 预计 |
|---|---|---|---|
| 1 核心渲染 | `feat/doc-continuous-view` | ui store 双模式 + SectionBlock + page.tsx 连续渲染 + 保存/确认/版本复用 | 1-2 天 |
| 2 AI 跟随与收尾 | `feat/doc-continuous-ai` | getPhase 忙碌锁 + 滚动跟随/编辑锁 + 深链滚动定位 + 文档收尾 | 1-2 天 |

**测试基线约定:** 前端无测试框架，Task 0 记录 `pnpm build` / `pnpm lint` 基线为对照（基线应全绿）。后端零改动，仅批 2 收尾跑一次 pytest 确认不新增失败（GOTCHAS E4：Windows 先起 docker）。

---

## 文件结构（全批总览，标注批次）

| 文件 | 责任 | 动作 | 批 |
|---|---|---|---|
| `apps/web/src/stores/ui.ts` | `editorMode` + `setEditorMode`，persist version 1→2 + migrate | 改 | 1 |
| `apps/web/src/components/section-block.tsx` | 章头（标题/状态徽标/图章动作槽）+ 只读/可编辑编辑器分支 + 激活章 ring | 新建 | 1 |
| `apps/web/src/app/(app)/projects/[id]/page.tsx` | 模式切换按钮 + 中栏按模式分支渲染；图章组件单章原位/连续移章块；深链滚动定位 | 改 | 1/2 |
| `apps/web/src/components/ai-chat-panel.tsx` | `AIChatPanelRef.getPhase()` + 导出 `AIPhase` | 改 | 2 |
| `apps/web/src/components/section-outline.tsx` | （可选）状态色映射提取共享，章头复用 | 改 | 1 |
| `docs/GOTCHAS.md` | 实施中新踩的坑（实现后回填） | 改 | 2 |
| `AGENTS.md` | 「单章/全文双模式 + 激活章语义」约定 | 改 | 2 |

---

# 批 1：核心渲染（feat/doc-continuous-view）

## Task 0: 工程前置（基线 + 分支）

- [ ] **Step 1: 记录前端基线**

```bash
cd apps/web && pnpm build 2>&1 | tail -5
pnpm lint 2>&1 | tail -5
```

Expected: 全绿。留存输出作批内对照。

- [ ] **Step 2: 开分支**

```bash
git checkout main && git checkout -b feat/doc-continuous-view
```

## Task 1: ui store 双模式（spec §3.1）

**Files:** `apps/web/src/stores/ui.ts`

- [ ] **Step 1:** `UIState` 加 `editorMode: 'single' | 'continuous'` + `setEditorMode`
- [ ] **Step 2:** `persist` version 1→2；migrate：`if (version < 2) s.editorMode = 'single'`（老用户无此字段兜底）
- [ ] **Step 3:** `tsc --noEmit` 通过；确认老 localStorage 数据（v1）刷新后不抛错、默认单章

## Task 2: SectionBlock 组件（spec §3.3）

**Files:** `apps/web/src/components/section-block.tsx`（新建）

- [ ] **Step 1:** props：`section: Section`、`isActive: boolean`、`initialContent: object | null`（页面统一传 `contentCache.get(id) ?? section.content`）、`onActivate: (id) => void`、`editorRef: (r: TiptapEditorRef | null) => void`（回调 ref 登记进页面 `editorRefs.current[id]`，spec §3.7）、`figureSlot?: ReactNode`（drawings 章头动作槽，页面层传入 FigureUpload/FigureGenerate）
- [ ] **Step 2:** 章头：序号·标题 + 状态徽标（色点 + 文本：待填写/草稿中/已确认，色映射与 `section-outline.tsx` 的 `STATUS_DOT` 同源——必要时提取共享常量）；容器 `onMouseDownCapture` 让**正文点击也触发激活**（仅非激活态触发，光标需第二次点击——v1 已知瑕点，spec §3.3）
- [ ] **Step 3:** 编辑器分支：`<TiptapEditor key={`${section.id}-${isActive ? 'edit' : 'read'}`} editable={isActive} content={initialContent} ... />`；激活态加 accent ring 视觉标识
- [ ] **Step 4:** 激活态才传 `onChange/onRewriteComplete/sectionId`（非激活态零回调，与只读语义一致）
- [ ] **Step 5:** `tsc --noEmit` 通过

## Task 3: page.tsx 双模式渲染（spec §3.3/§3.5/§3.7）

**Files:** `apps/web/src/app/(app)/projects/[id]/page.tsx`

- [ ] **Step 1:** 读 `editorMode` / `setEditorMode`；顶栏最左加模式切换按钮（单章 `PanelTop` / 全文 `Rows3`，`title` + `aria-label`）
- [ ] **Step 2:** 中栏主体按模式分支：
  - 单章：现有渲染块原样保留（含编辑器上方的图章组件）
  - 连续：滚动容器内 `sections.map` 渲染 `SectionBlock`，drawings 章块槽传 FigureUpload/FigureGenerate（其 `onInsertImage` 走 `editorRefs.current[drawingsId]`；点击章块先激活：`onActivate` 中 `setCurrentId` + `scrollIntoView`）
- [ ] **Step 3:** 页面持有 `editorRefs: Record<id, TiptapEditorRef | null>`（回调 ref 登记）与 `contentCacheRef: Map<id, json>`（`handleSave` 写入 `current.id`、apply-diff 成功后经 `onAppliedContent` 同步，spec §3.5）；`onAppliedContent` 按 `current.id` 取 ref 调 `resetContent`；`handleRewriteComplete` 桥接不变
- [ ] **Step 4:** 模式切换按钮 onClick 先 `flushPendingSave()` 再切模式（编辑器树整体重挂载前落库，spec §3.2）
- [ ] **Step 5:** 保存链路验证：连续模式下编辑激活章 → 2s 防抖 PATCH → 切章（点击章头/大纲）先 flush 后重挂载 → 内容无丢失（crossover 修复模式原样）；快速回切章节内容不回退（缓存兜底）
- [ ] **Step 6:** 手工验收批 1 清单（见下），`pnpm build` 通过

**批 1 手工验收清单:**

- [ ] 切换按钮双向往返；刷新后记住模式
- [ ] 全文模式：所有章节按 order 纵向堆叠，只读章显示内容/图片
- [ ] 点击章头/大纲激活：该章可编辑（工具条/气泡出现）、其余只读；h1 显示激活章标题+状态
- [ ] 激活章输入 → 「保存中…」→「已保存」；确认完成 toast 且状态徽标变「已确认」
- [ ] 切章后回切：内容为最新（无丢失、无串台）；**快速连点回切内容不回退**
- [ ] drawings 章块出现图章组件，点击先激活再可插入；**未激活时发起生成/上传，插入仍落 drawings 章**
- [ ] 模式切换先落库再重挂载，激活章输入不悬空
- [ ] 版本抽屉打开的是激活章版本
- [ ] 单章模式：全部现有交互无回归（图章组件仍在上方、AI 面板正常）

## Task 4: 批 1 原子提交

按依赖顺序拆 commit（每步一个；计划中「图章章头」单列的第 4 个提交与第 3 个同改 page.tsx、行级耦合无法分离，合并为一个并在 body 说明）：

1. `docs: 连续文档视图设计契约与 TDD 实施计划`
2. `feat(ui): 工作区中栏单章/全文双模式状态持久化`
3. `feat(editor): SectionBlock 连续模式章节块（章头+状态徽标+只读/可编辑分支）`
4. `feat(projects): 工作区中栏单章/全文双模式渲染（含图章移章块）`

---

# 批 2：AI 跟随与收尾（feat/doc-continuous-ai）

## Task 5: AIChatPanel 暴露忙碌态（spec §3.2/§3.4）

**Files:** `apps/web/src/components/ai-chat-panel.tsx`

- [ ] **Step 1:** 导出 `AIPhase` 类型；`AIChatPanelRef` 加 `getPhase: () => AIPhase`
- [ ] **Step 2:** `useImperativeHandle` 实现 `getPhase: () => phase`（用 ref 保存 phase 或直接闭包读最新 state——注意 imperative handle 闭包过期问题，用 `useRef` 同步 phase 值）
- [ ] **Step 3:** `tsc --noEmit` 通过

## Task 6: 滚动跟随 + 两把锁（spec §3.2/§3.8）

**Files:** `apps/web/src/app/(app)/projects/[id]/page.tsx`

- [ ] **Step 1:** 编辑锁：`onChange` 置 dirty（`flushPendingSave` 后清）+ `document.activeElement` 焦点落在可编辑实例内 + **激活章在视口内**（滚轮滚动不失焦，纯焦点判定会锁死跟随，spec §3.2）
- [ ] **Step 2:** AI 忙碌锁：`aiChatRef.current?.getPhase()` 非 `'idle'`（**含 `done`/`diff-review`**——防待审草稿被滚动静默丢弃；面板未挂载视 idle，spec §3.2）
- [ ] **Step 3:** IntersectionObserver（仅连续模式、root=中栏滚动容器、观察各 SectionBlock 根元素）：候选章变化 → 500ms 防抖 → 两把锁均未生效时 `setCurrentId`；跟随触发不 `scrollIntoView`
- [ ] **Step 4:** 手工验证：滚动停稳面板/激活章切换；对话进行中滚动不夺权；输入中滚动不夺权；失焦后恢复跟随
- [ ] **Step 5:** `pnpm build` 通过

## Task 7: 深链滚动定位（spec §3.6）

**Files:** `apps/web/src/app/(app)/projects/[id]/page.tsx`

- [ ] **Step 1:** `?section=` 定位与 revision「前往」在连续模式下追加 `scrollIntoView`（单章模式行为不变）；定位在目标章挂载后执行（`setCurrentId` 后的 effect / rAF，spec §3.6）
- [ ] **Step 2:** 手工验证：审查报告页「去修订」→ 连续模式定位目标章并弹确认卡片；pending 提示条「前往」同效

## Task 8: 收尾（文档 + 合并）

- [ ] **Step 1:** 全量验证：`pnpm build` + `tsc --noEmit` + `pnpm lint` 全绿；`docker compose up -d postgres` 后 `cd apps/api && uv run pytest -q 2>&1 | tail -3` 确认后端基线不新增失败（GOTCHAS E4）
- [ ] **Step 2:** `AGENTS.md` 增补约定：「单章/全文双模式与激活章语义——激活章唯一可编辑、AI 面板与顶栏操作绑定激活章、两把锁（编辑中/AI 忙碌）冻结滚动跟随；模式持久化 ui store」
- [ ] **Step 3:** `docs/GOTCHAS.md` 回填实施中新踩的坑（如 IntersectionObserver 抖动、imperative handle 闭包过期等）
- [ ] **Step 4:** spec 头部版本补「已实施」记录与合并 commit hash
- [ ] **Step 5:** 批 2 原子提交后 `--no-ff` 合并 main

**批 2 原子提交划分:**

1. `feat(ai): AIChatPanelRef.getPhase 暴露面板相位供忙碌锁`
2. `feat(projects): 连续模式滚动停稳跟随 + 编辑/AI 双锁`
3. `feat(projects): 深链与修订前往在连续模式滚动定位`
4. `docs: AGENTS 双模式约定 + GOTCHAS 回填 + spec 实施记录`

---

## 验收（最终，spec §6）

- [ ] 双模式切换 + localStorage 记忆（刷新/跨项目）
- [ ] 连续模式：全文滚动浏览、激活章唯一可编辑、确认/版本/保存态正确作用激活章
- [ ] AI：绑定激活章；进行中会话与待审草稿（done）不被滚动夺权；生成/修订/diff 审核全链路可用
- [ ] 深链 + revision「前往」定位正确
- [ ] 图纸章章头动作可用（含未激活时发起，插入仍落 drawings）
- [ ] 单章模式零回归
- [ ] 快速回切章节内容不回退；模式切换先落库
- [ ] build / tsc / lint 全绿；后端 pytest 无新增失败
