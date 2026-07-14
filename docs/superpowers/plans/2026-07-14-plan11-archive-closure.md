# 计划 11：归档闭环接线 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通归档闭环最后一公里——暴露 `POST /projects/{id}/archive` API、修复 `ProjectOut` schema 漏字段、前端加归档按钮与徽标。后端 `archive_service` + `rag/archiver` 代码已齐全，本计划纯接线。

**Architecture:** 后端仅在 `app/api/projects.py` 新增路由薄层：归属校验（复用 `project_service.get_project`，非本人返回 404）→ 前置校验（至少一个非空 confirmed 章节，否则 422 防空项目造垃圾 chunk）→ 调 `archive_service.archive()`。`ProjectOut` 补 `archived_at` 字段并经 `_to_out` 输出。前端在项目详情页顶栏加「归档到知识库 / 更新知识库」按钮（按 `status` 切换文案），工作台卡片用 `useArchiveProject` mutation 替换裸 `api` 调用（归档后自动刷新列表使徽标生效）。无 Alembic 迁移（`archived_at` 列在 init schema 已存在）。

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest · Next.js 16 · React 19 · TanStack Query · lucide-react

**关联 spec：** [P0 验收补全迭代设计](../specs/2026-07-14-p0-completion-iteration.md) §6

---

## 文件结构

| 文件 | 责任 | 操作 |
|---|---|---|
| `apps/api/app/schemas/project.py` | `ProjectOut` 补 `archived_at` 字段 | 修改 |
| `apps/api/app/api/projects.py` | `_to_out` 输出 `archived_at`；新增 `POST /{id}/archive` 端点 + 前置校验 | 修改 |
| `apps/api/tests/test_projects.py` | schema 字段测试 + 归档端点/幂等/权限/前置校验测试 | 修改 |
| `apps/web/src/types/api.ts` | `Project` 补 `archived_at` | 修改 |
| `apps/web/src/lib/queries.ts` | 新增 `useProject` + `useArchiveProject` hooks | 修改 |
| `apps/web/src/app/(app)/projects/[id]/page.tsx` | 顶栏归档按钮（文案随 status 切换） | 修改 |
| `apps/web/src/components/project-card.tsx` | 归档按钮改用 mutation（刷新列表）+ 徽标核对 | 修改 |

> **无需迁移**：`archived_at` 列已存在于 `alembic/versions/aaf63a3f052a_init_schema_..._py`（init schema，line 49）。当前 Alembic head 为 `a20f16f0da4e`。

---

## Task 1：ProjectOut schema 补 archived_at + _to_out 输出

**Files:**
- Modify: `apps/api/app/schemas/project.py`
- Modify: `apps/api/app/api/projects.py`（仅 `_to_out`）
- Test: `apps/api/tests/test_projects.py`

- [ ] **Step 1: 写失败测试 — GET project 响应含 status 与 archived_at 字段**

在 `apps/api/tests/test_projects.py` 末尾（`test_api_unauthenticated_returns_401` 之后）追加：

```python
def test_api_get_project_returns_status_and_archived_at(client, registered_user, db_session):
    """GET /projects/{id} 响应含 status 与 archived_at（archived_at 初始为 null）。"""
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]

    res = client.get(f"/api/v1/projects/{project_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "draft"
    assert "archived_at" in body
    assert body["archived_at"] is None  # 未归档
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_projects.py::test_api_get_project_returns_status_and_archived_at -v`
Expected: FAIL（`KeyError: 'archived_at'` 或 `assert "archived_at" in body` 失败——schema 未暴露该字段）

- [ ] **Step 3: ProjectOut 补 archived_at 字段**

修改 `apps/api/app/schemas/project.py`，在 `ProjectOut` 的 `metadata` 字段之后、`created_at` 之前加一行。完整 `ProjectOut` 应为：

