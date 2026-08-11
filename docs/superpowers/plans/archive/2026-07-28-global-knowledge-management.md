# 全局知识库管理(导航 + 删除)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 admin 全局知识库管理能力——(a) admin 导航「内容」加子菜单 dropdown,露出 templates/knowledge 两个子页入口;(b) 后端加删除端点 + 前端 GlobalKnowledgeCard 加删除按钮(带确认 Dialog);(c) 顺带把页面标题从「知识库直传」改成「全局知识库」。

**Architecture:** 后端镜像模板删除模式(DELETE + service 函数,删 KnowledgeFile + minio 对象 + 关联 KnowledgeChunk)。前端导航用 dropdown 子菜单(复用现有 UserMenu 的点击展开 + 外部关闭模式)。删除用确认 Dialog 防误删(硬删除,不可恢复)。

**Tech Stack:** FastAPI + SQLAlchemy(后端);Next.js + shadcn Dialog + TanStack Query(前端)

**背景(替代独立 spec):** admin 全局库现状只能上传(docx/pdf + 抓取网页),不能删除/管理。入口也难找(「内容」导航直跳 templates,knowledge 子页要手输 URL)。本计划闭环这两块。

---

## 文件结构

### 新建文件(1 个)

| 文件 | 职责 |
|---|---|
| `apps/web/src/components/navbar-content-dropdown.tsx` | 「内容」导航子菜单 dropdown |

### 改动文件(5 个)

| 文件 | 改动 |
|---|---|
| `apps/api/app/services/knowledge_service.py` | 加 `delete_global_file()`(删 KF + minio + chunk) |
| `apps/api/app/api/admin/content.py` | 加 `DELETE /admin/knowledge/files/{file_id}` 端点 |
| `apps/api/tests/test_knowledge_service_delete.py` | 删除 service 测试 |
| `apps/web/src/lib/api.ts` + `queries.ts` | 加 `deleteGlobalKnowledge` API + hook |
| `apps/web/src/app/(app)/admin/content/knowledge/page.tsx` | GlobalKnowledgeCard 加删除按钮 + 确认 Dialog + 标题改名 |
| `apps/web/src/components/navbar.tsx` | 「内容」项用 ContentDropdown 替代直接 Link |

---

## 任务依赖

```
Task 1 (后端 service) → Task 2 (后端端点 + 测试)
Task 3 (前端 API + hook) ── 依赖 Task 2 ──→ Task 4 (前端删除 UI)
Task 5 (导航 dropdown) 独立
```

Task 1-2 是后端,Task 3-4 是前端删除,Task 5 是导航(独立)。

---

## Task 1: 后端 — `delete_global_file` service 函数(TDD)

**Files:**
- Modify: `apps/api/app/services/knowledge_service.py`
- Test: `apps/api/tests/test_knowledge_service_delete.py`

- [ ] **Step 1: 写测试**

创建 `apps/api/tests/test_knowledge_service_delete.py`:

```python
"""knowledge_service.delete_global_file 测试。"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.models import KnowledgeChunk, KnowledgeFile
from app.services import knowledge_service


def test_delete_global_file_removes_record_and_storage(db_session):
    """删 global 文件:KnowledgeFile 记录删 + minio 对象删 + 关联 chunk 删。"""
    storage = MagicMock()
    admin = MagicMock()
    admin.id = uuid.uuid4()

    # 建一个 global KF + 关联 chunk
    kf = knowledge_service.upload_to_global(
        db_session, storage=storage, uploader=admin,
        filename="test.md", content=b"unique-delete-test-content",
        mime="text/markdown", text="正文内容" * 50,
    )
    # upload_to_global 内部会 _ingest_chunks,但 SQLite 测试库可能跳过 chunk 表
    # 手动建一个 chunk 关联,验证删除时它也被删
    chunk = KnowledgeChunk(
        user_id=admin.id, scope="global", file_id=kf.id,
        source_type="external_md", source_id=kf.id,
        chunk_index=0, content="正文内容" * 50,
    )
    db_session.add(chunk)
    db_session.commit()

    object_key = kf.object_key
    bucket = kf.bucket
    kf_id = kf.id

    knowledge_service.delete_global_file(db_session, storage=storage, file_id=str(kf_id))

    # KF 记录删了
    assert db_session.get(KnowledgeFile, kf_id) is None
    # minio 对象删了
    storage.delete.assert_called_once_with(bucket, object_key)
    # 关联 chunk 删了
    remaining = db_session.query(KnowledgeChunk).filter_by(file_id=kf_id).all()
    assert len(remaining) == 0


def test_delete_global_file_404_on_missing(db_session):
    """删不存在的文件 → NotFoundError。"""
    from app.core.exceptions import NotFoundError
    storage = MagicMock()
    with pytest.raises(NotFoundError):
        knowledge_service.delete_global_file(
            db_session, storage=storage, file_id=str(uuid.uuid4()),
        )


def test_delete_global_file_refuses_personal(db_session):
    """拒绝删 personal 文件(本函数只管 global,防误调)。"""
    from app.core.exceptions import ValidationError
    storage = MagicMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    kf = knowledge_service.upload_external(
        db_session, storage=storage, user=user,
        filename="personal.md", content=b"personal-content",
        mime="text/markdown", text="text",
    )
    with pytest.raises(ValidationError):
        knowledge_service.delete_global_file(
            db_session, storage=storage, file_id=str(kf.id),
        )
```

