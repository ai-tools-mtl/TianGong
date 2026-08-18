# 连续文档视图（单章/全文双模式）— 设计契约

> 版本 v1.1（2026-08-18）。由 `/grill-me` 设计访谈产生。访谈对象未实时作答，**全部决策采用推荐项**（§2 表格逐条记录否决理由与反悔成本，任何一条可单点反悔，不牵动其余）。实施计划见 `plans/2026-08-18-continuous-document-view-plan.md`。
> **已实施（2026-08-18，两批合并 main）**：批 1 核心渲染 `5fc076e`（双模式状态/SectionBlock/中栏渲染/per-section 引用表/内容缓存）· 批 2 AI 跟随 `ec069ee`+`7fc9f66`（getPhase 忙碌锁/滚动停稳跟随/编辑锁/深链滚动定位）。实施中两处与 v1.1 文本的偏差：图章组件入「章块内」而非「章头行内」（组件是展开式面板，§3.7 已更正）；批 1 计划中独立的 drawings 提交与批 2 独立的深链提交均因同文件行级耦合并入相邻提交（计划 §Task 4 已注明）。
> v1.1 自查修订（源码级复核后）：① 单例 `editorRef` 在多实例同挂下指向最后挂载实例会插错章节 → 改 per-section 引用表（§3.3/§3.7）；② 快速回切章节时查询 refetch 未落地、编辑器挂载读 `section.content` 会内容回退 → 加每章内容缓存（§3.5）；③ 编辑锁只看焦点会粘死（滚轮滚动不失焦）→ 加「激活章在视口内」判定（§3.2）；④ phase `done` 的待审草稿会被滚动切换静默丢弃 → `done`/`diff-review` 计入忙碌锁（§3.2）。另补模式切换 flush、正文点击激活瑕点、重挂载性能观察与备选（§3.9）。
> 触发背景：用户反馈「分章节撰写不好浏览全文、内容不直观、写作不全局」。结论：分章生成不动，缺的是工作区内的「合着读/合着写」入口。
> 约束场景：PC 端（≥1280px），延续 UI 契约 `2026-07-14-ui-redesign-contract.md`；三栏工作台壳不变，只改中栏内容形态。

## 1. 目标与范围

### 1.1 问题

- 工作区内永远只显示单章；全文只能去独立只读路由 `/preview`，切出即断写流、不可编辑。
- 左栏大纲只有标题 + 状态点，无任何内容预览。
- 前后呼应、附图编号、术语一致性只能靠记性——「写作不全局」是真实痛点。
- 系统侧全局意识已具备（`context_assembler` 注入已写章节 + 术语表），缺的是**人**的全局入口。

### 1.2 目标

工作区中栏加「单章 / 全文」双模式切换。全文模式 = 连续文档视图：各章按 `order` 纵向堆叠、可连续滚动浏览；「激活章」唯一可编辑；AI 右栏、顶栏操作、左栏大纲高亮全部跟随激活章。

### 1.3 范围内

| 项 | 内容 |
|---|---|
| 双模式切换 | 中栏顶栏切换按钮；模式选择持久化 localStorage（并入 ui store） |
| 连续渲染 | 各章纵向堆叠：章头（标题 + 状态徽标）+ 章块动作（图纸章）+ 编辑器 |
| 激活章机制 | 点击 / 滚动停稳自动跟随 + 两把锁（编辑中锁定 / AI 忙碌锁定） |
| AI 面板跟随 | 面板绑定激活章（现有按章重置语义）；忙碌锁保证不打断进行中会话 |
| 顶栏操作 | 确认完成 / 版本作用激活章；h1 显示激活章标题 + 状态 |
| 深链兼容 | `?section=` 与 revision「前往」在连续模式下激活 + 滚动定位 |
| 图纸章 | FigureUpload / FigureGenerate 移入 drawings 章头，点击先激活 |

### 1.4 明确不做（去范围）