```python
class ProjectOut(BaseModel):
    id: str
    title: str
    stage: str
    status: str
    progress_pct: int
    metadata: dict[str, Any] | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

（即：在 `metadata: dict[str, Any] | None = None` 行下方插入 `    archived_at: datetime | None = None`）

- [ ] **Step 4: _to_out 输出 archived_at**

修改 `apps/api/app/api/projects.py` 的 `_to_out` 函数，补 `archived_at=p.archived_at`。完整函数应为：

```python
def _to_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=str(p.id), title=p.title, stage=p.stage, status=p.status,
        progress_pct=p.progress_pct, metadata=p.metadata_,
        archived_at=p.archived_at, created_at=p.created_at, updated_at=p.updated_at,
    )
```

（`Project` 模型已有 `archived_at: Mapped[datetime | None]`，见 `app/models/project.py:28-30`）

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_projects.py::test_api_get_project_returns_status_and_archived_at -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/schemas/project.py app/api/projects.py tests/test_projects.py
git commit -m "feat(plan11): ProjectOut 补 archived_at 字段并经 _to_out 输出"
```

---

## Task 2：POST /projects/{id}/archive 端点 + 前置校验

**Files:**
- Modify: `apps/api/app/api/projects.py`（import + 新增 archive 端点）
- Test: `apps/api/tests/test_projects.py`

> **测试策略**：测试库为 sqlite 内存库，`knowledge_chunks` 表被排除（pgvector 不支持），真实 `archive_service.archive` 会触发 `embed_texts` 失败。因此成功路径用 `monkeypatch.setattr("app.api.projects.archive_service.archive", fake)` 替换，只验证路由 + 归属 + 前置校验。404/422 路径在到达 archive 前已抛出，无需 mock。

- [ ] **Step 1: 写失败测试 — 归档端点四场景（成功/幂等/权限 404/空项目 422）**

在 `apps/api/tests/test_projects.py` 末尾追加（注意顶部若已有 `_login` 则不重复定义；test_projects.py 当前没有 `_login`，故新增）：

```python
# ── 归档端点（POST /projects/{id}/archive）──

def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })


def _seed_project_with_confirmed_section(db_session, registered_user, title="可归档发明"):
    """建项目并在 DB 层把第一个章节置为 confirmed+非空（绕过 confirm 时触发的 LLM summary）。"""
    from sqlalchemy import select
    from app.models import User
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    p = create_project(db_session, user=user, title=title)
    section = list_sections(db_session, user_id=user.id, project_id=str(p.id))[0]
    section.status = "confirmed"
    section.content = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "本发明涉及一种新型装置。"}]}
    ]}
    db_session.commit()
    return p


def test_api_archive_success(client, registered_user, db_session, monkeypatch):
    """归档成功返回 chunk 数（mock archiver 避开 sqlite pgvector 限制）。"""
    p = _seed_project_with_confirmed_section(db_session, registered_user)
    _login(client, registered_user)

    def fake_archive(db, *, user_id, project_id):
        return {"project_id": project_id, "chunks": 5, "status": "archived"}
    monkeypatch.setattr("app.api.projects.archive_service.archive", fake_archive)

    res = client.post(f"/api/v1/projects/{p.id}/archive")
    assert res.status_code == 200
    body = res.json()
    assert body["project_id"] == str(p.id)
    assert body["chunks"] == 5
    assert body["status"] == "archived"


def test_api_archive_idempotent(client, registered_user, db_session, monkeypatch):
    """重复归档幂等：二次调用同样 200。"""
    p = _seed_project_with_confirmed_section(db_session, registered_user)
    _login(client, registered_user)

    def fake_archive(db, *, user_id, project_id):
        return {"project_id": project_id, "chunks": 5, "status": "archived"}
    monkeypatch.setattr("app.api.projects.archive_service.archive", fake_archive)

    r1 = client.post(f"/api/v1/projects/{p.id}/archive")
    r2 = client.post(f"/api/v1/projects/{p.id}/archive")
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_api_archive_other_user_404(client, registered_user, db_session):
    """非本人项目归档返回 404（防探测，与 get/patch/delete 一致）。"""
    p = _seed_project_with_confirmed_section(db_session, registered_user)

    from app.core.security import hash_password
    from app.models import User
    other = User(email="other@b.com", password_hash=hash_password("Pass1234!"), name="Other")
    db_session.add(other)
    db_session.commit()
    client.post("/api/v1/auth/login", json={"email": "other@b.com", "password": "Pass1234!"})

    res = client.post(f"/api/v1/projects/{p.id}/archive")
    assert res.status_code == 404


def test_api_archive_empty_project_422(client, registered_user, db_session):
    """无已确认章节的空项目归档返回 422（防造垃圾 chunk）。"""
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    _login(client, registered_user)
    res = client.post("/api/v1/projects", json={"title": "空项目"})
    project_id = res.json()["id"]

    res = client.post(f"/api/v1/projects/{project_id}/archive")
    assert res.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_projects.py::test_api_archive_success tests/test_projects.py::test_api_archive_idempotent tests/test_projects.py::test_api_archive_other_user_404 tests/test_projects.py::test_api_archive_empty_project_422 -v`
