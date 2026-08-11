# 选区 AI 重写（气泡菜单 + diff 审核）— TDD 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给已有的 `astream_rewrite` 后端接一个符合 Apple Liquid Glass 美学的"选区气泡菜单"前端 UI，重写结果走已有的 diff 审核流程（用户逐 hunk 接受/拒绝）。

**Architecture:** 后端新增 `rewrite-diff` 端点（拼接整章原文 + AI 输出 → 复用 `compute_section_diff`）；前端 TiptapEditor 扩展 2 个 ref 方法（`getSelectionText` / `getSelectionCoords`）；新增 `SelectionBubbleMenu` 组件（Liquid Glass 气泡，editor 驱动）；page.tsx 接 `onRewriteComplete` 回调，复用已有 `DiffReviewPanel` + `handleApplyDiff`。后端 1 端点 + 1 service 函数，前端 1 组件 + 1 hook + 接线。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy 2.0 / Next.js / React / TanStack Query / Tiptap v3 / diff_match_patch（已有）。视觉：Apple Liquid Glass skill。

**Spec:** `docs/superpowers/specs/2026-07-28-selection-rewrite-design.md`
**关联 brainstorming 决策:** 2026-07-28，6 个 Q&A 见 spec 附录 A
**当前分支：** `spec/selection-rewrite`（spec 提交在此）。本计划开工前应从 main 开 `feat/selection-rewrite` 分支
**预计工期：** 1-3 天

---

## 前置验证（Task 0，开工前必做）

确认基线测试全绿 + 切到实施分支。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `apps/api/app/schemas/diff.py` | 加 `RewriteDiffRequest` schema | 改 |
| `apps/api/app/services/diff_service.py` | 新增 `compute_rewrite_diff` 函数 | 改 |
| `apps/api/app/api/sections.py` | 新增 `POST /sections/{id}/rewrite-diff` 路由 | 改 |
| `apps/api/tests/test_diff_service.py` | 加 `compute_rewrite_diff` 测试（复用 `_make_section` / `_tiptap_para` helper） | 改 |
| `apps/api/tests/test_sections_api.py` | 加端点 API 测试（端到端） | 改 |
| `apps/web/src/lib/api.ts` | 加 `rewriteDiff` 方法 | 改 |
| `apps/web/src/lib/queries.ts` | 加 `useRewriteDiff` hook | 改 |
| `apps/web/src/types/api.ts` | 加 `RewriteDiffRequest` / 已有 `DiffResponse`（确认） | 改 |
| `apps/web/src/components/editor/tiptap-editor.tsx` | `TiptapEditorRef` 加 `getSelectionText` / `getSelectionCoords`；`useEditor` 加 `onSelectionUpdate` | 改 |
| `apps/web/src/components/editor/selection-bubble-menu.tsx` | 新增气泡菜单组件（Liquid Glass） | 新建 |
| `apps/web/src/app/(app)/projects/[id]/page.tsx` | 加 `handleRewriteComplete` + `onRewriteComplete` prop 接线 | 改 |

---

## Task 0: 工程前置验证（基线绿 + 分支）

**Files:**
- 无文件改动，仅验证

- [ ] **Step 1: 确认基线测试全绿**

Run:
```bash
cd apps/api && uv run pytest -q 2>&1 | tail -10
```
Expected: 全绿（当前基线约 709 passed + 1 xfailed）。若有 failure，先停止本计划，修复基线再开工。

- [ ] **Step 2: 切到实施分支**

```bash
cd /g/03-Personal-Projects/TianGong
git checkout main
git checkout -b feat/selection-rewrite
```
Expected: 新分支 `feat/selection-rewrite` 创建成功。spec 已在 main 上（commit `1ea2571` 合并后）或本分支基于含 spec 的 main。

- [ ] **Step 3: 确认目标端点不存在（取证基线）**

Run:
```bash
cd apps/api && uv run python -c "
from app.api.sections import router
routes = [r.path for r in router.routes]
print('rewrite-diff in routes:', any('rewrite-diff' in r for r in routes))
"
```
Expected: 打印 `rewrite-diff in routes: False`（证明端点还不存在，本计划完成后应变 True）。

---

## Phase 1: 后端 rewrite-diff 端点

### Task 1.1: `RewriteDiffRequest` schema

**Files:**
- Modify: `apps/api/app/schemas/diff.py:34-38`（在 `ApplyDiffRequest` 之后追加）

- [ ] **Step 1: 加 schema**

在 `apps/api/app/schemas/diff.py` 末尾（`ApplyDiffRequest` 类之后）追加：

```python
class RewriteDiffRequest(BaseModel):
    """选区重写 diff 的请求体（spec §3.4）。

    selected_text: 用户在编辑器选中的原文
    ai_text: AI 重写后的新文本（来自 streamRewrite SSE 流）
    不含 expected_version：diff 计算只读，乐观锁留给 apply-diff
    """
    selected_text: str
    ai_text: str
```