- **后端任何改动**：无新端点、无 schema 变更——`useSections` 已返回全量章节含 `content`（`Section.content`），连续模式零新增 API。
- **`/preview` 页**：保留不动（它是有项目元信息头的干净整页阅读面；全文模式是三栏工作区，二者定位不同）。
- **多章同时可编辑**：同一时刻只有激活章一个可编辑实例（§3.3 理由）。
- **左栏大纲内容摘要 hover**：顺带观察项，不纳入本期。
- **移动端 / 平板**：延续 UI 契约 PC 端唯一目标场景。
- **全文模式下新增 AI 能力**：对话 / 生成 / 修订 / diff 审核管线零改动，只改「面板跟哪一章」。
- **章头 sticky**：v1 不做，未来若文档超长再议。

## 2. grill 决策摘要（10 钉）

| # | 决策点 | 结论 | 否决项（想反悔先回应） |
|---|---|---|---|
| 1 | 模式关系 | **双模式并存切换**：单章模式仍是 AI 生成/对话/diff 审核主战场；全文模式专攻浏览与连贯写作 | 「全面替换」牵动确认/版本/diff/图章等全部按章机制，风险与收益不成比例；「全文为主」把生成流放进长文档，心智负担更高 |
| 2 | 激活章切换 | **点击（大纲/章头）立即 + 滚动停稳 500ms 自动跟随**，受两把锁约束（§3.2）：编辑中锁定（含视口判定）、AI 非 idle 锁定（含待审草稿） | 「钉住激活章」最稳但每写一章多点一次，牺牲了「写哪谈哪」的流畅；「无锁跟随」会打断进行中会话/输入，还会静默丢弃待审草稿 |
| 3 | 编辑语义 | **激活章唯一可编辑**，其余章节只读渲染；配合滚动跟随即「滚到哪写到哪」 | 多章同可编辑 → 保存状态机 ×N、防抖/确认/乐观锁全部按章复制，crossover 风险面放大；单可编辑实例完整复用现有保存机制（§4） |
| 4 | 渲染策略 | 非激活章用**只读 TiptapEditor**（preview 同款，7 只读实例已验证可行），激活章用可编辑实例，`key` 强制重挂载 | `generateHTML` 新渲染路径引入样式分叉；懒挂载导致滚动时编辑器挂卸、选区丢失 |
| 5 | AI 面板绑定 | **绑定激活章**（`sectionId` prop 零改动，按章重置是现有语义） | 面板改绑导致对话显示重置是现状而非回归；两把锁保证进行中不被夺权 |
| 6 | 顶栏操作分布 | 确认完成/版本作用**激活章**，h1 显示激活章标题+状态；预览/审查/检索/术语/导出/更多保持项目级 | 操作下放每章章头 ×8 噪音大；h1 明确显示作用对象即可防误操作 |
| 7 | 工具条/选区气泡 | 只渲染激活章（`editable` 条件化，现有代码已如此） | — |
| 8 | 默认模式 | **localStorage 记住上次选择**（ui store persist version 1→2） | 「永远默认单章」则新能力不可见，等于没做 |
| 9 | 预览页 | **保留不动** | 删除需把项目元信息头迁入工作区；全文模式是工作台不是阅读面 |
| 10 | 图纸章 | FigureUpload/Generate 入 drawings **章块**（章头之下，展开式面板不放章头行内），点击时先激活该章 | 图纸插入只能作用于可编辑实例（`setImage` 在只读实例无效），激活前置是硬约束 |

## 3. 详细设计

### 3.1 双模式与状态

- `stores/ui.ts` 新增 `editorMode: 'single' | 'continuous'` + `setEditorMode`；`persist` version 升 **2**，migrate 兜底 `editorMode ?? 'single'`（老用户 localStorage v1 无此字段）。
- 中栏顶栏最左侧放切换按钮：显示当前模式图标，点击切到另一模式。单章 `PanelTop` / 全文 `Rows3`（lucide），带 `title` + `aria-label`（「切换为全文视图」/「切换为单章视图」）。
- 单章模式：现有渲染路径**原样保留**（编辑器上方图章组件等都不动），行为零回归。

### 3.2 激活章状态机（核心）

