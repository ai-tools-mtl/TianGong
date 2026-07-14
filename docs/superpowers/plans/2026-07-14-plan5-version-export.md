# 计划 5：版本快照 + 全篇预览 + 导出 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** 实现交底书的版本管理（章节快照可回滚）、全篇预览（合并所有章节只读视图）、导出 Word/Markdown（套用模板样式 + 抬头元信息），让交底书能固化和交付。

**Architecture:** 后端新增 SectionVersion 模型（章节级版本快照）+ 版本/预览/导出 API。导出用 python-docx 生成 .docx（Tiptap JSON → docx 元素映射）。前端加版本历史抽屉 + 全篇预览页 + 导出按钮。

**Tech Stack:** python-docx（Word 导出）· FastAPI（API）· React（前端预览/版本）

**Spec reference:** 设计文档 v1.5
- 数据模型：3.2 SectionVersion
- 工程细节：13.5 导出渲染器（Tiptap→docx 映射表）
- 13.6 删除语义、13.7 项目 completed 判定

---

## 后端 API 设计（本计划新增）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/v1/sections/{id}/versions` | GET | 章节版本列表 |
| `/api/v1/sections/{id}/versions` | POST | 创建版本快照（手动） |
| `/api/v1/sections/{id}/versions/{vid}` | POST | 回滚到指定版本 |
| `/api/v1/projects/{id}/preview` | GET | 全篇预览（合并章节） |
| `/api/v1/projects/{id}/export/docx` | GET | 导出 Word |
| `/api/v1/projects/{id}/export/markdown` | GET | 导出 Markdown |

---

## 文件结构（本计划新增）

```
apps/api/app/
├── models/section_version.py     # 新增
├── schemas/version.py            # 新增
├── schemas/export.py             # 新增
├── services/version_service.py   # 新增
├── services/export_service.py    # 新增（Tiptap→docx 渲染器）
├── api/versions.py               # 新增
├── api/export.py                 # 新增
apps/web/src/
├── components/version-drawer.tsx # 新增（版本历史抽屉）
├── app/(app)/projects/[id]/preview/page.tsx  # 新增（全篇预览）
```

---

## 任务 0：SectionVersion 模型 + 迁移

**Files:**
- Create: `apps/api/app/models/section_version.py`
- Modify: `apps/api/app/models/__init__.py`

- [ ] **Step 1: 模型**

Create `apps/api/app/models/section_version.py`:
```python
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class SectionVersion(Base, IdMixin, TimestampMixin):
    __tablename__ = "section_versions"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(20), default="manual")  # auto / manual
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

更新 `models/__init__.py` 加入 SectionVersion。

- [ ] **Step 2: 迁移 + Commit**

```bash
cd apps/api && uv run alembic revision --autogenerate -m "add section_versions"
cd apps/api && uv run alembic upgrade head
git add apps/api/app/models/ apps/api/alembic/versions/
git commit -m "feat: SectionVersion 模型（章节版本快照）"
```

---

## 任务 1：版本服务 + API

**Files:**
- Create: `apps/api/app/schemas/version.py`
- Create: `apps/api/app/services/version_service.py`
- Create: `apps/api/app/api/versions.py`
- Modify: `apps/api/app/api/router.py`
- Modify: `apps/api/app/services/section_service.py`（确认时自动存版本）

- [ ] **Step 1: Schema**

Create `apps/api/app/schemas/version.py`:
```python
from datetime import datetime

from pydantic import BaseModel


class VersionOut(BaseModel):
    id: str
    section_id: str
    content: dict | None
    summary: str | None
    created_by: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class VersionCreate(BaseModel):
    note: str | None = None
```

- [ ] **Step 2: 版本服务**

Create `apps/api/app/services/version_service.py`:
```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Section, SectionVersion


def list_versions(db: Session, *, section: Section) -> list[SectionVersion]:
    return list(db.scalars(
        select(SectionVersion)
        .where(SectionVersion.section_id == section.id)
        .order_by(SectionVersion.created_at.desc())
    ))