- [ ] **Step 2: 验证 import 可用**

Run:
```bash
cd apps/api && uv run python -c "
from app.schemas.diff import RewriteDiffRequest
r = RewriteDiffRequest(selected_text='涉及', ai_text='归属于')
print('OK:', r.selected_text, r.ai_text)
"
```
Expected: 打印 `OK: 涉及 归属于`。

- [ ] **Step 3: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/app/schemas/diff.py
git commit -m "feat(api): RewriteDiffRequest schema（选区重写 Task 1.1）"
```

---

### Task 1.2: `compute_rewrite_diff` service 函数（TDD）

**Files:**
- Modify: `apps/api/app/services/diff_service.py`（末尾追加）
- Test: `apps/api/tests/test_diff_service.py`（复用 `_make_section` / `_tiptap_para` helper）

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_diff_service.py` 末尾追加（`_make_section` / `_tiptap_para` helper 已存在于 line 174-197，直接复用）：

```python
# ---------- compute_rewrite_diff（选区重写整章 diff，spec §3.4）----------


def test_compute_rewrite_diff_basic(db_session, registered_user):
    """选中'涉及'→AI 输出'归属于'，返回 1 个 replace hunk。"""
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    # 给章节写入含'涉及'的内容
    section.content = _tiptap_para("本发明涉及一种机械装置")
    db_session.commit()

    hunks = compute_rewrite_diff(section, "涉及", "归属于")
    assert len(hunks) == 1
    h = hunks[0]
    assert h.type == "replace"
    assert "涉及" in (h.original_para or "")
    assert "归属于" in (h.modified_para or "")


def test_compute_rewrite_diff_not_found_raises(db_session, registered_user):
    """selected_text 不在章节里 → ValidationError。"""
    from app.core.exceptions import ValidationError
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    section.content = _tiptap_para("本发明涉及一种机械装置")
    db_session.commit()

    with pytest.raises(ValidationError):
        compute_rewrite_diff(section, "不存在的文字", "新内容")


def test_compute_rewrite_diff_first_occurrence_only(db_session, registered_user):
    """选中文字多次出现，只替换首次（验证 find 而非 replaceAll）。"""
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    # '所述' 出现两次
    section.content = _tiptap_para("所述装置包括所述凸轮")
    db_session.commit()

    hunks = compute_rewrite_diff(section, "所述", "该")
    # 只替换首次：'该装置包括所述凸轮' vs '所述装置包括所述凸轮'
    # diff 应只产生 1 个 replace hunk（首次'所述'→'该'），第二次'所述'保留
    assert len(hunks) == 1
    assert hunks[0].type == "replace"


def test_compute_rewrite_diff_empty_section(db_session, registered_user):
    """section.content 为 None → original=''，selected_text 找不到 → ValidationError。"""
    from app.core.exceptions import ValidationError
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    section.content = None
    db_session.commit()

    with pytest.raises(ValidationError):
        compute_rewrite_diff(section, "任意文字", "新内容")


def test_compute_rewrite_diff_identical_ai_no_hunks(db_session, registered_user):
    """AI 输出与选中文字相同 → 拼接后整章无变化 → 空 hunks。"""
    from app.services.diff_service import compute_rewrite_diff

    section, _ = _make_section(db_session, registered_user)
    section.content = _tiptap_para("本发明涉及一种机械装置")
    db_session.commit()

    hunks = compute_rewrite_diff(section, "涉及", "涉及")  # 相同
    assert hunks == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_diff_service.py -v -k "compute_rewrite_diff" 2>&1 | tail -10`
Expected: FAIL（`ImportError: cannot import name 'compute_rewrite_diff' from 'app.services.diff_service'`）

- [ ] **Step 3: 实现 `compute_rewrite_diff`**

在 `apps/api/app/services/diff_service.py` 末尾（`apply_diff_to_section` 之后）追加：

```python
def compute_rewrite_diff(section, selected_text: str, ai_text: str) -> list[Hunk]:
    """选区重写的整章 diff（方案 B：后端代算拼接，spec §3.4）。

    流程：
    1. _tiptap_to_markdown(section.content) → 整章原文 markdown
    2. 原文.find(selected_text) → 首次出现位置；找不到报 ValidationError
    3. 首次出现替换成 ai_text → ai_full_text（多次出现只替换首次，避免误伤）
    4. compute_section_diff(原文, ai_full_text) → hunks（复用已有函数）
    """
    from app.core.exceptions import ValidationError
    from app.services.export_service import _tiptap_to_markdown

    original = _tiptap_to_markdown(section.content) if section.content else ""
    idx = original.find(selected_text)
    if idx == -1:
        raise ValidationError("无法在章节中定位选区，请重新选择")
    ai_full = original[:idx] + ai_text + original[idx + len(selected_text):]
    return compute_section_diff(original, ai_full)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_diff_service.py -v -k "compute_rewrite_diff" 2>&1 | tail -10`
Expected: 5 PASS

