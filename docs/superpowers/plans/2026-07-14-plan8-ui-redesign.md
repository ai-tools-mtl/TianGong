# 计划 8：PC 端 UI 重构（grill 契约驱动）

> **本计划为已完成的实施记录**（非待执行计划）。记录一次由 `/grill-me` 设计访谈驱动的 UI 重构，含设计契约、实施内容、原子提交划分、踩坑与验收。
> **设计契约详见：** `specs/2026-07-14-ui-redesign-contract.md`
> **关联踩坑：** `GOTCHAS.md` F5（Turbopack `@plugin` 解析失败）、F6（next-themes 空转）

**Goal:** 将天工前端从「单栏居中博客形态 + 纯灰度主题」重构为「GitHub/Figma 工具感的工作台形态 + 墨色产品态 + AI 紫专属」，以 PC 端（≥1280px）为唯一目标场景。

**Architecture:** 工作台型 app shell（顶部全局栏 + 满宽主区）+ 项目内紧凑三栏（左大纲 / 中编辑 / 右 AI，可折叠 + localStorage 记忆）+ 冷灰底亮色优先主题（墨色管产品态、紫色严格只给 AI）+ 双字体策略（UI 用 Geist+系统栈保响应、正文用思源黑体保跨设备一致）。

**Spec reference:** 本次重构的契约由 `/grill-me` 会话产生（10 个钉子问题），非 MVP 设计文档章节。契约独立归档于 `specs/2026-07-14-ui-redesign-contract.md`。

---

## 背景

重构前的前端状态：
- `(app)/layout.tsx` 用 `max-w-5xl`（1024px）封印所有页面宽度，包括项目工作区
- 主题纯灰度（`--primary: oklch(0.205 0 0)`，所有 token 零色度），无品牌色、无 AI 视觉身份
- `next-themes` 已装但 ThemeProvider 未接通，暗色主题是死的
- 编辑器 `prose` 类完全无样式（`@tailwindcss/typography` 未装）
- 字体只引 Geist，中文 fallback 到系统字体，跨设备字形漂移
- AI 面板 `window.location.reload()` 整页重载丢失工作区状态

## grill 决策摘要（10 钉）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 美观锚点 | GitHub / Figma（工具感、灰底+点缀色、高信息密度） |
| 2 | 骨架形态 | 工作台型（左栏+主工作区满宽），非阅读型单栏 |
| 3 | 左栏层级 | 项目级（仅 `projects/[id]/*` 出现），全局导航留顶部 |
| 4 | AI 位置 | 紧凑三栏常驻右栏（强 AI），非浮动/全屏切换 |
| 5 | 折叠策略 | 用户手动折叠左右栏 + localStorage 记忆 |
| 6 | 品牌色 | 无独立品牌色，AI 单独染紫（Cursor/Vercel 调性） |
| 7 | 品牌色归属 | 产品态归墨色（ink），紫严格只给 AI 元素 |
| 8 | 默认主题 | 亮色优先，暗色可选（专业耐写优先于科技炫感） |
| 9 | 字体 | 双策略：UI 用系统栈保响应，正文用思源黑体 Web 字体 |
| 10 | 中文字体 | 思源黑体 Noto Sans SC（GitHub 中文 fallback 同源，风险最低） |

完整契约（含连锁决定的隐含事项）见 spec 文档。

---

## 任务划分（5 阶段，已全部完成）

### 阶段 0：地基（主题系统 + 字体 + ThemeProvider）

- `globals.css` 纯灰度 → 冷灰底（hue 240）+ 墨色产品态；新增 `--ai/--ai-foreground/--ai-muted/--ai-glow` 与 `--success/--warning/--info` 语义 token；修掉重复 `@apply` bug；radius 收到 0.5rem；手写 `.prose` 排版（GitHub 风）
- `layout.tsx` 接入 `Noto_Sans_SC`（`--font-zh`，仅挂正文类）+ `suppressHydrationWarning`
- `providers.tsx` 接通 `next-themes` ThemeProvider（亮色默认、跟随系统）

### 阶段 1：顶栏改版 + app shell 宽度策略

- `navbar.tsx` 重做：内联 SVG logo（「工」方印）+ `next/link` active 高亮 + 主题切换按钮 + 用户下拉
- 新增 `logo.tsx` / `theme-toggle.tsx` / `page-shell.tsx` 共享组件
- `(app)/layout.tsx` 去掉 `max-w-5xl` 改 `flex-1` 满宽分发，容器下放各页面

### 阶段 2：项目工作区紧凑三栏

- `projects/[id]/page.tsx` 重写为三栏（左 240 / 中 1fr / 右 360），左右栏可折叠，状态存 `stores/ui.ts`（zustand+persist）
- `ai-chat-panel.tsx` 删双重宽度声明、`reload()` → `invalidateQueries()`、AI 气泡淡紫底+紫边框+生成光晕动画
- `section-outline.tsx` 状态点走 token + 折叠态竖条
- `preview` / `review` 加 `.prose`，硬编码 green/amber 改 `--success/--warning` token，评分卡用 Card 重排