- 复用现有 `currentId` state，语义从「当前章节」扩展为「激活章节」；单章模式下两者等价（单章模式 `currentId` 即编辑器所在章）。
- 切换触发：
  1. 大纲点击（现有 `onSelect=setCurrentId`）；
  2. 章头点击（连续模式新增）；
  3. IntersectionObserver 滚动停稳 500ms（仅连续模式，见 §3.8）。
- **两把锁**（锁生效时只允许显式点击切换，滚动跟随失效）：
  - **编辑锁**：激活编辑器**仍在视口内**且（有焦点或防抖窗口内有未 flush 输入）→ 锁定。判定：`onChange` 置 dirty（`flushPendingSave` 后清）+ `document.activeElement` 落在激活编辑器内 + IntersectionObserver 确认激活章在视口。**激活章滚出视口即视为编辑结束**——滚轮滚动不会使编辑器失焦，只看焦点锁会永久粘死，AI 面板就永远不跟随；出视口后切换时由 `flushPendingSave` 兜底保存。
  - **AI 忙碌锁**：`AIChatPanelRef` 新增 `getPhase()`；`phase` 非 `'idle'`（chatting / generating / revising / **done** / diff-review）→ 锁定。面板未挂载（右栏折叠）视为 idle。**`done` 也冻结**：生成完待审的草稿若被滚动切换，面板按章重置（ai-chat-panel.tsx:185 清 phase/hunks，草稿审核入口随之消失）等于静默丢弃——今天单章模式切章是显式点击，损失可预期；滚动跟随若把 `done` 当空闲就会意外丢稿。代价：草稿挂着不处理时滚动不跟随，用户点大纲即可显式切走（与今日行为一致）。
- 切换流程沿用现有机制：cleanup `flushPendingSave` → `setCurrentId` → 同步 `current` → 清 `lastContentRef` → 编辑器重挂载 → AIChatPanel 的 `[sectionId]` effect 自动重置。crossover 修复模式（`lastContentRef` 与 `current` 同渲染闭包配对）原样保留。**模式切换（单章⇄全文）同样先 `flushPendingSave`**——编辑器树整体重挂载，先落库保证显示与后端一致。
- 滚动定位：**点击触发**的激活切换后该章 `scrollIntoView`；滚动跟随触发的激活不 scrollIntoView（自己就在视口，避免滚动位置跳动）。

### 3.3 连续模式渲染树

```
<section 中栏>
  ├─ 顶栏：模式切换 | h1(激活章标题 + 状态徽标) | 保存态 | 项目级按钮(预览/审查/检索/术语) + 确认完成 + 更多
  ├─ revision pending 提示条（不变）
  └─ 滚动容器（现有 flex-1 overflow-y-auto）
       └─ sections.map（按 order 排序）
            └─ SectionBlock（新组件）
                 ├─ 章头：序号·标题 + 状态徽标（色点+文本：待填写/草稿中/已确认）
                 │        + drawings 章：FigureUpload / FigureGenerate 章块内（§3.7）
                 └─ TiptapEditor
                      key = `${id}-${isActive ? 'edit' : 'read'}`
                      editable = isActive
                      content = contentCache.get(id) ?? section.content   （每章内容缓存，§3.5）
                      ref = 回调 ref → editorRefs.current[id]（per-section 引用表，§3.7）
```

- **key 强制重挂载**：激活章切换时新旧两个实例都重挂载，初始 content 一律读「每章内容缓存」（§3.5）——杜绝快速回切时查询 refetch 未落地导致的最后输入回退。可编辑性切换不残留 undo 栈/选区（符合预期）。
- 正文点击也可触发激活（SectionBlock 容器 `onMouseDownCapture`），但不自动落光标——激活后需第二次点击定位插入点（v1 已知瑕点，未来可透传点击坐标用 `handleClickAt` 优化）。
- 激活章视觉标识：章头 + 编辑器容器加 accent ring / border 高亮，只读章弱化。
- 间距：章间 `space-y-6`，章内沿用现有编辑器卡片样式。
- `SectionBlock` 新组件职责：章头渲染（含状态徽标与图章动作槽）+ 只读/可编辑编辑器分支 + 点击章头回调激活。页面层只负责数据与激活章状态。

