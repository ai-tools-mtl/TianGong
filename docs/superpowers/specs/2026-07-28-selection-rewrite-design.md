# 选区 AI 重写（气泡菜单 + diff 审核）— 设计契约

> 日期：2026-07-28
> 状态：待评审
> 范围：`apps/web/src/components/editor/`（气泡菜单 + TiptapEditor 扩展）+ `apps/web/src/app/(app)/projects/[id]/page.tsx`（接线）+ `apps/api/app/api/sections.py` + `apps/api/app/services/diff_service.py` + `apps/api/app/schemas/diff.py`（新增 rewrite-diff 端点）
> 关联：复用已有 `astream_rewrite`（后端 SSE 流式）+ `compute_section_diff` / `apply_diff_to_section`（diff 引擎）+ `DiffReviewPanel`（前端审核 UI）
> 视觉规范：Apple Liquid Glass skill（`F:/软件缓存/Prompthub/data/skills/apple-design-skill--1b293375/repo/SKILL.md`）

---

## 1. 目标与范围

### 1.1 做什么

补齐已有但未接 UI 的"选区 AI 重写"链路。后端 `astream_rewrite` + `streamRewrite` API 早已存在，但前端编辑器无任何"选中文字 → 重写"入口。本 spec 给它接一个符合 Apple Liquid Glass 美学的气泡菜单，重写结果走已有的 diff 审核流程（用户逐 hunk 接受/拒绝，符合专利场景严谨性）。

### 1.2 用户故事

> 用户在编辑器选中"本发明**涉及**一种机械装置"中的"涉及"二字 → 选区上方浮现液态玻璃气泡 `[✨ AI 重写]` → 点开输入"改成更专业的表述" → 气泡内流式展示 AI 输出"归属于" → 流式结束自动触发 diff 审核面板 → 用户看到整章上下文里的这一处替换 → 接受/拒绝 → 应用到章节。

### 1.3 不做什么（YAGNI）

| 排除项 | 理由 |
|---|---|
| 直接原位替换（不审核） | 专利场景必须可审核可拒绝，已显式排除 |
| 选区级 diff（只看选中段） | 用户要看改动在整章的位置，已选整章级 diff |
| 批量多处同时改 | MVP 不需要，未来按需扩展 |
| `replaceSelectionWith` ref 方法 | 当前 diff 流程不经过它（apply 走后端 Tiptap 级），YAGNI |
| 移动端键盘遮挡处理 | 桌面端为主，YAGNI |
| 气泡拖动/固定 | 滚动时跟随选区或隐藏，足够 |
| 右键上下文菜单 | Apple 选区交互是气泡，不是右键菜单 |
| 右栏 AI 面板联动 | 切换视线违反"发现即处理"，方案 B 已排除 |

### 1.4 前置事实（brainstorming 取证）

**已有能力清单：**

| 能力 | 后端 | 前端 API | 前端 UI |
|---|---|---|---|
| 整章生成草稿 | ✅ `astream_generate` | ✅ `streamGenerate` | ✅ `handleGenerate` |
| 整章 diff 审核 | ✅ `compute_section_diff` | ✅ `computeDiff` | ✅ `DiffReviewPanel` |
| 应用 diff | ✅ `apply_diff_to_section` | ✅ `applyDiff` | ✅ `handleApplyDiff` |
| **选区重写** | ✅ `astream_rewrite` | ✅ `streamRewrite` | ❌ **本 spec 补齐** |

**关键发现：** 后端 `diff_service.py` 已是完整的段落级 + 字符级二级 diff（`SequenceMatcher` + `diff_match_patch`），`DiffReviewPanel` 已支持逐 hunk 接受/拒绝。本 spec 不重写这套，只接最后一块拼图。

---

## 2. 总体架构与数据流

### 2.1 组件分层