Expected: FAIL（404 —— 端点不存在，路由未匹配；`POST /api/v1/projects/{id}/archive` 返回 404 而非预期状态码）

- [ ] **Step 3: 补 import + 新增 archive 端点**

修改 `apps/api/app/api/projects.py`。

**a) 替换 import 区**（当前前 10 行），加入 `select`、`ValidationError`、`Section`、`archive_service`：

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.deps import get_current_user
from app.models import Project, Section, User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import archive_service, project_service
```

**b) 在文件末尾（`delete` 端点之后）新增 archive 端点**：

```python
@router.post("/{project_id}/archive")
def archive(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 归属校验：非本人项目返回 404（防探测，与其他端点一致）
    project = project_service.get_project(db, user=current_user, project_id=project_id)

    # 前置校验：至少一个非空 confirmed 章节（防空项目造垃圾 chunk，spec §6.2）
    has_confirmed = db.scalar(
        select(Section).where(
            (Section.project_id == project.id)
            & (Section.status == "confirmed")
            & (Section.content.is_not(None))
        ).limit(1)
    )
    if has_confirmed is None:
        raise ValidationError("内容不足，无法归档（需至少一个已确认的非空章节）")

    # archive_service.archive 内部二次校验归属并调 rag/archiver（幂等：先删旧 chunk 再重生）
    return archive_service.archive(db, user_id=current_user.id, project_id=project_id)
```

> 说明：`project_service.get_project` 已封装 UUID 解析 + 归属校验（非本人抛 `NotFoundError`→404）。`archive_service.archive` 内部会再次校验归属（纵深防御，生产路径无害；测试中成功路径被 mock）。端点直接返回 service 的 dict `{"project_id", "chunks", "status"}`，与前端 `api.archiveProject` 的返回类型一致，无需额外 response_model。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_projects.py::test_api_archive_success tests/test_projects.py::test_api_archive_idempotent tests/test_projects.py::test_api_archive_other_user_404 tests/test_projects.py::test_api_archive_empty_project_422 -v`
Expected: 4 个全部 PASS

- [ ] **Step 5: 跑后端全量回归**

Run: `cd apps/api && uv run pytest -v`
Expected: 全部 PASS（原有测试 + Task 1 的 1 个 + Task 2 的 4 个新增，无回归）

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/api/projects.py tests/test_projects.py
git commit -m "feat(plan11): POST /projects/{id}/archive 端点 + 前置校验（422 空项目 / 404 非本人）"
```

---

## Task 3：前端 — Project 类型补字段 + useProject/useArchiveProject hooks + 详情页归档按钮

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/lib/queries.ts`
- Modify: `apps/web/src/app/(app)/projects/[id]/page.tsx`

- [ ] **Step 1: Project 类型补 archived_at**

修改 `apps/web/src/types/api.ts` 的 `Project` interface，在 `metadata` 之后、`created_at` 之前加 `archived_at`。完整 interface：

```typescript
export interface Project {
  id: string
  title: string
  stage: string
  status: string
  progress_pct: number
  metadata: Record<string, unknown> | null
  archived_at: string | null
  created_at: string
  updated_at: string
}
```

- [ ] **Step 2: queries.ts 加 useProject + useArchiveProject hooks**

修改 `apps/web/src/lib/queries.ts`。

**a) 在 `queryKeys` 对象中加 `project` 键**（在 `projects` 之后）：