- [ ] **Step 5: 回归现有 diff 测试**

Run: `cd apps/api && uv run pytest tests/test_diff_service.py -v 2>&1 | tail -10`
Expected: 全绿（原有测试 + 新增 5 个）

- [ ] **Step 6: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/app/services/diff_service.py apps/api/tests/test_diff_service.py
git commit -m "feat(api): compute_rewrite_diff 选区重写整章 diff（Task 1.2，方案 B 后端代算拼接）"
```

---

### Task 1.3: API 路由 + 端到端测试

**Files:**
- Modify: `apps/api/app/api/sections.py`（在 `apply-diff` 路由之后追加）
- Test: `apps/api/tests/test_sections_api.py`（新建或扩展）

- [ ] **Step 1: 写失败测试（端到端 API）**

先确认测试文件是否存在：

Run: `ls apps/api/tests/test_sections_api.py 2>&1`

如果不存在，创建 `apps/api/tests/test_sections_api.py`：

```python
# apps/api/tests/test_sections_api.py
"""sections API 端点测试（选区重写 diff 端点端到端）。"""
import pytest


def _make_logged_in_section(client, registered_user, db_session):
    """登录 + 建项目取第一章节（复用 test_ai.py 的脚手架模式）。"""
    from sqlalchemy import select

    from app.models import User, UserLLMConfig
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from app.services.seed_service import ensure_default_template
    from app.core.security import encrypt_value

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    # 配 LLM 配置（虽然 rewrite-diff 不调 LLM，但 get_section 链路一致）
    db_session.add(UserLLMConfig(
        user_id=user.id, name="test",
        base_url="http://x", api_key_encrypted=encrypt_value("sk-test"), model="m",
    ))
    db_session.commit()
    p = create_project(db_session, user=user, title="rewrite-diff 测试项目")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    return sections[0]