def create_version(
    db: Session, *, section: Section, created_by: str = "manual", note: str | None = None
) -> SectionVersion:
    version = SectionVersion(
        section_id=section.id,
        content=section.content,
        summary=section.summary,
        created_by=created_by,
        note=note,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def rollback_to_version(db: Session, *, section: Section, version_id: str) -> Section:
    try:
        vid = UUID(version_id)
    except ValueError:
        raise NotFoundError("版本不存在")
    version = db.scalar(
        select(SectionVersion).where(
            (SectionVersion.id == vid) & (SectionVersion.section_id == section.id)
        )
    )
    if version is None:
        raise NotFoundError("版本不存在")
    # 回滚前先存当前内容为新版本（防丢失）
    if section.content != version.content:
        create_version(db, section=section, created_by="auto", note="回滚前自动保存")
    section.content = version.content
    section.summary = version.summary
    db.commit()
    db.refresh(section)
    return section
```

- [ ] **Step 3: 版本 API**

Create `apps/api/app/api/versions.py`:
```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.version import VersionCreate, VersionOut
from app.services import section_service, version_service

router = APIRouter(tags=["versions"])


def _to_out(v) -> VersionOut:
    return VersionOut(
        id=str(v.id), section_id=str(v.section_id), content=v.content,
        summary=v.summary, created_by=v.created_by, note=v.note,
        created_at=v.created_at,
    )


@router.get("/sections/{section_id}/versions", response_model=list[VersionOut])
def list_versions(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    versions = version_service.list_versions(db, section=section)
    return [_to_out(v) for v in versions]


@router.post("/sections/{section_id}/versions", response_model=VersionOut, status_code=201)
def create_version(
    section_id: str,
    payload: VersionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    v = version_service.create_version(db, section=section, note=payload.note)
    return _to_out(v)


@router.post("/sections/{section_id}/versions/{version_id}/rollback")
def rollback(
    section_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    section_service_section = version_service.rollback_to_version(
        db, section=section, version_id=version_id
    )
    return {"message": "已回滚", "section_id": str(section_service_section.id)}
```

- [ ] **Step 4: 确认章节时自动存版本**

在 `section_service.update_section` 里，status 变 confirmed 时先存版本:
```python
        if status == "confirmed" and old_status != "confirmed":
            from app.services.version_service import create_version
            create_version(db, section=section, created_by="auto", note="确认章节时自动保存")
            from app.services.summary_service import generate_summary
            generate_summary(db, section)
```

- [ ] **Step 5: 注册路由 + 测试 + Commit**

Modify router.py 加 versions 路由。

Create `apps/api/tests/test_versions.py`:
```python
def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })


def _make_project_with_section(client, db_session):
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    res = client.post("/api/v1/projects", json={"title": "版本测试"})
    pid = res.json()["id"]
    sections = client.get(f"/api/v1/projects/{pid}/sections").json()
    return sections[0]["id"]


def test_create_version(client, registered_user, db_session):
    _login(client, registered_user)
    sid = _make_project_with_section(client, db_session)
    res = client.post(f"/api/v1/sections/{sid}/versions", json={"note": "手动快照"})
    assert res.status_code == 201
    assert res.json()["note"] == "手动快照"


def test_list_versions(client, registered_user, db_session):
    _login(client, registered_user)
    sid = _make_project_with_section(client, db_session)
    client.post(f"/api/v1/sections/{sid}/versions", json={"note": "v1"})
    client.post(f"/api/v1/sections/{sid}/versions", json={"note": "v2"})
    res = client.get(f"/api/v1/sections/{sid}/versions")
    assert res.status_code == 200
    assert len(res.json()) == 2
```

```bash
cd apps/api && uv run pytest tests/test_versions.py -v
git add apps/api/app/schemas/version.py apps/api/app/services/version_service.py apps/api/app/api/versions.py apps/api/app/api/router.py apps/api/app/services/section_service.py apps/api/tests/test_versions.py
git commit -m "feat: 章节版本快照（创建/列表/回滚 + 确认时自动存）"
```

---

## 任务 2：导出渲染器（Tiptap→docx）+ 导出 API

**Files:**
- Create: `apps/api/app/services/export_service.py`
- Create: `apps/api/app/api/export.py`
- Modify: `apps/api/app/api/router.py`

- [ ] **Step 1: 导出服务（Tiptap→docx 渲染）**

Create `apps/api/app/services/export_service.py`:
```python
"""导出服务：Tiptap JSON → docx / Markdown（设计 13.5）。"""

import io
from typing import Any

from docx import Document
from docx.shared import Pt
from sqlalchemy.orm import Session

from app.models import Project, Section


def export_markdown(db: Session, *, project: Project) -> str:
    """导出为 Markdown 文本。"""
    sections = _get_ordered_sections(db, project)
    lines = [f"# {project.title}\n"]

    # 抬头元信息
    if project.metadata_:
        meta = project.metadata_
        if meta.get("inventors"):
            lines.append(f"**发明人**：{', '.join(meta['inventors'])}\n")
        if meta.get("applicant"):
            lines.append(f"**申请人**：{meta['applicant']}\n")

    for s in sections:
        lines.append(f"\n## {s.title}\n")
        if s.content:
            lines.append(_tiptap_to_markdown(s.content))
        lines.append("")
    return "\n".join(lines)


def export_docx(db: Session, *, project: Project) -> bytes:
    """导出为 .docx 字节。"""
    doc = Document()
    doc.add_heading(project.title, level=0)

    # 抬头元信息
    if project.metadata_:
        meta = project.metadata_
        info_parts = []
        if meta.get("inventors"):
            info_parts.append(f"发明人：{', '.join(meta['inventors'])}")
        if meta.get("applicant"):
            info_parts.append(f"申请人：{meta['applicant']}")
        if meta.get("disclosure_date"):
            info_parts.append(f"日期：{meta['disclosure_date']}")
        if info_parts:
            doc.add_paragraph(" | ".join(info_parts))

    sections = _get_ordered_sections(db, project)
    for s in sections:
        doc.add_heading(s.title, level=1)
        if s.content:
            _render_tiptap_to_docx(doc, s.content)
        else:
            doc.add_paragraph("（待填写）")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _get_ordered_sections(db: Session, project: Project) -> list[Section]:
    from sqlalchemy import select
    return list(db.scalars(
        select(Section).where(Section.project_id == project.id).order_by(Section.order)
    ))


def _tiptap_to_markdown(doc_json: dict) -> str:
    """Tiptap JSON → Markdown 纯文本（简化版）。"""
    parts: list[str] = []

    def walk(node: Any):
        if isinstance(node, dict):
            ntype = node.get("type")
            if ntype == "text":
                text = node.get("text", "")
                marks = node.get("marks", [])
                if any(m.get("type") == "bold" for m in marks):
                    text = f"**{text}**"
                parts.append(text)
            elif ntype == "paragraph":
                for child in node.get("content", []):
                    walk(child)
                parts.append("\n\n")
            elif ntype == "heading":
                level = node.get("attrs", {}).get("level", 2)
                parts.append(f"\n{'#' * level} ")
                for child in node.get("content", []):
                    walk(child)
                parts.append("\n\n")
            elif ntype in ("bulletList", "orderedList"):
                for child in node.get("content", []):
                    walk(child)
            elif ntype == "listItem":
                parts.append("- ")
                for child in node.get("content", []):
                    walk(child)
                parts.append("\n")
            else:
                for child in node.get("content", []):
                    walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc_json)
    return "".join(parts).strip()


def _render_tiptap_to_docx(doc: Document, doc_json: dict) -> None:
    """把 Tiptap JSON 渲染到 python-docx Document。"""
    def walk(node: Any):
        if isinstance(node, dict):
            ntype = node.get("type")
            if ntype == "paragraph":
                texts = []
                for child in node.get("content", []):
                    texts.append(_get_text(child))
                doc.add_paragraph("".join(texts))
            elif ntype == "heading":
                level = node.get("attrs", {}).get("level", 2)
                texts = []
                for child in node.get("content", []):
                    texts.append(_get_text(child))
                doc.add_heading("".join(texts), level=min(level, 3))
            elif ntype in ("bulletList", "orderedList"):
                style = "List Bullet" if ntype == "bulletList" else "List Number"
                for item in node.get("content", []):
                    if item.get("type") == "listItem":
                        texts = []
                        for child in item.get("content", []):
                            texts.append(_get_text(child))
                        doc.add_paragraph("".join(texts), style=style)
            else:
                for child in node.get("content", []):
                    walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc_json)