**关键**:测试用 `@patch("app.services.knowledge_service._ingest_chunks")` 不需要——因为 upload_to_global 在 SQLite 测试库会跳过 chunk 入库(参考 Task 8 经验),所以我们手动建 chunk。但如果 SQLite 报 pgvector 错,加 patch。

先跑确认测试失败原因,再决定是否 patch。

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd apps/api && uv run pytest tests/test_knowledge_service_delete.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'delete_global_file'`

- [ ] **Step 3: 实现 delete_global_file**

在 `apps/api/app/services/knowledge_service.py` 的 `list_global_files` 函数(约第 155 行)之后加:

```python
def delete_global_file(db: Session, *, storage: Storage, file_id: str) -> None:
    """admin 删除全局库文件。

    删除三件套:KnowledgeFile 记录 + minio 对象 + 关联 KnowledgeChunk。
    仅限 scope=global 的文件(防误删 personal)。
    硬删除,不可恢复——前端必须带确认 Dialog。
    """
    try:
        fid = uuid.UUID(file_id)
    except ValueError:
        raise NotFoundError("文件不存在")

    kf = db.get(KnowledgeFile, fid)
    if kf is None:
        raise NotFoundError("文件不存在")
    if kf.scope != "global":
        raise ValidationError("仅可删除全局库文件")

    # 1. 删关联 chunk(KnowledgeChunk.file_id FK 是 SET NULL,不会级联,需手动)
    from sqlalchemy import delete as sa_delete
    db.execute(
        sa_delete(KnowledgeChunk).where(KnowledgeChunk.file_id == fid)
    )

    # 2. 删 minio 对象(失败不阻塞 DB 删除——对象孤儿可后续清理)
    try:
        storage.delete(kf.bucket, kf.object_key)
    except Exception:
        pass

    # 3. 删 KnowledgeFile 记录
    db.delete(kf)
    db.commit()
```

**注意**:
- `KnowledgeChunk` 需 import,检查文件顶部是否已 import(现有 `_ingest_chunks` 用了,应该有)。Run `grep -n "KnowledgeChunk" apps/api/app/services/knowledge_service.py | head -3` 确认
- `ValidationError` 需 import(检查顶部)
- 用 SQLAlchemy `delete()` 批量删 chunk,比循环 `db.delete()` 高效

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd apps/api && uv run pytest tests/test_knowledge_service_delete.py -v`
Expected: PASS(3 个测试)

如果第 1 个测试因 SQLite/pgvector 报错(upload_to_global 内部的 _ingest_chunks 调 embedding),在测试文件顶部加:
```python
@pytest.fixture(autouse=True)
def _mock_ingest(monkeypatch):
    """跳过 chunk 入库的 embedding 调用(SQLite 测试库不跑 pgvector)。"""
    monkeypatch.setattr(
        "app.services.knowledge_service._ingest_chunks",
        lambda *args, **kwargs: None,
    )
```

- [ ] **Step 5: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/api/app/services/knowledge_service.py apps/api/tests/test_knowledge_service_delete.py
git commit -m "feat(knowledge): delete_global_file service(删 KF+minio+chunk)"
```

---

## Task 2: 后端 — `DELETE /admin/knowledge/files/{file_id}` 端点

**Files:**
- Modify: `apps/api/app/api/admin/content.py`

- [ ] **Step 1: 加端点**

打开 `apps/api/app/api/admin/content.py`,在 `upload_global` 函数(约第 142-165 行)之后加:

```python