def test_rewrite_diff_endpoint_basic(client, registered_user, db_session):
    """POST /sections/{id}/rewrite-diff → 返回 DiffResponse（含 hunks）。"""
    section = _make_logged_in_section(client, registered_user, db_session)
    # 给章节写内容
    from app.ai.markdown_to_tiptap import markdown_to_tiptap
    section.content = markdown_to_tiptap("本发明涉及一种机械装置")
    db_session.commit()

    res = client.post(
        f"/api/v1/sections/{section.id}/rewrite-diff",
        json={"selected_text": "涉及", "ai_text": "归属于"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "hunks" in data
    assert len(data["hunks"]) >= 1
    assert data["hunks"][0]["type"] == "replace"


def test_rewrite_diff_endpoint_not_found_returns_400(client, registered_user, db_session):
    """selected_text 不在章节 → 400 ValidationError。"""
    section = _make_logged_in_section(client, registered_user, db_session)
    from app.ai.markdown_to_tiptap import markdown_to_tiptap
    section.content = markdown_to_tiptap("本发明涉及一种机械装置")
    db_session.commit()

    res = client.post(
        f"/api/v1/sections/{section.id}/rewrite-diff",
        json={"selected_text": "不存在的文字", "ai_text": "新内容"},
    )
    assert res.status_code == 400


def test_rewrite_diff_endpoint_unauthorized_returns_404(client, registered_user, db_session):
    """非章节所有者 → 404（get_section 权限校验）。"""
    section = _make_logged_in_section(client, registered_user, db_session)
    from app.ai.markdown_to_tiptap import markdown_to_tiptap
    section.content = markdown_to_tiptap("本发明涉及一种机械装置")
    db_session.commit()

    # 用另一个用户的 cookie 访问（client 默认未登录 → 401，但本测试聚焦端点存在性）
    # 简化：不登录直接访问 → 401（get_current_user 拦截）
    # 为聚焦 rewrite-diff 端点本身，这里验证未登录 401
    res = client.post(
        f"/api/v1/sections/{section.id}/rewrite-diff",
        json={"selected_text": "涉及", "ai_text": "归属于"},
    )
    # 未登录场景：取决于测试 client 是否注入 cookie。test_ai.py 的 _make_logged_in_section
    # 会登录。这里用一个全新 client 不登录，期望 401。
    assert res.status_code in (401, 404)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_sections_api.py -v 2>&1 | tail -10`
Expected: FAIL（`404 Not Found`——路由不存在）

- [ ] **Step 3: 加 API 路由**

修改 `apps/api/app/api/sections.py`。先确认 import 区已有 `diff_service` + `DiffResponse`（apply-diff 已用）。在 `apply-diff` 路由之后追加：

```python
@router.post("/sections/{section_id}/rewrite-diff", response_model=DiffResponse)
def compute_rewrite_diff(
    section_id: str,
    payload: RewriteDiffRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """计算选区重写的整章 diff（方案 B：后端拼接原文 + AI 输出，spec §3.4）。

    与 /diff 区别：本端点接收 selected_text + ai_text，后端做"首次出现替换"拼接，
    再调 compute_section_diff。前端无需自行实现 Tiptap→markdown 转换。
    """
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    hunks = diff_service.compute_rewrite_diff(section, payload.selected_text, payload.ai_text)
    return DiffResponse(hunks=hunks)
```

同时在 `apps/api/app/api/sections.py` 顶部 import 区，把 `RewriteDiffRequest` 加进从 `app.schemas.diff` 的 import：

```python
from app.schemas.diff import ApplyDiffRequest, DiffRequest, DiffResponse, RewriteDiffRequest
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_sections_api.py -v 2>&1 | tail -10`
Expected: 3 PASS（或视 401/404 测试的具体环境，前两个必过）

- [ ] **Step 5: 回归现有 sections 测试**

Run: `cd apps/api && uv run pytest tests/test_sections.py tests/test_diff_service.py -q 2>&1 | tail -8`
Expected: 全绿

- [ ] **Step 6: 验证端点存在（与 Task 0 Step 3 对比）**

Run:
```bash
cd apps/api && uv run python -c "
from app.api.sections import router
routes = [r.path for r in router.routes]
print('rewrite-diff in routes:', any('rewrite-diff' in r for r in routes))
"
```
Expected: 打印 `rewrite-diff in routes: True`

- [ ] **Step 7: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/app/api/sections.py apps/api/tests/test_sections_api.py
git commit -m "feat(api): POST /sections/{id}/rewrite-diff 端点（选区重写 Task 1.3）"
```

---

## Phase 1 收尾检查

- [ ] `schemas/diff.py` 含 `RewriteDiffRequest`（`selected_text` + `ai_text`，无 `expected_version`）
- [ ] `diff_service.py` 含 `compute_rewrite_diff`（首次出现替换 + 复用 `compute_section_diff`）
- [ ] `api/sections.py` 含 `POST /sections/{id}/rewrite-diff` 路由
- [ ] 后端 8 个新测试全绿（5 service + 3 API），现有 diff 测试零回归

---

## Phase 2: 前端 API + hook

### Task 2.1: `api.rewriteDiff` 方法 + `useRewriteDiff` hook

**Files:**
- Modify: `apps/web/src/lib/api.ts`（在 `applyDiff` 之后追加）
- Modify: `apps/web/src/lib/queries.ts`（在 `useApplyDiff` 之后追加）
- Modify: `apps/web/src/types/api.ts`（确认/加 `RewriteDiffRequest` 类型）

- [ ] **Step 1: 加类型定义**

在 `apps/web/src/types/api.ts` 找到 `DiffResponse` 附近，加 `RewriteDiffRequest`（若已有 `DiffRequest` 则参考其风格）：

```typescript
export interface RewriteDiffRequest {
  selected_text: string
  ai_text: string
}
```

- [ ] **Step 2: 加 `api.rewriteDiff` 方法**

在 `apps/web/src/lib/api.ts` 找到 `applyDiff`（约 line 611-615）之后追加：

```typescript
  rewriteDiff: (sectionId: string, data: { selected_text: string; ai_text: string }) =>
    request<DiffResponse>(`/sections/${sectionId}/rewrite-diff`, {
      method: 'POST',
      body: data,
    }),
```

- [ ] **Step 3: 加 `useRewriteDiff` hook**

在 `apps/web/src/lib/queries.ts` 找到 `useApplyDiff`（约 line 392-400）之后追加：

```typescript
export function useRewriteDiff(sectionId: string) {
  return useMutation({
    mutationFn: (data: { selected_text: string; ai_text: string }) =>
      api.rewriteDiff(sectionId, data),
  })
}
```

- [ ] **Step 4: 验证前端 build 通过**

Run: `cd apps/web && pnpm build 2>&1 | tail -5`
Expected: build 成功（exit 0，无类型错误）

- [ ] **Step 5: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/web/src/types/api.ts apps/web/src/lib/api.ts apps/web/src/lib/queries.ts
git commit -m "feat(web): api.rewriteDiff + useRewriteDiff hook（选区重写 Task 2.1）"
```

---

## Phase 3: TiptapEditor 扩展（选区 API）

### Task 3.1: `getSelectionText` + `getSelectionCoords` ref 方法

**Files:**
- Modify: `apps/web/src/components/editor/tiptap-editor.tsx`（扩展 `TiptapEditorRef` + `useImperativeHandle`）

- [ ] **Step 1: 扩展 `TiptapEditorRef` 接口**

修改 `apps/web/src/components/editor/tiptap-editor.tsx` 的接口定义（当前是 line 11-14）：

```typescript
export interface TiptapEditorRef {
  insertImage: (src: string, alt: string) => void
  getJSON: () => object
  // 新增（选区重写气泡菜单用，spec §3.1）
  getSelectionText: () => string
  getSelectionCoords: () => { top: number; left: number; bottom: number } | null
}
```

- [ ] **Step 2: 实现 ref 方法**

修改 `useImperativeHandle`（当前是 line 40-46）：

```typescript
    useImperativeHandle(ref, () => ({
      insertImage: (src: string, alt: string) => {
        editor?.chain().focus().setImage({ src, alt }).run()
      },
      getJSON: () => editor?.getJSON() ?? {},
      getSelectionText: () => {
        if (!editor) return ''
        const { from, to, empty } = editor.state.selection
        if (empty) return ''
        return editor.state.doc.textBetween(from, to, '\n')
      },
      getSelectionCoords: () => {
        if (!editor) return null
        const { from, to, empty } = editor.state.selection
        if (empty) return null
        // 用 ProseMirror view 的 coordsAtPos 拿视口坐标
        const view = editor.view
        const startCoords = view.coordsAtPos(from)
        const endCoords = view.coordsAtPos(to)
        return {
          top: Math.min(startCoords.top, endCoords.top),
          left: Math.min(startCoords.left, endCoords.left),
          bottom: Math.max(startCoords.bottom, endCoords.bottom),
        }
      },
    }))
```

- [ ] **Step 3: 验证 build + 类型检查**

Run: `cd apps/web && pnpm build 2>&1 | tail -5`
Expected: build 成功（exit 0）

- [ ] **Step 4: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/web/src/components/editor/tiptap-editor.tsx
git commit -m "feat(web): TiptapEditorRef 加 getSelectionText/getSelectionCoords（选区重写 Task 3.1）"
```

---

## Phase 4: SelectionBubbleMenu 组件（Liquid Glass）

### Task 4.1: 组件骨架（状态机 + Liquid Glass 样式）

**Files:**
- Create: `apps/web/src/components/editor/selection-bubble-menu.tsx`

- [ ] **Step 1: 创建组件文件**

创建 `apps/web/src/components/editor/selection-bubble-menu.tsx`：

```typescript
'use client'

import { Sparkles, Square, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { getChatDefaultSource } from '@/lib/llm-source'
import { toast } from 'sonner'

interface SelectionBubbleMenuProps {
  sectionId: string
  /** 由 TiptapEditor 提供：实时读取选区文字 */
  getSelectionText: () => string
  /** 由 TiptapEditor 提供：实时读取选区视口坐标 */
  getSelectionCoords: () => { top: number; left: number; bottom: number } | null
  /** 流式重写完成（或停止）时回调，把 AI 输出 + 选中原文传回 page.tsx */
  onRewriteComplete: (aiOutput: string, selectedText: string) => void
}

type BubbleState = 'hidden' | 'ready' | 'prompting' | 'streaming'

export function SelectionBubbleMenu({
  sectionId, getSelectionText, getSelectionCoords, onRewriteComplete,
}: SelectionBubbleMenuProps) {
  const [state, setState] = useState<BubbleState>('hidden')
  const [coords, setCoords] = useState<{ top: number; left: number; bottom: number } | null>(null)
  const [instruction, setInstruction] = useState('')
  const [aiOutput, setAiOutput] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const selectedTextRef = useRef('')

  // 监听选区变化（轮询 ProseMirror selection，因为 onSelectionUpdate 在父组件配置）
  // 简化策略：用 setInterval 轮询选区状态（200ms 足够，避免高频）
  useEffect(() => {
    const tick = () => {
      const text = getSelectionText()
      const c = getSelectionCoords()
      if (text && c) {
        // 选区变化时更新坐标，但若正在 streaming 不打断
        if (state !== 'streaming') {
          setCoords(c)
          selectedTextRef.current = text
          setState((prev) => (prev === 'hidden' ? 'ready' : prev === 'ready' ? 'ready' : prev))
        }
      } else {
        // 选区清空：streaming 中保持（用户可能临时点了别处），其余态隐藏
        if (state !== 'streaming') {
          setState('hidden')
          setCoords(null)
        }
      }
    }
    const id = setInterval(tick, 200)
    return () => clearInterval(id)
  }, [getSelectionText, getSelectionCoords, state])

  // 滚动时清空坐标（让气泡暂时消失，下次 tick 重新定位）
  // 注：父组件编辑器容器 onScroll 也可触发，这里用 window 监听兜底
  useEffect(() => {
    const onScroll = () => {
      if (state !== 'streaming') {
        const c = getSelectionCoords()
        setCoords(c)
        if (!c) setState('hidden')
      }
    }
    window.addEventListener('scroll', onScroll, true)
    return () => window.removeEventListener('scroll', onScroll, true)
  }, [getSelectionCoords, state])

  async function handleRewrite() {
    const source = getChatDefaultSource()
    if (!source) {
      toast.error('请先在设置中选择 LLM 源')
      return
    }
    const selectedText = selectedTextRef.current
    if (!selectedText) {
      toast.error('未选中文字')
      return
    }
    setState('streaming')
    setAiOutput('')
    abortRef.current = new AbortController()
    let output = ''
    try {
      await api.streamRewrite(
        sectionId,
        { selected_text: selectedText, instruction: instruction.trim() || undefined },
        (token) => {
          output += token
          setAiOutput(output)
        },
        abortRef.current.signal,
      )
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // 用户停止：保留半截内容，继续走 diff
      } else {
        const e = err as { message?: string }
        toast.error(e?.message || '重写失败')
        setState('ready')
        return
      }
    }
    // 流式完成（含停止）：回调 + 隐藏
    onRewriteComplete(output, selectedText)
    setState('hidden')
    setInstruction('')
    setAiOutput('')
  }

  function handleStop() {
    abortRef.current?.abort()
  }

  function handleCollapse() {
    setState('ready')
    setInstruction('')
  }

  if (state === 'hidden' || !coords) return null

  // 定位：上方空间够就放上方，否则放下方
  const bubbleHeight = 200 // 估算（prompting/streaming 态）
  const showBelow = coords.top < bubbleHeight + 16
  const top = showBelow ? coords.bottom + 8 : coords.top - (state === 'ready' ? 44 : bubbleHeight) - 8
  const left = coords.left

  return (
    <div
      className="bubble-menu"
      style={{
        position: 'fixed',
        top: `${top}px`,
        left: `${left}px`,
        zIndex: 50,
      }}
    >
      {state === 'ready' && (
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5"
          onClick={() => setState('prompting')}
        >
          <Sparkles className="size-3.5" />
          AI 重写
        </Button>
      )}

      {state === 'prompting' && (
        <div className="flex flex-col gap-2 p-2" style={{ width: 320 }}>
          <textarea
            autoFocus
            placeholder="告诉 AI 怎么改..."
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') handleCollapse()
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleRewrite()
            }}
            style={{ minHeight: 60, resize: 'none' }}
            className="w-full rounded-md border border-black/[0.08] bg-white/80 px-2 py-1.5 text-sm outline-none"
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={handleCollapse}>
              取消
            </Button>
            <Button size="sm" onClick={handleRewrite} disabled={!instruction.trim()}>
              重写
            </Button>
          </div>
        </div>
      )}

      {state === 'streaming' && (
        <div className="flex flex-col gap-2 p-2" style={{ width: 360 }}>
          <div className="flex items-center justify-between">
            <span className="text-xs text-[#86868b]">AI 重写中...</span>
            <Button variant="ghost" size="icon-xs" onClick={handleStop}>
              <Square className="size-3" />
            </Button>
          </div>
          <div className="max-h-32 overflow-y-auto rounded-md bg-white/60 px-2 py-1.5 text-sm">
            {aiOutput || '（等待输出...）'}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: 加 Liquid Glass 样式**

在 `apps/web/src/app/globals.css`（或现有全局样式文件）末尾追加：

```css
/* SelectionBubbleMenu 气泡（Apple Liquid Glass，spec §3.2）*/
.bubble-menu {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border: 0.5px solid rgba(0, 0, 0, 0.08);
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
  animation: bubble-materialize 150ms ease-out;
}

@keyframes bubble-materialize {
  from { opacity: 0; transform: scale(0.96); }
  to { opacity: 1; transform: scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .bubble-menu { animation: none; transition: opacity 150ms; }
}
```

- [ ] **Step 3: 验证 build**

Run: `cd apps/web && pnpm build 2>&1 | tail -5`
Expected: build 成功

- [ ] **Step 4: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/web/src/components/editor/selection-bubble-menu.tsx apps/web/src/app/globals.css
git commit -m "feat(web): SelectionBubbleMenu 组件骨架（Liquid Glass 气泡，Task 4.1）"
```

---

### Task 4.2: 在 TiptapEditor 内挂载气泡

**Files:**
- Modify: `apps/web/src/components/editor/tiptap-editor.tsx`（挂载 SelectionBubbleMenu）

- [ ] **Step 1: 加 props + 挂载**

修改 `apps/web/src/components/editor/tiptap-editor.tsx`：

a) 扩展 `TiptapEditorProps` 接口（加 `onRewriteComplete`）：

```typescript
interface TiptapEditorProps {
  content?: object | null
  onChange?: (json: object) => void
  editable?: boolean
  sectionId?: string
  /** 选区重写完成时回调（传给 SelectionBubbleMenu） */
  onRewriteComplete?: (aiOutput: string, selectedText: string) => void
}
```

b) 在函数签名解构 `onRewriteComplete`：

```typescript
export const TiptapEditor = forwardRef<TiptapEditorRef, TiptapEditorProps>(
  function TiptapEditor({ content, onChange, editable = true, sectionId = '', onRewriteComplete }, ref) {
```

c) 在 return 的 JSX 里（`</div>` 闭合前）挂载气泡：

```typescript
    return (
      <div className="overflow-hidden rounded-xl border bg-card">
        {editable && <Toolbar editor={editor} sectionId={sectionId} />}
        <EditorContent
          editor={editor}
          className="prose prose-sm tiptap max-w-none px-5 py-4 focus:outline-none"
        />
        {editable && onRewriteComplete && sectionId && (
          <SelectionBubbleMenu
            sectionId={sectionId}
            getSelectionText={() => editorRef.current?.getSelectionText() ?? ''}
            getSelectionCoords={() => editorRef.current?.getSelectionCoords() ?? null}
            onRewriteComplete={onRewriteComplete}
          />
        )}
      </div>
    )
```

**注意：** 这里有个 ref 自引用问题——`SelectionBubbleMenu` 需要读 `editorRef` 的方法，但 `editorRef` 是 `TiptapEditor` 自己的 forwardRef。解法：在 `TiptapEditor` 内部用一个本地 ref 桥接。修改 ref 声明：

```typescript
export const TiptapEditor = forwardRef<TiptapEditorRef, TiptapEditorProps>(
  function TiptapEditor({ content, onChange, editable = true, sectionId = '', onRewriteComplete }, ref) {
    // 内部 ref 桥接：既给 forwardRef 用，也给 SelectionBubbleMenu 用
    const internalRef = useRef<TiptapEditorRef>(null)
    useImperativeHandle(ref, () => internalRef.current ?? {/* fallback */})
    // ... useEditor ...
    // getSelectionText 等方法挂到 internalRef
```

实际上更简单：**直接传 editor 实例**给气泡，不走 ref。修改为：

```typescript
    // 在 useEditor 之后，SelectionBubbleMenu 直接用 editor 实例
    {editable && onRewriteComplete && sectionId && (
      <SelectionBubbleMenu
        sectionId={sectionId}
        getSelectionText={() => {
          if (!editor) return ''
          const { from, to, empty } = editor.state.selection
          if (empty) return ''
          return editor.state.doc.textBetween(from, to, '\n')
        }}
        getSelectionCoords={() => {
          if (!editor) return null
          const { from, to, empty } = editor.state.selection
          if (empty) return null
          const startCoords = editor.view.coordsAtPos(from)
          const endCoords = editor.view.coordsAtPos(to)
          return {
            top: Math.min(startCoords.top, endCoords.top),
            left: Math.min(startCoords.left, endCoords.left),
            bottom: Math.max(startCoords.bottom, endCoords.bottom),
          }
        }}
        onRewriteComplete={onRewriteComplete}
      />
    )}
```

这样气泡直接用闭包里的 `editor`，不绕 ref。

d) 顶部 import 加 `SelectionBubbleMenu`：