def _get_text(node: dict) -> str:
    """从 Tiptap text 节点取文本。"""
    if node.get("type") == "text":
        return node.get("text", "")
    return ""
```

- [ ] **Step 2: 导出 API**

Create `apps/api/app/api/export.py`:
```python
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import export_service, project_service

router = APIRouter(tags=["export"])


@router.get("/projects/{project_id}/preview")
def preview(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """全篇预览（合并章节）。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    from app.services.export_service import _get_ordered_sections
    sections = _get_ordered_sections(db, project)
    return {
        "title": project.title,
        "metadata": project.metadata_,
        "sections": [
            {
                "order": s.order, "key": s.key, "title": s.title,
                "content": s.content, "status": s.status,
            }
            for s in sections
        ],
    }


@router.get("/projects/{project_id}/export/markdown")
def export_markdown(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    md = export_service.export_markdown(db, project=project)
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{project.title}.md"},
    )


@router.get("/projects/{project_id}/export/docx")
def export_docx(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    docx_bytes = export_service.export_docx(db, project=project)
    return Response(
        docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=project.docx"},
    )
```

- [ ] **Step 3: 注册路由 + 测试 + Commit**

Modify router.py 加 export 路由。

```bash
cd apps/api && uv run pytest tests/ -v
git add apps/api/app/services/export_service.py apps/api/app/api/export.py apps/api/app/api/router.py
git commit -m "feat: 导出渲染器（Tiptap→docx/Markdown）+ 全篇预览 API"
```

---

## 任务 3：前端——全篇预览页 + 导出按钮 + 版本抽屉

**Files:**
- Create: `apps/web/src/app/(app)/projects/[id]/preview/page.tsx`
- Create: `apps/web/src/components/version-drawer.tsx`
- Modify: `apps/web/src/app/(app)/projects/[id]/page.tsx`（加预览/导出入口 + 版本按钮）
- Modify: `apps/web/src/lib/api.ts`（加 preview/export/versions）

- [ ] **Step 1: api.ts 扩展**

追加到 api 对象:
```typescript
  // ── 版本 ──
  listVersions: (sectionId: string) =>
    request<import('@/types/api').Version[]>(`/sections/${sectionId}/versions`),
  createVersion: (sectionId: string, note?: string) =>
    request<import('@/types/api').Version>(`/sections/${sectionId}/versions`, {
      method: 'POST', body: JSON.stringify({ note }),
    }),
  rollbackVersion: (sectionId: string, versionId: string) =>
    request<{ message: string }>(`/sections/${section_id}/versions/${versionId}/rollback`, { method: 'POST' }),

  // ── 预览/导出 ──
  previewProject: (projectId: string) =>
    request<{ title: string; metadata: any; sections: any[] }>(`/projects/${projectId}/preview`),

  exportDocxUrl: (projectId: string) => `${BASE}/api/v1/projects/${projectId}/export/docx`,
  exportMarkdownUrl: (projectId: string) => `${BASE}/api/v1/projects/${projectId}/export/markdown`,
```

types/api.ts 加 Version 类型:
```typescript
export interface Version {
  id: string
  section_id: string
  content: Record<string, unknown> | null
  summary: string | null
  created_by: string
  note: string | null
  created_at: string
}
```

- [ ] **Step 2: 全篇预览页**

Create `apps/web/src/app/(app)/projects/[id]/preview/page.tsx`:
```tsx
'use client'

import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { TiptapEditor } from '@/components/editor/tiptap-editor'

export default function PreviewPage() {
  const params = useParams<{ id: string }>()
  const { data, isLoading } = useQuery({
    queryKey: ['preview', params.id],
    queryFn: () => api.previewProject(params.id),
  })

  if (isLoading) return <p className="text-muted-foreground">加载中...</p>
  if (!data) return null

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-bold">{data.title}</h1>
        {data.metadata?.inventors && (
          <p className="text-sm text-muted-foreground">
            发明人：{data.metadata.inventors.join('、')}
          </p>
        )}
      </div>
      <hr />
      {data.sections.map((s: any) => (
        <div key={s.order} className="space-y-2">
          <h2 className="text-lg font-semibold">{s.title}</h2>
          <div className="border rounded-lg p-4">
            {s.content ? (
              <TiptapEditor content={s.content} editable={false} />
            ) : (
              <p className="text-muted-foreground">（待填写）</p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: 版本抽屉组件**

Create `apps/web/src/components/version-drawer.tsx`:
```tsx
'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

interface VersionDrawerProps {
  sectionId: string
  open: boolean
  onClose: () => void
}

export function VersionDrawer({ sectionId, open, onClose }: VersionDrawerProps) {
  const qc = useQueryClient()
  const { data: versions } = useQuery({
    queryKey: ['versions', sectionId],
    queryFn: () => api.listVersions(sectionId),
    enabled: open && !!sectionId,
  })

  const rollback = useMutation({
    mutationFn: (versionId: string) => api.rollbackVersion(sectionId, versionId),
    onSuccess: () => {
      toast.success('已回滚')
      qc.invalidateQueries({ queryKey: ['sections'] })
      onClose()
    },
  })

  if (!open) return null

  return (
    <div className="fixed inset-y-0 right-0 w-96 border-l bg-background p-4 shadow-lg overflow-y-auto">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold">版本历史</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>关闭</Button>
      </div>
      <div className="space-y-2">
        {versions?.map((v) => (
          <div key={v.id} className="rounded-lg border p-3 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {new Date(v.created_at).toLocaleString('zh-CN')}
              </span>
              <span className="text-xs bg-muted px-2 py-0.5 rounded">
                {v.created_by === 'auto' ? '自动' : '手动'}
              </span>
            </div>
            {v.note && <p className="text-sm">{v.note}</p>}
            <Button
              size="sm" variant="outline"
              onClick={() => rollback.mutate(v.id)}
              disabled={rollback.isPending}
            >
              回滚到此版本
            </Button>
          </div>
        ))}
        {versions?.length === 0 && (
          <p className="text-sm text-muted-foreground">暂无版本记录</p>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 项目详情页加预览/导出/版本入口**

在项目详情页顶部操作栏加按钮（标题旁）:
```tsx
<div className="flex items-center gap-2">
  <a href={`/projects/${projectId}/preview`}>
    <Button variant="outline" size="sm">预览</Button>
  </a>
  <a href={api.exportDocxUrl(projectId)} target="_blank">
    <Button variant="outline" size="sm">导出 Word</Button>
  </a>
  <Button variant="outline" size="sm" onClick={() => setVersionOpen(true)}>版本</Button>
  <Button onClick={handleConfirm} disabled={updateSection.isPending}>确认完成</Button>
</div>
```

并在组件里加版本抽屉状态:
```tsx
const [versionOpen, setVersionOpen] = useState(false)
// 在 return 末尾加:
{current && <VersionDrawer sectionId={current.id} open={versionOpen} onClose={() => setVersionOpen(false)} />}
```

- [ ] **Step 5: 构建验证 + Commit**

```bash
cd apps/web && pnpm build
git add apps/web/
git commit -m "feat: 前端全篇预览页 + 导出按钮 + 版本历史抽屉"
```

---

## 任务 4：端到端验证

- [ ] **Step 1: 启动后端**

```bash
cd apps/api && uv run uvicorn app.main:app --reload
```

- [ ] **Step 2: 验证版本/预览/导出 API**

```bash
# 登录获取 cookie
# 创建项目 → 获取 section
# 更新 section content → 创建版本 → 列出版本 → 回滚
# 导出 Markdown → 验证内容
# 导出 docx → 验证文件下载
# 全篇预览 → 验证合并章节
```

- [ ] **Step 3: 浏览器验证**

1. 进入项目 → 编辑章节 → 点「版本」→ 看到版本历史
2. 点「预览」→ 看到全篇合并视图
3. 点「导出 Word」→ 下载 .docx 文件

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "chore: 计划 5 版本/预览/导出端到端验证通过"
```

---

## 完成标准

- [ ] SectionVersion 模型 + 版本 API（列表/创建/回滚）
- [ ] 确认章节时自动存版本
- [ ] 导出渲染器（Tiptap→docx + Markdown）
- [ ] 全篇预览 API + 页面
- [ ] 导出 Word/Markdown API + 按钮
- [ ] 前端版本历史抽屉
- [ ] 端到端验证通过
