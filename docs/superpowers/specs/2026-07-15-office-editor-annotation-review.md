# 天工 TianGong — Office 风格编辑器 + 批注式审查工作流设计文档

> 日期：2026-07-15
> 目标：将编辑器升级为 Office 风格（Word 工具栏 + A4 页面 + 标尺 + 真分页），并将审查结果从独立报告页改为文档内批注 + 接受/拒绝工作流。
> 关联：本文档是 [MVP 设计文档](./2026-07-13-tiangong-mvp-design.md) 的 P1 增强扩展，对应设计 11.2「全篇质量检查报告」+ 编辑体验升级。

---

## 1. 背景与动机

P0 全部完成后，系统的核心创作→审查→归档链路已跑通。但两个体验瓶颈阻碍真实使用：

1. **审查结果与编辑脱节**：当前审查输出在独立 `/review` 页面，用户看到"技术方案缺替代实施方式"后要切回编辑页手动找对应位置修改——来回切换、无法定位、无法一键应用建议。
2. **编辑器体验粗糙**：当前 Tiptap 只有 6 个简陋按钮（B/I/H2/H3/列表），无字体/字号/颜色/对齐，无 A4 页面感，与代理人熟悉的 Word/WPS 差距大。

本设计将这两个问题一起解决：**Office 风格编辑器 + 批注式审查**——审查结果以批注形式出现在文档右侧侧栏，锚定到文档具体位置，用户逐条「接受」（AI 替换原文）/「拒绝」（保留原样），消除审查→编辑的来回切换。

## 2. 三大模块概览

| 模块 | 内容 | 依赖 |
|---|---|---|
| ① 审查引擎增强 | 跨章节一致性检查 + 问题定位到章节 + 严重程度分级 | 现有 review_service |
| ② 批注系统 | 自定义 Tiptap Mark + 批注侧栏 + 接受/拒绝工作流 | ① 的输出 + Tiptap |
| ③ Office 样式编辑器 | Word 风格工具栏 + A4 容器 + 标尺 + 真分页 | Tiptap（无 Pro 依赖） |

## 3. 审查引擎增强（模块①）

### 3.1 与现有审查的关系

融入现有 `run_review`，不新增独立端点。在现有 Rubric 维度评分（②）之后插入两个新阶段：

```
① load（不变）
② score：Rubric 维度评分（prompt 增强：输出 applies_to）
②b consistency_check：跨章节一致性检查（新增）
②c locate_and_classify：问题定位与分级（新增）
③ aggregate：聚合总分 + 生成摘要（增强）
④ persist：存 ReviewRecord + 生成 Annotation 记录（增强）
```

`quality_report` 技能开关（设计 7.4，已在 Plan 12 定义为 BUILTIN_SKILLS 占位）控制 ②b/②c 是否执行——禁用时退化为现有审查行为。

### 3.2 跨章节一致性检查（②b）

单次 LLM 调用 + 结构化 prompt。检查关键章节对的逻辑一致性：

| 检查对 | 检查内容 |
|---|---|
| 背景技术 ↔ 技术方案 | 技术方案是否解决了背景技术提出的问题 |
| 技术方案 ↔ 有益效果 | 有益效果是否由技术方案产生 |
| 技术方案 ↔ 具体实施方式 | 实施方式是否与技术方案一致 |

Prompt 输出结构化 JSON：
```json
{
  "issues": [
    {
      "pair": ["background", "solution"],
      "description": "背景技术提到XX问题，但技术方案未直接解决该问题",
      "severity": "warning",
      "anchor_text": "本发明未涉及XX问题的解决方案"
    }
  ]
}
```

`anchor_text` 是被批注的原文片段，用于前端定位批注位置。

### 3.3 问题定位与分级（②c）

合并 ② 的 Rubric 维度 suggestion + ②b 的一致性 issues，按章节归类 + 分三级：

| 级别 | 判定规则 | 来源 |
|---|---|---|
| **critical（严重）** | 跨章节矛盾、关键章节缺失或为空 | ②b 一致性 issues（severity=critical） |
| **warning（建议）** | Rubric 维度分数 < 70 的改进建议 | ② Rubric suggestion |
| **suggestion（优化）** | Rubric 维度分数 70-85 的优化点 | ② Rubric suggestion |