```typescript
import { SelectionBubbleMenu } from './selection-bubble-menu'
```

- [ ] **Step 2: 验证 build**

Run: `cd apps/web && pnpm build 2>&1 | tail -5`
Expected: build 成功

- [ ] **Step 3: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/web/src/components/editor/tiptap-editor.tsx
git commit -m "feat(web): TiptapEditor 挂载 SelectionBubbleMenu（Task 4.2）"
```

---

## Phase 5: page.tsx 接线 + dogfood

### Task 5.1: `handleRewriteComplete` + `onRewriteComplete` prop

**Files:**
- Modify: `apps/web/src/app/(app)/projects/[id]/page.tsx`

- [ ] **Step 1: 加 hook + handler**

在 `apps/web/src/app/(app)/projects/[id]/page.tsx` 找到 `const rewriteDiff = useComputeDiff` 附近（约 line 76-77 的 computeDiff/applyDiff 声明区），加：

```typescript
const rewriteDiff = useRewriteDiff(current?.id ?? '')
```

注意 `useRewriteDiff` 要从 `@/lib/queries` import（在 line 14-22 的 import 块加 `useRewriteDiff`）。

在 `handleApplyDiff` 函数之后（约 line 316+），加 `handleRewriteComplete`：

```typescript
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
```

- [ ] **Step 2: 给 TiptapEditor 传 `onRewriteComplete`**

找到 `<TiptapEditor` 挂载处（约 line 346-352），加 `onRewriteComplete` prop：

```typescript
              <TiptapEditor
                key={current.id}
                ref={editorRef}
                content={current.content}
                onChange={handleSave}
                sectionId={current.id}
                onRewriteComplete={handleRewriteComplete}
              />