### 阶段 3：非项目页重排 + auth 布局

- dashboard 卡片加 hover/进度条/状态色 token
- templates/settings/admin 用 `PageShell` + Card 重排
- 新增 `(auth)/layout.tsx` 双栏（左品牌栏含 AI 紫光晕，右表单），窄屏退化
- login/register 简化，复用 logo

### 阶段 4：全局收尾

- 硬编码色清扫：全局 grep 验证 `bg/text/border-(blue|green|amber|...)-[0-9]` 零残留
- 图标统一走 `lucide-react`
- `pnpm build` + `tsc --noEmit` 通过

---

## 原子提交划分（4 个，按依赖顺序）

| # | Commit | Scope | 说明 |
|---|--------|-------|------|
| 1 | `a412b92` | 地基 | 主题 token + 字体 + ThemeProvider。所有后续改动的依赖 |
| 2 | `58a0a6a` | 顶栏+shell | navbar + 共享组件 + 宽度封印解除 |
| 3 | `93759c5` | 工作区 | 三栏可折叠 + AI 面板 + 大纲 + preview/review |
| 4 | `9d2376a` | 非项目页 | dashboard/templates/settings/admin + auth |

每个提交单独 checkout 可编译、相关功能自洽。

---

## 踩坑（详见 GOTCHAS.md）

### F5: Turbopack `@plugin` 解析 npm 包名失败

- **现象**：`@plugin "@tailwindcss/typography"` 在 dev（Turbopack）报 `Can't resolve '@tailwindcss/typography'`，但 `pnpm build` 不报错
- **根因**：Turbopack 的 CSS `@plugin` 解析器在 Windows + pnpm symlink 环境下解析 npm 包名失败（不如 JS `import` 成熟）
- **修复**：卸载 typography 插件，手写 50 行 `.prose` CSS 直接设标题/段落/列表/代码块样式
- **预防**：Tailwind v4 在 Turbopack 下慎用 `@plugin` 引 npm 包；能用 CSS 手写就手写

### F6: next-themes 装了但没接 ThemeProvider

- **现象**：`useTheme()` 在组件里调用返回默认值，暗色主题完全无效
- **根因**：`sonner.tsx` 调了 `useTheme()` 但全局没有 `<ThemeProvider>` 包裹
- **修复**：`providers.tsx` 加 `<ThemeProvider attribute="class" defaultTheme="light" enableSystem>`
- **预防**：装了 next-themes 必须接 provider；`<html>` 加 `suppressHydrationWarning`

### F7: AIChatPanel 双重宽度声明

- **现象**：改 grid 列宽时 AI 面板宽度不跟随
- **根因**：`ai-chat-panel.tsx` 既被 grid 列（`320px`）约束，又自带 `style={{ width: 320 }} + border-l`
- **修复**：删内联 style 和 border，宽度完全交给 grid 列
- **预防**：组件放进 grid 时，宽度声明只能在一处——要么 grid 列、要么组件自身，不能两边都写

---

## 验收清单

### 自动验证（已通过）

- [x] `pnpm build` 通过（10 路由全部编译成功）
- [x] `pnpm exec tsc --noEmit` 退出码 0
- [x] 全局 grep 硬编码色零残留
- [x] `window.location.reload()` 已清除（仅注释保留）

### 手动走查（建议路径）

启动 `pnpm dev` 后按序验证：

1. **登录页** `/login` → 双栏布局，左品牌栏含 AI 紫光晕，右表单
2. **工作台** `/dashboard` → 项目卡片 hover 效果、进度条、状态 badge 着色
3. **进项目** `/projects/[id]` → 三栏布局，点左/右栏折叠按钮，**刷新后折叠态保持**
4. **AI 对话** → 发消息看淡紫气泡；点「生成草稿」看光晕动画（不再整页刷新）
5. **顶栏** → 点头像 → 主题切换亮/暗，每页都过一遍暗色
6. **预览** `/preview` → 正文应是思源黑体
7. **审查** `/review` → 绿/琥珀语义色，评分卡 Card 布局
8. **设置** `/settings` → 自定义配置表单 Card 分组
9. **管理** `/admin`（仅 admin）→ 用户表 + 全局 LLM 配置

### 遗留事项

- `apps/web/package.json` + `pnpm-lock.yaml` 显示 modified，但**净 diff 为空**（typography 装了又卸抵消），仅为 CRLF/LF 换行符抖动。可用 `git checkout -- apps/web/package.json apps/web/pnpm-lock.yaml` 还原。
- 移动端/平板响应式**未覆盖**（契约只覆盖 PC ≥1280px）。若未来需要，左/右栏折叠策略（阶段 5 的 a/b/c 抉择）需重新设计。

---

## 不在本轮范围

- 后端 API 改动（零）
- 业务逻辑改动（仅 `window.location.reload` → `invalidateQueries` 一处行为修复）
- 移动端/平板响应式
- 新功能、i18n、动画系统（除 AI 光晕外）