```typescript
export const queryKeys = {
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  me: ['me'] as const,
  templates: ['templates'] as const,
  sections: (id: string) => ['sections', id] as const,
}
```

> `['projects', id]` 以 `['projects']` 为前缀，归档后 invalidate `['projects']` 会同时刷新列表与详情。

**b) 在 `useDeleteProject` 之后（用户区分隔之前）加两个 hook**：

```typescript
export function useProject(projectId: string) {
  return useQuery<Project>({
    queryKey: queryKeys.project(projectId),
    queryFn: () => api.getProject(projectId),
    enabled: !!projectId,
  })
}

export function useArchiveProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.archiveProject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}
```

> `api.getProject` 已存在于 `lib/api.ts:58`；`api.archiveProject` 已存在于 `lib/api.ts:143`。

- [ ] **Step 3: 详情页顶栏加归档按钮**

修改 `apps/web/src/app/(app)/projects/[id]/page.tsx`。

**a) import 区加 Archive 图标 + 新 hooks**：

第 3 行 lucide-react import 改为（在 `CheckCircle2` 后加 `Archive`）：

```typescript
import { Archive, CheckCircle2, Eye, History, PanelLeft, PanelRight, Search } from 'lucide-react'
```

第 14 行 queries import 改为：

```typescript
import { useArchiveProject, useProject, useSections, useUpdateSection } from '@/lib/queries'
```

**b) 组件内加 project 查询 + archive mutation**：

在 `const updateSection = useUpdateSection()` 之后加：

```typescript
  const { data: project } = useProject(projectId)
  const archiveMutation = useArchiveProject()
```

**c) 加 handleArchive 函数**（在 `handleConfirm` 函数之后）：

```typescript
  function handleArchive() {
    archiveMutation.mutate(projectId, {
      onSuccess: (res) => {
        if (project?.status === 'archived') {
          toast.success('知识库已更新')
        } else {
          toast.success(`已归档，写入 ${res.chunks} 个知识块`)
        }
      },
      onError: (err: { code?: string; message?: string }) =>
        toast.error(err?.message || '归档失败'),
    })
  }
```

**d) 顶栏按钮组加归档按钮**：

在「确认完成」`<Button>` 之后（即 `{current && (...)}` 按钮组内最后一个按钮后）加：

```typescript
              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5"
                onClick={handleArchive}
                disabled={archiveMutation.isPending}
              >
                <Archive className="size-3.5" />
                {project?.status === 'archived' ? '更新知识库' : '归档到知识库'}
              </Button>
```

即整段按钮组末尾变为（参考，确认完整上下文）：

```typescript
              <Button
                size="sm"
                className="h-8 gap-1.5"
                onClick={handleConfirm}
                disabled={updateSection.isPending}
              >
                <CheckCircle2 className="size-3.5" />
                确认完成
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5"
                onClick={handleArchive}
                disabled={archiveMutation.isPending}
              >
                <Archive className="size-3.5" />
                {project?.status === 'archived' ? '更新知识库' : '归档到知识库'}
              </Button>
```

- [ ] **Step 4: 验证前端构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功，无类型错误（`archived_at` 已在 Project 类型；`useProject`/`useArchiveProject` 已导出）

- [ ] **Step 5: 提交**