@router.delete("/admin/knowledge/files/{file_id}", status_code=204)
def delete_global_knowledge_file(
    file_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """admin 删除全局库文件(硬删除:KF + minio 对象 + 关联 chunk)。"""
    knowledge_service.delete_global_file(
        db, storage=get_storage(), file_id=file_id,
    )
    return None
```

**注意**:
- `require_admin` 和 `get_storage` 应已在文件顶部 import(现有 upload_global 用了)。Run `grep -n "require_admin\|get_storage\|knowledge_service" apps/api/app/api/admin/content.py | head -5` 确认
- 返回 204(无内容),对齐模板删除端点
- `knowledge_service` 需 import(检查顶部,upload_global 用了)

- [ ] **Step 2: 加 API 测试(可选,因 service 已测,这里只验证端点接通)**

在 `apps/api/tests/test_web_ingestion_api.py` 末尾或新建测试文件加一个轻量端点测试。**简化:跳过**,因为 service 层已覆盖,端点只是 thin wrapper。如果项目惯例要求端点测试,参考现有 `test_web_ingestion_api.py` 的 auth 模式加。

- [ ] **Step 3: 跑全量后端测试确认零回归**

Run: `cd apps/api && uv run pytest -x`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/api/app/api/admin/content.py
git commit -m "feat(api): DELETE /admin/knowledge/files/{id} 端点"
```

---

## Task 3: 前端 — API + hook

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: api.ts 加方法**

打开 `apps/web/src/lib/api.ts`,在 `adminUploadGlobal`(约第 522-533 行)之后加:

```typescript

  deleteGlobalKnowledge: (fileId: string) =>
    request<void>(`/admin/knowledge/files/${fileId}`, { method: 'DELETE' }),
```

- [ ] **Step 2: queries.ts 加 hook**

打开 `apps/web/src/lib/queries.ts`,在 `useAdminUploadGlobal`(约第 276-282 行)之后加:

```typescript

export function useDeleteGlobalKnowledge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => api.deleteGlobalKnowledge(fileId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.knowledgeGlobal })
    },
  })
}
```

**注意**:`request<void>` 对应后端 204(无内容),request wrapper 第 71-73 行处理了 204 返回 undefined。

- [ ] **Step 3: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无新增错误

- [ ] **Step 4: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/lib/api.ts apps/web/src/lib/queries.ts
git commit -m "feat(web): deleteGlobalKnowledge API + hook"
```

---

## Task 4: 前端 — GlobalKnowledgeCard 加删除按钮 + 确认 Dialog + 标题改名

**Files:**
- Modify: `apps/web/src/app/(app)/admin/content/knowledge/page.tsx`

- [ ] **Step 1: 加 import + 标题改名**

打开 `apps/web/src/app/(app)/admin/content/knowledge/page.tsx`。

第 4 行 lucide import 加 `Trash2`:
```typescript
import { Download, Globe, Trash2, Upload } from 'lucide-react'
```

加 Dialog import(在现有 import 区):
```typescript
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useDeleteGlobalKnowledge } from '@/lib/queries'
```

把 `PageHeader` 的 title 从「知识库直传」改成「全局知识库」:
```typescript
      <PageHeader title="全局知识库" description={`全员可检索 · ${list.length} 个文件`}>