### 3.4 AI 面板绑定

- `AIChatPanel` props 零改动：`sectionId={current.id}`（current = 激活章）。
- `AIChatPanelRef` 新增 `getPhase: () => AIPhase`，供忙碌锁读状态；`AIPhase` 类型导出。
- 连续模式下滚动浏览不打断会话：两把锁保证；锁释放后滚动停稳才切换。

### 3.5 保存 / 确认 / 版本（复用现状）

- `handleSave` / `flushPendingSave` / `sendPatch` / `handleConfirm` 逻辑不动，`current` = 激活章。
- 防抖 2s → PATCH（乐观锁 `expected_version` 照旧）；确认完成 → 「章节已确认」toast；`VersionDrawer sectionId={current.id}` 照旧。
- 单可编辑实例使整套保存状态机保持单例，无需按章扩展。
- **每章内容缓存 `contentCacheRef: Map<sectionId, json>`**：`handleSave` 同步写入 `current.id`（与 `lastContentRef` 同渲染闭包配对，延续 crossover 修复模式）；编辑器挂载 content 一律读缓存（缺失回退 `section.content`）。连续模式下快速回切章节时，查询 refetch 可能尚未落地，直接读 `section.content` 会把最后输入显示回退成旧文——缓存是唯一一致来源。
- `onAppliedContent`（apply-diff 成功）除 `resetContent` 外，同步更新 `contentCacheRef` 与 `lastContentRef`，保证缓存与后端一致。

### 3.6 深链与修订任务（T2 兼容）

- `?section={key}`：定位目标章 → `setCurrentId`；连续模式下追加 `scrollIntoView`（单章模式行为不变）。
- revision pending 提示条「前往」：同样激活 + 滚动。
- AIChatPanel 的 revision `consume`（sectionKey 匹配）由现有 `[sectionId]` effect 触发，连续模式切章自动兼容，无需改动。
- 滚动定位须在目标章挂载后执行（`setCurrentId` 后的下一个 effect / `requestAnimationFrame`）——首帧未挂载时 `scrollIntoView` 无效。

### 3.7 图纸章

- 连续模式：FigureUpload / FigureGenerate 渲染在 drawings **章块内（章头之下、编辑器之上，与单章模式同构）**；两个组件是展开式面板而非小按钮，不放章头行内。点击时若该章非激活章，先 `setCurrentId` + `scrollIntoView`（§2 钉 10 的硬约束）。
- **插入目标用 per-section 引用表 `editorRefs.current[drawingsId]`**（§3.3）——单例 ref 在多编辑器同挂下指向最后挂载实例，会把图插进别的章。两个组件的插入路径都发生在异步 UI（文件选择 / LLM 生成）之后，激活先行的时序安全。
- 单章模式：保持现状（组件在编辑器上方），不动。

### 3.8 滚动跟随（IntersectionObserver）

- 仅连续模式挂载；root = 中栏滚动容器；观察各 `SectionBlock` 根元素，`threshold` 取容量的中间判定（如 block 顶部进入容器上 1/3 即候选）。
- 候选变化 → 500ms 防抖 → 无两把锁时 `setCurrentId(候选章)`。
- 大纲高亮 = 激活章（与 AI 面板/顶栏操作一致，单一真源；可视章不强求独立样式）。

### 3.9 性能与边界

- N-1 只读编辑器 + 1 可编辑：preview 页已验证 7 只读实例可行；2 万字级总量（约 8 章）可控。
- 边界：sections 为空 / 加载中沿用现有分支；单章项目全文模式 = 一个 block，无副作用；图片在只读实例正常渲染（preview 同路径）。
- **激活切换的双实例重挂载成本**：每次切换 = 两个实例各一次 JSON 解析 + 视图构建（典型章节 1-4k 字，预计 <50ms/次），且切换受 500ms 防抖约束，可接受。若 dogfood 观察到可感卡顿，备选优化：编辑器按 `section.id` 稳定挂载 + `editor.setEditable()` 运行时切换（免重挂载），实施前需探针验证 tiptap v3 `useEditor` 对 editable 变化的处理（若内部重建则优化无效）。
- 备选降级（不在本期）：若未来数十章/大量图出现卡顿，非激活章换 `generateHTML` 静态渲染。