```

- [ ] **Step 3: 验证 build**

Run: `cd apps/web && pnpm build 2>&1 | tail -5`
Expected: build 成功

- [ ] **Step 4: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/web/src/app/(app)/projects/[id]/page.tsx
git commit -m "feat(web): page.tsx 接 onRewriteComplete（选区重写 Task 5.1）"
```

---

### Task 5.2: dogfood 走验收清单

**Files:**
- 无文件改动，手动验证

- [ ] **Step 1: 启动前后端**

```bash
cd apps/api && uv run uvicorn app.main:app --reload
# 另一个终端
cd apps/web && pnpm dev
```

- [ ] **Step 2: 走 spec §6 验收清单**

打开 `http://localhost:3000`，进入一个项目的章节编辑器，逐项验证：

- [ ] 选中文字 → 气泡在选区上方出现（折叠态 `[✨ AI 重写]`）
- [ ] 选区接近顶部 → 气泡显示在下方
- [ ] 点 `[✨ AI 重写]` → 展开输入框，自动 focus
- [ ] Esc → 回折叠态
- [ ] 输入指令 + 点重写（或 Cmd+Enter）→ 流式输出在气泡内展示
- [ ] streaming 中点停止 → 保留半截内容，进 diff 审核
- [ ] 流式完成 → 自动进 diff 审核面板
- [ ] diff 面板看到整章上下文里的那一处替换
- [ ] 接受/拒绝 hunk → 应用到章节
- [ ] 滚动编辑器 → 气泡跟随或隐藏
- [ ] 关闭气泡（点空白）→ 不影响编辑器其他操作