```

- [ ] **Step 2: AdminKnowledgePage 加删除状态**

在 `AdminKnowledgePage` 组件的 `useState` 后加:
```typescript
  const [ingestOpen, setIngestOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeFile | null>(null)
```

在 `</PageShell>` 之前(WebIngestDialog 旁边)加删除确认 Dialog:
```typescript
      <WebIngestDialog
        scope="global"
        open={ingestOpen}
        onOpenChange={setIngestOpen}
      />

      {/* 删除确认 Dialog */}
      <DeleteConfirmDialog
        target={deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      />
```

- [ ] **Step 3: GlobalKnowledgeCard 加删除按钮 + 传 setDeleteTarget**

把 `GlobalKnowledgeCard` 组件签名改为接收 `onDelete`:
```typescript
function GlobalKnowledgeCard({
  kf,
  onDelete,
}: {
  kf: KnowledgeFile
  onDelete: (kf: KnowledgeFile) => void
}) {
```

在卡片底部按钮区(现有「下载」按钮旁)加删除按钮:
```typescript
        <div className="flex items-center gap-2 pt-1">
          <Button variant="ghost" size="xs" asChild>
            <a href={api.knowledgeFileUrl(kf.id)} download>
              <Download className="mr-1 size-3.5" /> 下载
            </a>
          </Button>
          <Button
            variant="ghost"
            size="xs"
            className="text-destructive hover:text-destructive"
            onClick={() => onDelete(kf)}
          >
            <Trash2 className="mr-1 size-3.5" /> 删除
          </Button>
        </div>
```

然后改 list.map 调用,传 `onDelete`:
```typescript
            {list.map((kf) => (
              <GlobalKnowledgeCard
                key={kf.id}
                kf={kf}
                onDelete={setDeleteTarget}
              />
            ))}
```

- [ ] **Step 4: 加 DeleteConfirmDialog 组件**

在文件末尾(`formatSize` 函数之前)加:

```typescript
function DeleteConfirmDialog({
  target,
  onOpenChange,
}: {
  target: KnowledgeFile | null
  onOpenChange: (open: boolean) => void
}) {
  const del = useDeleteGlobalKnowledge()

  function handleConfirm() {
    if (!target) return
    del.mutate(target.id, {
      onSuccess: () => {
        toast.success('已删除')
        onOpenChange(false)
      },
      onError: (err: { message?: string }) =>
        toast.error(err?.message ?? '删除失败'),
    })
  }

  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>删除全局库文件?</DialogTitle>
          <DialogDescription>
            将永久删除「{target?.filename}」及其向量索引。此操作不可恢复。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={del.isPending}
          >
            {del.isPending ? '删除中...' : '确认删除'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 5: 类型检查 + build**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无新增错误

Run: `cd apps/web && pnpm build 2>&1 | tail -10`
Expected: build 成功

- [ ] **Step 6: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add "apps/web/src/app/(app)/admin/content/knowledge/page.tsx"
git commit -m "feat(web): 全局知识库页加删除(确认 Dialog)+标题改名"
```

---

## Task 5: 前端 — 导航「内容」加子菜单 dropdown

**Files:**
- Create: `apps/web/src/components/navbar-content-dropdown.tsx`
- Modify: `apps/web/src/components/navbar.tsx`

- [ ] **Step 1: 创建 ContentDropdown 组件**

创建 `apps/web/src/components/navbar-content-dropdown.tsx`:

```typescript
'use client'

import { BookOpen, FileText } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

const SUB_ITEMS = [
  { href: '/admin/content/templates', label: '模板', icon: FileText },
  { href: '/admin/content/knowledge', label: '知识库', icon: BookOpen },
] as const

/**
 * admin 导航「内容」子菜单 dropdown。
 *
 * 点击「内容」展开 templates/knowledge 两个子项;外部点击或选中后关闭。
 * 任一子页处于激活态时,「内容」本身也点亮。
 */
export function NavbarContentDropdown() {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // 外部点击关闭
  useEffect(() => {
    if (!open) return
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  // 子页激活态:任一子路径命中即点亮「内容」
  const isContentActive = pathname.startsWith('/admin/content')

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[13px] font-medium transition-colors',
          isContentActive
            ? 'bg-accent text-accent-foreground'
            : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
        )}
      >
        <FileText className="size-3.5" />
        内容
      </button>
      {open && (
        <div
          className="glass-overlay absolute left-0 top-full mt-1 w-44 overflow-hidden rounded-2xl border border-black/[0.07] p-1 dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-overlay)' }}
        >
          {SUB_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`)
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setOpen(false)}
                className={cn(
                  'flex items-center gap-2 rounded-full px-2.5 py-1.5 text-[13px] transition-colors',
                  active
                    ? 'bg-accent text-accent-foreground'
                    : 'text-foreground hover:bg-accent/60',
                )}
              >
                <Icon className="size-3.5" />
                {label}
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

**设计说明**:
- 复用现有 `UserMenu` 的 dropdown 模式(点击展开 + 外部 mousedown 关闭)
- `glass-overlay` + `var(--shadow-overlay)` 对齐 UserMenu 弹层样式
- 任一子页激活时「内容」也点亮(`isContentActive`)
- 选中子项后自动关闭

- [ ] **Step 2: navbar.tsx 用 ContentDropdown 替换「内容」Link**

打开 `apps/web/src/components/navbar.tsx`。

第 3-15 行 lucide import 里,`FileText` 已 import(第 6 行),保留。

在 import 区加:
```typescript
import { NavbarContentDropdown } from '@/components/navbar-content-dropdown'
```

然后改 ADMIN_NAV_ITEMS(第 55-62 行):**删掉「内容」项**(它现在由 dropdown 渲染,不应再出现在 nav items 数组里):

```typescript
const ADMIN_NAV_ITEMS: NavItem[] = [
  { href: '/admin', label: '概览', icon: LayoutDashboard },
  { href: '/admin/users', label: '用户', icon: Users },
  // 「内容」项由 NavbarContentDropdown 渲染(有子菜单),不在此数组
  { href: '/admin/review', label: '审核', icon: CheckCircle, showPendingBadge: true },
  { href: '/admin/skills', label: '技能', icon: Wrench },
  { href: '/admin/console', label: '控制台', icon: Settings },
]
```

然后在 nav 渲染处(约第 112-133 行的 `{navItems.map(...)}`),需要特殊处理「内容」dropdown——它不是普通 Link,要插在「用户」和「审核」之间。

把 nav 渲染逻辑改为:先 map ADMIN_NAV_ITEMS,但在「用户」之后、「审核」之前插入 `<NavbarContentDropdown />`。

**实现**:用一个标记位标记插入点。最简方案:在 map 里检测当前 item 是「用户」时,渲染完它后紧跟渲染 dropdown:

```typescript
            {navItems.map((item) => {
              const active = isAdminActive(pathname, item.href)
              const Icon = item.icon
              return (
                <span key={item.href} className="flex items-center">
                  <Link
                    href={item.href}
                    className={cn(
                      'flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[13px] font-medium transition-colors',
                      active
                        ? 'bg-accent text-accent-foreground'
                        : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
                    )}
                  >
                    <Icon className="size-3.5" />
                    {item.label}
                    {item.showPendingBadge && <PendingBadge />}
                  </Link>
                  {/* 「用户」项之后插入「内容」dropdown */}
                  {isAdminArea && item.href === '/admin/users' && (
                    <NavbarContentDropdown />
                  )}
                </span>
              )
            })}
```

**注意**:用 `<span>` 包裹每个 item + 可选 dropdown,保持 flex 布局。dropdown 跟在「用户」后面渲染。

- [ ] **Step 3: 类型检查 + build**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无新增错误

Run: `cd apps/web && pnpm build 2>&1 | tail -10`
Expected: build 成功

- [ ] **Step 4: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/components/navbar-content-dropdown.tsx apps/web/src/components/navbar.tsx
git commit -m "feat(web): admin 导航「内容」加子菜单 dropdown"
```

---

## 完成验证

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest`
Expected: 全部通过(682 + 3 新增 = 685)

- [ ] **Step 2: 前端 build**

Run: `cd apps/web && pnpm build`
Expected: 成功

- [ ] **Step 3: 手动验证清单**

启动前后端,用 admin 登录:

**导航**:
- [ ] admin 顶栏看到「内容」(带 ▾ 或可点击展开)
- [ ] 点「内容」展开子菜单:模板 / 知识库
- [ ] 点「知识库」进 `/admin/content/knowledge`
- [ ] 在 `/admin/content/knowledge` 时,「内容」本身点亮
- [ ] 外部点击关闭子菜单

**删除**:
- [ ] 全局知识库页的文件卡片有「删除」按钮(红色)
- [ ] 点删除弹确认 Dialog,显示文件名 + 警告
- [ ] 点取消 → Dialog 关闭,文件还在
- [ ] 点确认删除 → toast「已删除」+ 列表刷新,文件消失
- [ ] (后端验证)该文件的向量也删了(检索不再命中)

**标题**:
- [ ] 页面标题是「全局知识库」(不是「知识库直传」)

---

## 实施笔记

1. **KnowledgeChunk.file_id 是 SET NULL 不是 CASCADE**:删 KnowledgeFile 时 chunk 不会被自动删,service 层必须手动 `DELETE FROM knowledge_chunks WHERE file_id = ?`。Task 1 用 SQLAlchemy `delete()` 批量执行。

2. **硬删除 vs 软删除**:本计划用硬删除(对齐模板删除模式)。KnowledgeFile 没有 `deleted_at` 字段,加软删除要迁移。硬删除 + 前端确认 Dialog 是够的。

3. **minio 删除失败不阻塞**:`delete_global_file` 里 `storage.delete` 用 try/except 吞掉异常——minio 对象孤儿可后续清理,但 DB 记录必须删掉(否则文件还在列表里)。这是有意决策。

4. **navbar dropdown 插入点**:用 `item.href === '/admin/users'` 作为标记,在该 item 后渲染 dropdown。这避免了改 ADMIN_NAV_ITEMS 的数据结构(保持其他 item 简单 map)。如果觉得 hack,可改成 ADMIN_NAV_ITEMS 支持 `children?: NavItem[]` 字段,但那是更大重构,YAGNI。

5. **Dropdown 无障碍**:本实现用 `<button>` + `<div>`(不是 ARIA combobox)。对 admin 内部工具够用。如果要严格无障碍,可加 `aria-expanded` / `aria-haspopup` / `role="menu"`。

6. **Task 1 测试的 SQLite 兼容**:`upload_to_global` 内部调 `_ingest_chunks`,后者调 embedding。SQLite 测试库可能跳过 knowledge_chunks 表(参考 web ingestion 测试经验),也可能报错。如果报错,加 `autouse` fixture patch `_ingest_chunks`。先跑确认。