```
┌─────────────────────────────────────────────────────────────┐
│  TiptapEditor（已有，扩展 ref + 新增子组件）                 │
│  ├─ Toolbar（已有）                                          │
│  ├─ EditorContent（已有）                                    │
│  └─ SelectionBubbleMenu（新增，由 editor 实例驱动）          │
│      ├─ 折叠态：[✨ AI 重写] Liquid Glass 气泡               │
│      └─ 展开态：指令输入框 + [重写]/[停止] 按钮              │
│           ↓ streaming 完成时                                 │
│           onRewriteComplete(aiOutput, selectedText)          │
└──────────────────────┬──────────────────────────────────────┘
                       │ 回调
┌──────────────────────▼──────────────────────────────────────┐
│  page.tsx（接线层）                                          │
│  handleRewriteComplete(aiOutput, selectedText):              │
│    ├─ rewriteDiff.mutateAsync({selected_text, ai_text})      │
│    │    → POST /sections/{id}/rewrite-diff（新增端点）       │
│    ├─ setHunks(res.hunks) + setPhase('diff-review')          │
│    └─ DiffReviewPanel（已有）接管审核 → handleApplyDiff      │
└─────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  后端（新增 1 端点 + 复用已有 diff 引擎）                    │
│  POST /sections/{id}/rewrite-diff                            │
│    └─ diff_service.compute_rewrite_diff():                   │
│         1. _tiptap_to_markdown(section.content) → 原文        │
│         2. 原文.find(selected_text) → 首次出现替换成 ai_text  │
│         3. compute_section_diff(原文, 拼接后) → hunks         │
│  已有：astream_rewrite（SSE 流式重写）                        │
│  已有：apply-diff（Tiptap 级回写）                            │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 状态机

SelectionBubbleMenu 内部状态：

```
idle（无选区，气泡隐藏）
  ↓ onSelectionUpdate 检测到非空选区
ready（折叠态气泡 [✨ AI 重写]）
  ↓ 点击按钮
prompting（展开态，指令输入框 focus）
  ↓ 用户输入指令 + 点 [重写]
streaming（调 streamRewrite，气泡内流式展示 + [停止] 按钮）
  ↓ 流式完成 或 点 [停止]
done（自动关气泡 + 回调 onRewriteComplete）
```

**与 page.tsx 的 phase 联动：**
- 气泡 streaming 期间，page.tsx 的 `phase` 保持不变（不影响右栏 chat）
- 气泡 done → `onRewriteComplete` → page.tsx `setPhase('diff-review')` → `DiffReviewPanel` 接管

### 2.3 关键架构决策

**① 气泡放在 TiptapEditor 内部，不放在 page.tsx**

选区变化是高频事件（每次光标移动都触发）。若走 page.tsx 的 state，每次选区变化都重渲染整页。放编辑器内部用 ProseMirror 的 `onSelectionUpdate` 直接驱动气泡，零额外渲染开销。

**② 气泡只负责"选区 → 指令 → 流式输出"，diff 编排放回 page.tsx**

保持单一职责。气泡不碰 diff 逻辑，page.tsx 持有 `aiDraft` / `hunks` / `handleApplyDiff`（已有），气泡只是"产生 aiDraft 的另一条路径"。

**③ 整章拼接走后端（方案 B），前端零拼接**

后端已有 `_tiptap_to_markdown`（Tiptap JSON → markdown）。前端若自行转换 Tiptap→markdown 容易和后端不一致。新增 `rewrite-diff` 端点把"拼接 + diff"封装成原子操作，保证一致性。

**④ diff 计算不带乐观锁，apply 带锁**

diff 是只读操作（不写库），无需 `expected_version`。乐观锁留给后续的 `apply-diff`（已有端点，带 `expected_version`）。

---

## 3. 详细设计

### 3.1 TiptapEditor 扩展（选区 API）

`TiptapEditorRef` 从 2 个方法扩展到 4 个（精简版，不含 `replaceSelectionWith`——YAGNI）：

```typescript
// apps/web/src/components/editor/tiptap-editor.tsx
export interface TiptapEditorRef {
  insertImage: (src: string, alt: string) => void   // 已有
  getJSON: () => object                               // 已有
  // 新增
  getSelectionText: () => string                      // 选中纯文本（非空时）
  getSelectionCoords: () => { top: number; left: number; bottom: number } | null
                                                       // 选区视口坐标（气泡定位）
}
```

实现要点：
- `getSelectionText`：读 `editor.state.selection` → 用 `editor.state.doc.textBetween(from, to, '\n')` 取纯文本
- `getSelectionCoords`：用 ProseMirror 的 `view.coordsAtPos(from)` / `coordsAtPos(to)` 拿起止坐标，合并成 `{top, left, bottom}`；选区为空（from === to）时返回 `null`
- **不新增 ProseMirror plugin**：直接在 `useEditor` 配置里用 `onSelectionUpdate` 回调驱动气泡（气泡组件订阅 editor 的 selection 状态）

### 3.2 SelectionBubbleMenu 组件（Liquid Glass）

#### 视觉（Liquid Glass 规范）

气泡是**重叠层**（浮在编辑器内容之上），按 skill 规则可用 glass：

```css
/* 气泡核心样式 */
.bubble-menu {
  position: fixed;                          /* 用视口坐标定位 */
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border: 0.5px solid rgba(0, 0, 0, 0.08);  /* hairline */
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
  z-index: 50;
}
```

**字体/颜色：**
- 文字 `#1d1d1f`，辅助文字 `#86868b`
- 强调色（"重写"按钮）：Apple Blue `#0071e3`
- 灰度为主 + 一个蓝点缀，不用彩色装饰