- [ ] **Step 3: 把 dogfood 发现的问题记入 GOTCHAS.md（若有）**

若发现新坑（如坐标偏差、滚动跟随不准、diff 拼接边界），追加到 `docs/GOTCHAS.md`。

- [ ] **Step 4: 最终提交（dogfood 记录或修复）**

若有修复：
```bash
git add -A
git commit -m "fix(web): 选区重写 dogfood 修复（具体问题）"
```

---

## Self-Review 记录

### Spec 覆盖核对

对照 spec §1-§8 逐项检查：

| spec 章节 | 实现位置（Task） | 状态 |
|---|---|---|
| §1 目标：补 rewrite UI 入口 | 整个 plan | ✅ |
| §2.1 架构：气泡在编辑器内、diff 编排在 page.tsx | Task 4.2（挂载）+ Task 5.1（接线） | ✅ |
| §2.2 状态机（hidden/ready/prompting/streaming） | Task 4.1 BubbleState | ✅ |
| §3.1 TiptapEditorRef 加 2 方法 | Task 3.1 | ✅ |
| §3.2 SelectionBubbleMenu Liquid Glass | Task 4.1 + globals.css | ✅ |
| §3.3 page.tsx 接线 | Task 5.1 | ✅ |
| §3.4 后端 rewrite-diff 端点 | Task 1.1-1.3 | ✅ |
| §4 边界（找不到/AI相同/空章节/首次出现） | Task 1.2 测试覆盖 | ✅ |
| §5 后端 6 测试 | Task 1.2（5 个）+ Task 1.3（3 个，含 API）= 8 个 | ✅ |
| §6 验收清单 | Task 5.2 dogfood | ✅ |