```bash
cd apps/web && git add src/types/api.ts src/lib/queries.ts "src/app/(app)/projects/[id]/page.tsx"
git commit -m "feat(plan11): 详情页顶栏归档按钮 + useProject/useArchiveProject hooks + Project.archived_at 类型"
```

---

## Task 4：前端 — project-card 归档按钮改用 mutation（刷新列表使徽标生效）

**Files:**
- Modify: `apps/web/src/components/project-card.tsx`

> **现状**：`project-card.tsx` 的 `STATUS_LABEL` 已含 `archived: '已归档'`，Badge 已能显示归档态。但 `handleArchive` 直接调 `api.archiveProject`（无 react-query invalidation），归档后列表不刷新、徽标不更新。本任务改用 `useArchiveProject` mutation 解决，并让已归档项目也可点「更新」。

- [ ] **Step 1: 改 import + handleArchive + 按钮显示条件**

修改 `apps/web/src/components/project-card.tsx`。

**a) import 区**：把 queries import 改为含 `useArchiveProject`，并移除不再使用的 `api` import。

将：
```typescript
import { api } from '@/lib/api'
import { useDeleteProject } from '@/lib/queries'
```

改为：
```typescript
import { useArchiveProject, useDeleteProject } from '@/lib/queries'
```

> 移除 `import { api } from '@/lib/api'`——改用 mutation 后 `api` 在本文件不再被引用，保留会导致 TS 未使用 import 报错。

**b) 组件内加 archive mutation**：在 `const del = useDeleteProject()` 之后加：

```typescript
  const archive = useArchiveProject()
```

**c) 替换 handleArchive**：把当前的 `async function handleArchive`（直接调 `api.archiveProject`）替换为：

```typescript
  function handleArchive() {
    archive.mutate(project.id, {
      onSuccess: (res) => toast.success(`已归档到知识库（${res.chunks} 个知识块）`),
      onError: () => toast.error('归档失败'),
    })
  }
```

**d) 归档按钮显示条件扩展到 archived 态**：把卡片底部的归档按钮条件从仅 `completed` 扩展到 `completed || archived`，并切换文案。将：

```typescript
            {project.status === 'completed' && (
              <Button variant="ghost" size="xs" onClick={handleArchive}>
                归档
              </Button>
            )}
```

改为：

```typescript
            {(project.status === 'completed' || project.status === 'archived') && (
              <Button
                variant="ghost"
                size="xs"
                onClick={handleArchive}
                disabled={archive.isPending}
              >
                {project.status === 'archived' ? '更新' : '归档'}
              </Button>
            )}
```

> 徽标本身无需改动——`STATUS_LABEL['archived'] = '已归档'` 已就绪，归档后列表刷新即显示。

- [ ] **Step 2: 验证前端构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功，无类型错误、无未使用 import

- [ ] **Step 3: 提交**

```bash
cd apps/web && git add src/components/project-card.tsx
git commit -m "feat(plan11): project-card 归档改用 mutation（归档后刷新列表）+ 已归档可更新"
```

---

## Task 5：全量验证

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest -v`
Expected: 全部 PASS（原有 + Task 1 的 `test_api_get_project_returns_status_and_archived_at` + Task 2 的 4 个归档测试，共 5 个新增）

- [ ] **Step 2: 前端构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功，无类型错误

- [ ] **Step 3: 端到端手验（需启动后端 + 前端 + DB）**

启动后端和前端，登录后：
1. 打开一个有已确认章节的项目 → 点顶栏「归档到知识库」→ toast 显示「已归档，写入 N 个知识块」→ 按钮文案变为「更新知识库」
2. 回工作台 → 该项目卡片显示「已归档」徽标
3. 再次点「更新知识库」→ toast「知识库已更新」（幂等）
4. 打开一个全新空项目 → 点「归档到知识库」→ 提示「内容不足，无法归档」（422）

- [ ] **Step 4: 提交计划完成标记**

```bash
git commit --allow-empty -m "chore: 计划 11 归档闭环接线端到端验证通过"
```