**两个状态视觉：**

| 状态 | 视觉 |
|---|---|
| 折叠（ready） | 小气泡，单按钮 `[✨ AI 重写]`（Sparkles 图标 + 文字） |
| 展开（prompting/streaming） | 气泡展开，含 textarea 输入框（指令）+ 右侧 `[重写]` 按钮；streaming 时按钮变 `[停止]`，下方流式展示 AI 输出 |

#### 行为表

| 事件 | 行为 |
|---|---|
| `onSelectionUpdate` 检测到非空选区 | 气泡出现在选区上方（折叠态），坐标实时重算 |
| 选区清空 | 气泡消失 |
| 点 `[✨ AI 重写]` | 切换到展开态，textarea focus |
| textarea Esc | 回到折叠态 |
| 点 `[重写]`（输入非空） | 进 streaming，调 `streamRewrite(sectionId, {selected_text, instruction})` |
| streaming 中点 `[停止]` | abort AbortController，保留已生成内容，进 done，**回调 `onRewriteComplete`（传半截内容作为 aiOutput）**——用户能在 diff 审核里看到半截并决定接受/拒绝 |
| streaming 完成 | 自动关气泡 + `onRewriteComplete(aiOutput, selectedText)` |

#### Motion（按 Liquid Glass motion.md）

气泡是召唤式浮层：
- **同路径进出场**：出现/消失都从选区方向（scale 0.96→1 + opacity 0→1，不滑动）
- **可中断**：用户快速操作时不要卡动画（`transition-duration: 150ms`）
- **reduced-motion**：`@media (prefers-reduced-motion: reduce)` 时退化为纯 opacity 切换

#### 定位与边界

| 情况 | 处理 |
|---|---|
| 选区上方空间足够 | 气泡显示在选区上方（`top = selectionCoords.top - bubbleHeight - 8`） |
| 选区上方空间不够（接近编辑器顶部） | 气泡显示在选区下方（`top = selectionCoords.bottom + 8`） |
| 选区跨多段落 | `getSelectionText` 返回全部选中文字，定位用选区**起点**坐标 |
| 滚动 | `onScroll` 重新调 `getSelectionCoords` 更新坐标；若选区滚出视口则隐藏 |
| 选区是图片节点（`getSelectionText` 返回空） | 气泡不显示 |
| streaming 中选区变了 | 不影响进行中的请求，气泡保持 streaming 态直到完成 |

### 3.3 page.tsx 接线

```typescript
// apps/web/src/app/(app)/projects/[id]/page.tsx

// 新增 hook
function useRewriteDiff(sectionId: string) {
  return useMutation({
    mutationFn: (data: { selected_text: string; ai_text: string }) =>
      api.rewriteDiff(sectionId, data),
  })
}

// 在组件内
const rewriteDiff = useRewriteDiff(current?.id ?? '')

// 接收气泡回调
async function handleRewriteComplete(aiOutput: string, selectedText: string) {
  if (!current) return
  setPhase('diff-review')
  try {
    const res = await rewriteDiff.mutateAsync({
      selected_text: selectedText,
      ai_text: aiOutput,
    })
    setHunks(res.hunks)
    if (res.hunks.length === 0) {
      toast.info('AI 输出与原文无差异')
      setPhase('idle')
    }
  } catch (err: unknown) {
    const e = err as { code?: string; message?: string }
    toast.error(e?.message || '差异计算失败')
    setPhase('idle')
  }
}

// TiptapEditor 挂载处加 onRewriteComplete
<TiptapEditor
  key={current.id}
  ref={editorRef}
  content={current.content}
  onChange={handleSave}
  sectionId={current.id}
  onRewriteComplete={handleRewriteComplete}   // 新增
/>
```

**关键：** `DiffReviewPanel` / `handleApplyDiff` 已存在，零改动复用。气泡只是给 `setHunks` + `setPhase('diff-review')` 提供了"选区重写"这条新数据源。

### 3.4 后端新增端点 `rewrite-diff`

#### Schema（`apps/api/app/schemas/diff.py`）

```python
class RewriteDiffRequest(BaseModel):
    selected_text: str          # 用户选中的原文
    ai_text: str                # AI 重写后的新文本
    # 不含 expected_version：diff 计算只读，无需乐观锁
```

#### Service（`apps/api/app/services/diff_service.py`）