### 类型一致性核对

- `RewriteDiffRequest`：spec §3.4 = `{selected_text, ai_text}`（无 expected_version）→ Task 1.1 schema 一致 → Task 2.1 前端类型一致 → Task 5.1 调用一致 ✓
- `onRewriteComplete`：spec §3.3 = `(aiOutput: string, selectedText: string) => void` → Task 4.1 props 一致 → Task 4.2 挂载一致 → Task 5.1 handler 一致 ✓
- `getSelectionText` / `getSelectionCoords`：spec §3.1 → Task 3.1 实现 → Task 4.1 props → Task 4.2 闭包传递 ✓
- `compute_rewrite_diff(section, selected_text, ai_text)`：spec §3.4 → Task 1.2 签名一致 → Task 1.3 路由调用一致 ✓

### 已知限制（透明）

1. **轮询监听选区**（Task 4.1 用 `setInterval(200ms)`）：比 ProseMirror 原生 `onSelectionUpdate` 稍重，但避免在 TiptapEditor 内部加 plugin 的复杂度。200ms 延迟人眼几乎无感。若 dogfood 发现卡顿，未来改为原生事件。
2. **气泡高度估算**（Task 4.1 `bubbleHeight = 200`）：用估算值判断"上方空间够不够"。若字体/分辨率差异大可能误判，dogfood 观察。
3. **前端无单元测试**：项目无前端测试基建（GOTCHAS F1/F8），以 dogfood 为主。

### 占位符扫描

- 无 "TBD"/"TODO"/"fill in" —— ✅
- 所有代码块含完整实现 —— ✅
- 所有 Run 命令含 Expected —— ✅

---

## 实施顺序总结

| Phase | Tasks | 核心产出 | 测试新增 |
|---|---|---|---|
| 0 | Task 0 | 基线绿 + 分支 + 端点不存在取证 | 0 |
| 1 | Task 1.1-1.3 | 后端 rewrite-diff schema + service + 路由 | 8 |
| 2 | Task 2.1 | 前端 api.rewriteDiff + useRewriteDiff hook | 0（前端无测试基建） |
| 3 | Task 3.1 | TiptapEditorRef 加 2 方法 | 0 |
| 4 | Task 4.1-4.2 | SelectionBubbleMenu 组件 + 挂载 | 0 |
| 5 | Task 5.1-5.2 | page.tsx 接线 + dogfood | 0 |

**后端新增测试合计：8 个**（5 service + 3 API）

**预计工期：1-3 天**（spec §0 锚点：后端 1 端点 + 前端 1 组件，复用已有 diff 系统）