## 4. 复用清单（源码核验）

| 现有设施 | 复用方式 |
|---|---|
〔✓〕`TiptapEditor` `editable` prop（tiptap-editor.tsx:27，preview 已用只读实例） | 非激活章只读渲染，零新渲染路径 |
〔✓〕page.tsx 保存机制：`lastContentRef` / `flushPendingSave` / `sendPatch` / `handleConfirm`（crossover 修复模式，page.tsx:59/179/197/212） | 激活章即 `current`，机制原样复用 |
〔✓〕`AIChatPanel` 按 sectionId 重置 effect（ai-chat-panel.tsx:181） | 面板绑定激活章，零 props 改动 |
〔✓〕`useSections` 全量章节含 content（queries.ts:168；`Section.content` types/api.ts:119） | 连续模式零新增 API |
〔✓〕`Section.order` 排序字段（types/api.ts:115） | 堆叠顺序 |
〔✓〕`useUIStore` persist + migrate（stores/ui.ts，version 1） | editorMode 持久化，version 升 2 |
〔✓〕`?section=` 深链 + `revision-store.launchRevision`（page.tsx:79；revision-store.ts:57） | 连续模式滚动定位追加 |
〔✓〕`STATUS_DOT` 状态色映射（section-outline.tsx:6） | 章头状态徽标同色系（或提取共享常量） |
〔✓〕`preview` 页 7 只读实例渲染（preview/page.tsx:54） | 性能可行性证据 |

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 滚动停稳误切激活章（用户刚想编辑就被夺走） | 500ms 防抖 + 编辑锁（有焦点/未 flush 且章在视口才锁）；锁释放才恢复 |
| 编辑器重挂载丢最后输入 | 切换先 `flushPendingSave`；挂载 content 读每章内容缓存（§3.5） |
| 快速回切章节内容回退（refetch 未落地就重挂载） | 每章内容缓存是唯一挂载来源（§3.5） |
| 滚轮滚动不失焦 → 焦点锁粘死、面板永不跟随 | 编辑锁加「激活章在视口内」判定（§3.2） |
| 待审草稿被滚动切换静默丢弃 | `done`/`diff-review` 计入忙碌锁；显式点击仍可切走（§3.2） |
| 单例 editorRef 在多实例下插错章节 | per-section 引用表 `editorRefs`（§3.7） |
| 只读章被误以为可编辑 | 激活章 ring 高亮 + 章头/大纲点击激活的引导；正文点击也触发激活（§3.3 瑕点说明） |
| 激活切换导致滚动位置跳动 | 仅点击触发才 `scrollIntoView`，滚动跟随触发不滚动 |
| 8+ 编辑器首挂载性能 | 只读实例成本已验证；`setEditable` 备选与 `generateHTML` 降级路径记录在案（§3.9） |
| 单章模式回归 | 单章渲染路径原样保留，切换按钮为纯增量；验收清单 §6 覆盖 |

## 6. 验收标准

- 双模式：切换即时生效；刷新/跨项目记住上次模式（localStorage）。
- 连续模式：全文纵向可滚动浏览；激活章可编辑（其余只读）；确认完成/版本/保存态作用激活章且 h1 明确显示；快速回切章节内容不回退。
- AI：面板绑定激活章；进行中会话与待审草稿（done）不被滚动夺权；生成/修订/diff 审核全链路在连续模式可用。
- 深链：`?section=` 与 revision「前往」正确定位 + 滚动。
- 图纸章：章头动作可用，点击先激活；未激活时发起生成/上传，插入仍落 drawings 章。
- 单章模式：现有全部交互零回归。
- 工程：`pnpm build` + `tsc --noEmit` + `pnpm lint` 通过；后端零改动（pytest 基线不新增失败，仅回归性确认）。