```python
def compute_rewrite_diff(section, selected_text: str, ai_text: str) -> list[Hunk]:
    """选区重写的整章 diff（方案 B：后端代算拼接）。

    流程：
    1. _tiptap_to_markdown(section.content) → 整章原文 markdown
    2. 原文.find(selected_text) → 首次出现位置；找不到报 ValidationError
    3. 首次出现替换成 ai_text → ai_full_text
    4. compute_section_diff(原文, ai_full_text) → hunks（复用已有函数）
    """
    from app.services.export_service import _tiptap_to_markdown
    from app.core.exceptions import ValidationError

    original = _tiptap_to_markdown(section.content) if section.content else ""
    idx = original.find(selected_text)
    if idx == -1:
        raise ValidationError("无法在章节中定位选区，请重新选择")
    ai_full = original[:idx] + ai_text + original[idx + len(selected_text):]
    return compute_section_diff(original, ai_full)
```

#### API 路由（`apps/api/app/api/sections.py`）

```python
@router.post("/sections/{section_id}/rewrite-diff", response_model=DiffResponse)
def compute_rewrite_diff(
    section_id: str,
    payload: RewriteDiffRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """计算选区重写的整章 diff（方案 B：后端拼接原文 + AI 输出）。"""
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    hunks = diff_service.compute_rewrite_diff(section, payload.selected_text, payload.ai_text)
    return DiffResponse(hunks=hunks)
```

#### 前端 API（`apps/web/src/lib/api.ts`）

```typescript
rewriteDiff: (sectionId: string, data: { selected_text: string; ai_text: string }) =>
  request<DiffResponse>(`/sections/${sectionId}/rewrite-diff`, {
    method: 'POST',
    body: data,
  }),
```

---

## 4. 边界情况与降级

| 情况 | 处理 |
|---|---|
| `selected_text` 在整章 markdown 里找不到（Tiptap→markdown 转换标点变化、或用户手改了章节） | 后端 `ValidationError`（400）→ 前端 toast"无法定位选区，请重新选择" + `setPhase('idle')` |
| AI 输出与选中文字完全相同（用户给了无意义指令） | diff 引擎返回空 hunks → 前端 toast"AI 输出与原文无差异" |
| streaming 中网络断开 | 复用 `streamRewrite` 已有的 SSE 错误处理（toast + 保留半截内容） |
| 用户连续触发多次重写（选区 A 重写未完又选 B） | 气泡单实例，新选区会 abort 旧请求 + 重新开始；不让多个流并行 |
| 选区跨多个段落 | `getSelectionText` 用 `textBetween(from, to, '\n')` 含换行，diff 引擎按段落对齐处理 |
| 章节内容为空（用户在空章节选了个换行符） | `getSelectionText` 返回空或纯空白 → 气泡不显示（ready 态不触发） |

---

## 5. 测试策略

### 5.1 后端测试（`apps/api/tests/test_diff.py` 扩展）

| 用例 | 验证点 |
|---|---|
| `test_compute_rewrite_diff_basic` | 选中"涉及"→AI 输出"归属于"，返回 1 个 replace hunk |
| `test_compute_rewrite_diff_not_found` | `selected_text` 不在章节里 → `ValidationError` |
| `test_compute_rewrite_diff_first_occurrence_only` | 选中文字多次出现，只替换首次（验证 `find` 而非 `replaceAll`） |
| `test_compute_rewrite_diff_empty_section` | section.content 为 None → 不报错（original=""） |
| `test_rewrite_diff_endpoint` | API 端到端：POST → 返回 DiffResponse |
| `test_rewrite_diff_endpoint_unauthorized` | 非章节所有者 → 404（复用 `get_section` 权限校验） |

### 5.2 前端测试

前端项目无测试基建（GOTCHAS F1/F8 提到 shadcn CLI 装不了测试组件），以**手动 dogfood** 为主。验收清单见 §6。

### 5.3 dogfood 验收清单（spec §6 验收）

- [ ] 选中文字 → 气泡在选区上方出现（折叠态）
- [ ] 选区接近顶部 → 气泡显示在下方
- [ ] 点 `[✨ AI 重写]` → 展开输入框，自动 focus
- [ ] Esc → 回折叠态
- [ ] 输入指令 + 重写 → 流式输出在气泡内展示
- [ ] streaming 中点停止 → 保留半截内容，进 diff 审核
- [ ] 流式完成 → 自动进 diff 审核面板
- [ ] diff 面板看到整章上下文里的那一处替换
- [ ] 接受/拒绝 hunk → 应用到章节
- [ ] 滚动编辑器 → 气泡跟随或隐藏
- [ ] 关闭气泡（点空白）→ 不影响编辑器其他操作