每个问题带：
- `applies_to: [section_key]` — 关联到哪个章节
- `anchor_text: str` — 被批注的原文片段（用于前端定位）
- `suggestion: str | None` — AI 建议的修改内容（"接受"时替换原文用）

### 3.4 ReviewRecord 新增字段

```python
# 新增到 ReviewRecord 模型
section_health: dict       # {section_key: {"score": int, "status": "good|warning|critical"}}
classified_issues: list    # 合并后的问题列表（含 severity/applies_to/anchor_text）
summary: str               # 整体评价摘要（1-2 句话，LLM 生成）
```

### 3.5 审查输出为批注

审查完成后，除了存 ReviewRecord，还为每个 classified_issue 生成一条 **Annotation 记录**（见模块②），status=pending。前端收到审查结果后加载批注到编辑器。

---

## 4. 批注系统（模块②）

### 4.1 技术方案：自建，不依赖 Tiptap Pro

Tiptap 的 `TrackedChanges` 和 `CommentsKit` 是 Pro 付费扩展。本设计自建批注系统：
- **自定义 Tiptap Mark**（`comment` mark，带 `annotationId` 属性）标记被批注的文本范围
- **批注数据存外部**（Annotation 表，不嵌在文档 JSON 里），通过 Mark 的 annotationId 关联
- **ProseMirror Decoration** 做高亮渲染（非破坏式，不改文档状态）

社区有成熟实践（[Dev.to: Google Docs-like commenting in Tiptap](https://dev.to/sereneinserenade/how-i-implemented-google-docs-like-commenting-in-tiptap-k2k)）。

### 4.2 数据模型

新增 `Annotation` 实体：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK CASCADE | |
| section_id | UUID FK CASCADE | |
| review_record_id | UUID FK CASCADE | 关联哪轮审查产生 |
| anchor_text | str | 被批注的原文片段（用于重新定位） |
| severity | str | critical / warning / suggestion |
| title | str | 问题标题 |
| description | str | 问题描述 |
| suggestion | str nullable | AI 建议的修改内容（"接受"时替换原文） |
| status | str | pending / accepted / rejected |
| resolved_at | datetime nullable | 接受/拒绝时间 |
| created_at / updated_at | datetime | TimestampMixin |

### 4.3 批注锚定策略

文档编辑后字符偏移会失效，采用**文本搜索重新定位**策略：

1. 审查时 LLM 输出 `anchor_text`（被批注的原文片段）
2. 前端加载章节内容时，在 Tiptap 文档中搜索该片段
3. 找到 → 用 `editor.commands.setTextSelection({from, to})` 定位 + `editor.commands.setMark('comment', {annotationId})` 标记高亮
4. 找不到（文档已改）→ 降级为章节级批注（锚定到章节标题，不标记具体文本，侧栏仍显示）

### 4.4 批注侧栏交互

- 列出当前章节所有 pending 批注，按 severity 分组（严重/建议/优化）
- 每条批注卡片：severity 图标 + 标题 + 描述 + 建议内容预览
- **「接受」按钮**：`editor.chain().setTextSelection({from,to}).deleteSelection().insertContent(suggestion).run()` → 标记 annotation.status=accepted → 移除高亮 Mark → 内容变更触发防抖保存（复用 Plan 9 乐观锁）
- **「拒绝」按钮**：标记 annotation.status=rejected → 移除高亮 Mark
- 点击批注卡片 → 编辑器滚动到对应位置 + 临时高亮
- 顶部 tab 切换：待处理 / 已接受 / 已拒绝

### 4.5 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/sections/{section_id}/annotations` | 列出章节的批注（可按 status 过滤） |
| GET | `/projects/{project_id}/annotations` | 列出项目的全部批注 |
| POST | `/annotations/{id}/accept` | 接受批注（返回建议内容供前端替换） |
| POST | `/annotations/{id}/reject` | 拒绝批注 |
| DELETE | `/annotations/{id}` | 删除批注（仅 pending 可删） |

accept 端点返回 `{suggestion, anchor_text}`，前端拿到后执行编辑器替换。实际的内容替换在前端 Tiptap editor 上操作（后端只更新 Annotation.status），替换后的内容通过现有的防抖保存 PATCH 持久化。

---

## 5. Office 风格编辑器（模块③）

### 5.1 Word 风格工具栏

替换当前简陋的 6 按钮工具栏。新增 Tiptap 扩展：

| 扩展 | 功能 |
|---|---|
| `@tiptap/extension-text-style` | 文本样式基础（字号等依赖） |
| `@tiptap/extension-font-family` | 字体选择 |
| `@tiptap/extension-color` + `@tiptap/extension-text-style` | 字体颜色 |
| `@tiptap/extension-highlight` | 背景高亮 |
| `@tiptap/extension-underline` | 下划线 |
| `@tiptap/extension-text-align` | 对齐方式 |
| `@tiptap/extension-text-style` + 自定义 | 字号（通过 attrs） |

工具栏布局（Office 功能区风格）：
- **字体组**：字体下拉 + 字号下拉 + 增大/减小字号
- **格式组**：加粗 / 斜体 / 下划线 / 删除线
- **颜色组**：字体颜色 / 背景色
- **段落组**：左对齐 / 居中 / 右对齐 / 两端对齐 / 增加缩进 / 减少缩进
- **结构组**：H1/H2/H3 / 无序列表 / 有序列表

### 5.2 A4 页面容器

编辑区套 A4 比例容器：
- 固定宽度 820px（A4 @ 96dpi 的 210mm≈794px，取整 820 含内边距）
- 白底 + `box-shadow` 模拟纸张悬浮
- 居中显示在编辑区
- 默认页边距：上下 2.54cm（96px）、左右 3.18cm（120px）

### 5.3 标尺

顶部水平标尺组件：
- 刻度以 cm 为单位（0-21cm，A4 宽度）
- 左右各一个可拖拽的页边距控制点（三角形滑块）
- 拖拽时实时调整 A4 容器的 `padding-left` / `padding-right`
- 标尺刻度与实际页边距联动

实现：React 组件 + `onMouseDown/Move/Up` 拖拽 + 状态管理。不依赖 Tiptap，纯 CSS 定位层。

### 5.4 真分页渲染

内容超出 A4 一页高度时自动分页：
- 每页固定高度（A4 高度 297mm ≈ 1123px @ 96dpi，减去上下页边距 ≈ 930px 内容区）
- 内容区用 CSS `column-width` + `column-gap` 实现多列分页效果（每列 = 一页）
- 页间用 `column-gap` + 背景留白模拟页间距
- 底部页码显示（第 N 页）

实现策略（CSS column 方案）：
```css
.a4-content {
  column-width: 820px;
  column-gap: 40px;  /* 页间距 */
  height: 930px;     /* 单页内容高度 */
}
```

ProseMirror 内容流入 column 布局后自然分页。**不做 ProseMirror 级别的精确分页计算**（测量每个节点高度 + 手动插入分页符），那是极高复杂度，MVP 用 CSS column 近似。

### 5.5 三栏布局调整

当前三栏：左大纲(240px) + 中编辑器(1fr) + 右AI面板(360px)。

新增批注侧栏后变为四区：
- 左：章节大纲（240px，可折叠）
- 中：A4 编辑器（居中，固定 820px 宽度）
- 右上：AI 对话面板（360px，可折叠）
- 右下/右侧：批注侧栏（300px，可折叠）

布局取舍：AI 面板和批注侧栏**不能同时占右栏**（空间不够）。方案：
- 默认显示批注侧栏（审查后查看批注时）
- AI 面板和批注侧栏用 tab 切换（同一个右栏区域）
- 或：批注侧栏作为浮动面板（类似 VS Code 的 Problems 面板），不占固定列宽

MVP 选择：**右栏 tab 切换**（AI 对话 / 批注列表），共享 360px 宽度。

---

## 6. 数据流

```
用户点「执行审查」（在编辑器页面，不再跳转 /review 页）
  → POST /projects/{id}/review
  → run_review:
      ② Rubric 评分（带 applies_to + anchor_text）
      ②b 一致性检查（单次 LLM）
      ②c 问题定位 + 分级
      ③ 聚合 + 生成 summary
      ④ 存 ReviewRecord（含 section_health/classified_issues/summary）
         + 为每个 issue 创建 Annotation 记录（status=pending）
  → 前端收到 ReviewRecord + Annotation 列表
  → 编辑器加载批注：
      → 在文档中搜索 anchor_text → 定位 → setMark('comment') 高亮
      → 找不到的降级为章节级批注
  → 批注侧栏展示 pending 批注列表（按 severity 分组）
  → 用户逐条操作：
      「接受」→ 前端 editor 替换原文为 suggestion → POST /annotations/{id}/accept
              → 内容变更触发防抖保存 PATCH（复用 Plan 9 乐观锁）
      「拒绝」→ POST /annotations/{id}/reject → 移除高亮 Mark
  → 批注侧栏更新状态
```

---

## 7. 涉及文件

### 模块① 审查引擎增强

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 | `ai/rubric_prompts.py` | 新增 `build_consistency_prompt` + 修改 `build_score_prompt` 加 applies_to/anchor_text 输出 |
| 后端 | `services/review_service.py` | 新增 `_check_consistency` + `_locate_and_classify` + 生成 Annotation + summary |
| 后端 | `models/review_record.py` | 新增 `section_health`/`classified_issues`/`summary` 字段 |
| 后端 | 迁移 | `add_review_report_fields` |
| 后端 | `api/review.py` | `_record_to_dict` 输出新字段 |
| 测试 | `tests/test_review.py`（新/扩展） | 一致性检查 + 问题分级 + applies_to |

### 模块② 批注系统

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 | `models/annotation.py`（新）+ 迁移 | Annotation 实体 |
| 后端 | `services/annotation_service.py`（新） | CRUD + accept/reject |
| 后端 | `api/annotations.py`（新）+ `router.py` | 批注 API 端点 |
| 前端 | `editor/comment-mark.ts`（新） | 自定义 Tiptap Mark |
| 前端 | `components/annotation-sidebar.tsx`（新） | 批注侧栏 + 接受/拒绝 |
| 前端 | `lib/queries.ts` + `types/api.ts` | annotation hooks + 类型 |
| 前端 | `lib/api.ts` | annotation API 方法 |
| 测试 | `tests/test_annotations_review.py`（新） | 审查生成批注 + accept/reject |

### 模块③ Office 样式编辑器

| 层 | 文件 | 改动 |
|---|---|---|
| 前端 | `editor/office-toolbar.tsx`（新） | Word 风格工具栏 |
| 前端 | `editor/ruler.tsx`（新） | 标尺组件 |
| 前端 | `editor/a4-page.tsx`（新） | A4 容器 + 分页 |
| 前端 | `editor/tiptap-editor.tsx` | 重构：集成新扩展 + A4 + 标尺 + 工具栏 |
| 前端 | `app/(app)/projects/[id]/page.tsx` | 四区布局 + 批注/AI tab 切换 |
| 前端 | `package.json` | 新 Tiptap 扩展依赖 |
| 前端 | `app/globals.css` | Office 样式 + 批注高亮 + A4 + 标尺 CSS |

---

## 8. 取舍

- **批注锚定用文本搜索而非精确偏移**：文档编辑后偏移失效，`anchor_text` 搜索更鲁棒，找不到降级为章节级。
- **接受修改用预生成 suggestion**：审查时 LLM 输出建议替换文本，"接受"时直接替换，不再调 LLM。
- **真分页用 CSS column 方案**：不做 ProseMirror 级精确分页（测量节点高度+手动分页符），用 CSS `column-width` 近似，复杂度可控。
- **标尺页边距不持久化**：MVP 每次打开用默认页边距，拖拽调整仅当前会话有效。持久化到 Project metadata 是 P2。
- **AI 面板与批注侧栏共享右栏 tab**：空间不够同时展示，用 tab 切换。
- **不引入 Tiptap Pro**：自建 CommentMark + Decoration，免费可控。
- **审查入口从 /review 页移到编辑器内**：不再跳转独立页面，审查按钮直接在编辑器顶栏，结果就地展示为批注。原有 /review 页保留（只读查看历史审查记录）。

---

## 9. 非目标（本设计明确不做）

- Tiptap Pro 付费扩展（TrackedChanges/CommentsKit）
- ProseMirror 级精确分页计算
- 标尺页边距持久化
- 多人实时协作批注（批注是单人审查→修改工作流）
- 批注回复/讨论线程（MVP 每条批注单轮接受/拒绝，不做多轮讨论）
- 手动添加批注（MVP 批注仅由审查引擎自动生成，用户不手动标注）