---

## 6. 实施顺序（TDD 任务预案）

按依赖关系拆 4 个 Phase，详细 TDD 步骤见配套 plan。

### Phase 1：后端 rewrite-diff 端点
- Task 1.1：`RewriteDiffRequest` schema
- Task 1.2：`diff_service.compute_rewrite_diff`
- Task 1.3：API 路由 + 6 个后端测试

### Phase 2：前端 API + hook
- Task 2.1：`api.rewriteDiff` 方法
- Task 2.2：`useRewriteDiff` hook

### Phase 3：TiptapEditor 扩展
- Task 3.1：`getSelectionText` + `getSelectionCoords` ref 方法
- Task 3.2：`onSelectionUpdate` 配置

### Phase 4：SelectionBubbleMenu 组件
- Task 4.1：组件骨架（状态机 + Liquid Glass 样式）
- Task 4.2：折叠/展开/streaming 态交互
- Task 4.3：定位 + 滚动跟随 + 边界处理

### Phase 5：page.tsx 接线 + dogfood
- Task 5.1：`handleRewriteComplete` + `onRewriteComplete` prop
- Task 5.2：dogfood 走 §6 验收清单

---

## 7. 风险与未决事项

### 7.1 已识别风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Tiptap→markdown 转换丢失格式（如加粗、列表） | diff 可能在格式标记上产生伪 hunk | `_tiptap_to_markdown` 已在生产用（export_service），可信；dogfood 观察 |
| 选区坐标在 nested scroll 容器里计算偏差 | 气泡定位不准 | 用 ProseMirror 原生 `view.coordsAtPos`（视口坐标），不用 DOM getBoundingClientRect 累加 |
| 多次重写并发 | 用户快速操作可能触发多个流 | 气泡单实例 + 新选区 abort 旧请求（AbortController） |

### 7.2 显式推迟到 backlog

| 事项 | 触发条件 |
|---|---|
| 直接原位替换（跳过 diff） | dogfood 后用户反馈"diff 太重，想要快速替换" |
| 选区级 diff（只看选中段） | dogfood 后用户反馈"整章 diff 太长" |
| 多选区批量重写 | 真实场景需要时 |
| 移动端键盘遮挡处理 | 移动端用户增多时 |

### 7.3 未决事项

无。所有设计决策已在 brainstorming §1-§6 中敲定：
- 触发：选区气泡菜单
- 落地：走现有 diff 审核流程
- diff 范围：整章级
- 整章拼接：后端代算（方案 B）
- TiptapEditorRef：只加 `getSelectionText` + `getSelectionCoords`（不加 `replaceSelectionWith`）

---

## 8. 验收标准

1. **功能验收（dogfood）：** §6 验收清单全部通过
2. **测试验收：** 后端 6 个新测试通过 + 现有 diff 测试零回归
3. **代码验收：**
   - `TiptapEditorRef` 扩展为 4 个方法（`insertImage` / `getJSON` / `getSelectionText` / `getSelectionCoords`）
   - 新增 `SelectionBubbleMenu` 组件（Liquid Glass 样式）
   - 新增后端端点 `POST /sections/{id}/rewrite-diff` + `compute_rewrite_diff` service 函数
   - `page.tsx` 接 `onRewriteComplete`，复用已有 `DiffReviewPanel` + `handleApplyDiff`
4. **视觉验收：** 气泡符合 Apple Liquid Glass 规范（glass 仅在浮层、hairline 边框、灰度为主 + 一个蓝点缀、同路径进出场动画）

---

## 附录 A：brainstorming 决策记录

本 spec 源自一次 brainstorming 会话，关键决策链：

| 问题 | 决策 |
|---|---|
| Q1 触发方式 | 选区气泡菜单（vs 右栏联动 / 右键菜单） |
| Q2 落地策略 | 走现有 diff 审核流程（vs 直接替换 / 浮层预览） |
| Q3 diff 范围 | 整章级（vs 选区级） |
| Q4 主方案 | 方案 A：气泡内输入指令 + 流式 + diff 审核 |
| Q5 整章拼接 | 方案 B：后端代算（vs 前端转换 / JSON 遍历） |
| Q6 TiptapEditorRef | 只加 2 个方法（不加 `replaceSelectionWith`） |

**核心洞察：** 项目的 diff/apply 系统已完整存在，只缺"选区重写"的 UI 入口。工作量从"做 C 方案 2-3 周"缩到"接 UI 1-3 天"。
