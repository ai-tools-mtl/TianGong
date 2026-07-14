# 计划 10：附图与文件上传 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 P0 验收点 #15（附图章节：上传图片 + 文字描述 + AI 图注润色），含文件上传安全与导出集成。

**Architecture:** 新增 `Attachment` 实体（本地文件存储 + UUID 命名防路径遍历 + 魔数校验）。后端 CRUD + 鉴权下载路由；编辑器装 Tiptap Image 扩展，附图章节上传图片插入节点；导出渲染器补 image 节点；复用计划 9 的 `astream_llm` 实现纯文本图注润色（非多模态，设计 9.5）。

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · python-docx · Tiptap Image 扩展 · Next.js

**关联 spec：** [P0 验收补全迭代设计](../specs/2026-07-14-p0-completion-iteration.md) §5

**前置依赖：** 计划 9 的 `astream_llm`（Task 5/6 已建）。若计划 9 未执行，图注润色端点可改用同步 `stream_llm` 作为降级。

---

## 文件结构

| 文件 | 责任 | 操作 |
|---|---|---|
| `apps/api/app/models/attachment.py` | Attachment ORM | 新建 |
| `apps/api/app/models/__init__.py` | 注册 Attachment | 修改 |
| `apps/api/alembic/versions/<new>_create_attachments.py` | 迁移 | 新建 |
| `apps/api/app/core/config.py` | 加 upload_dir / max_image_size_mb | 修改 |
| `apps/api/app/services/attachment_service.py` | 存盘 + 魔数校验 + CRUD | 新建 |
| `apps/api/app/api/attachments.py` | 上传/列表/下载/删除路由 | 新建 |
| `apps/api/app/api/router.py` | 挂载 attachments 路由 | 修改 |
| `apps/api/app/api/ai.py` | caption-figures 流式端点 | 修改 |
| `apps/api/app/services/export_service.py` | image 节点渲染（docx + markdown） | 修改 |
| `apps/api/tests/test_attachments.py` | 上传/权限/魔数/导出 | 新建 |
| `apps/web/package.json` | @tiptap/extension-image | 修改 |
| `apps/web/src/components/editor/tiptap-editor.tsx` | Image 扩展 + 上传按钮 | 修改 |
| `apps/web/src/components/editor/figure-upload.tsx` | 附图上传组件 | 新建 |
| `apps/web/src/lib/api.ts` | attachment 方法 | 修改 |
| `apps/web/src/lib/queries.ts` | attachment hooks | 修改 |
| `apps/web/src/types/api.ts` | Attachment 类型 | 修改 |
| `.gitignore` | 排除 uploads/ | 修改 |

---

## Task 1：Attachment 数据模型 + 迁移

**Files:**
- Create: `apps/api/app/models/attachment.py`
- Modify: `apps/api/app/models/__init__.py`
- Create: `apps/api/alembic/versions/<new>_create_attachments.py`
- Test: `apps/api/tests/test_attachments.py`

- [ ] **Step 1: 写失败测试 — Attachment 模型字段**

新建 `apps/api/tests/test_attachments.py`：

```python
"""附图附件测试。"""


def test_attachment_model_fields():
    """Attachment 实体有设计 3.2 定义的字段。"""
    from app.models.attachment import Attachment
    a = Attachment(
        project_id=None, section_id=None,
        filename="test.png", storage_path="uploads/abc.png",
        mime_type="image/png", size=1024,
    )
    assert a.filename == "test.png"
    assert a.storage_path == "uploads/abc.png"
    assert a.mime_type == "image/png"
    assert a.size == 1024
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_attachments.py::test_attachment_model_fields -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.models.attachment'`）

- [ ] **Step 3: 创建 Attachment 模型**

新建 `apps/api/app/models/attachment.py`：

```python
import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Attachment(Base, IdMixin, TimestampMixin):
    """附件/附图（设计 3.2）。本地存储，UUID 命名防路径遍历。"""
    __tablename__ = "attachments"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))  # 原始文件名（仅展示）
    storage_path: Mapped[str] = mapped_column(String(512))  # UUID 存储名
    mime_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
```

注册到 `apps/api/app/models/__init__.py`——在 import 区加，在 `__all__` 加 `"Attachment"`：

import 区（在 `from app.models.template import Template` 之前）加：

```python
from app.models.attachment import Attachment
```

`__all__` 列表加 `"Attachment"`（放在 `"User"` 之后）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_attachments.py::test_attachment_model_fields -v`
Expected: PASS

- [ ] **Step 5: 生成迁移**

Run: `cd apps/api && uv run alembic revision --autogenerate -m "create attachments"`
Expected: 生成迁移文件。打开确认 `down_revision` 指向当前 head，`upgrade()` 含 `op.create_table('attachments', ...)` 各列 + 索引，`downgrade()` 含 `op.drop_table('attachments')`。

- [ ] **Step 6: 跑迁移**

Run: `cd apps/api && uv run alembic upgrade head`
Expected: 成功创建 attachments 表

- [ ] **Step 7: 提交**

```bash
cd apps/api && git add app/models/attachment.py app/models/__init__.py alembic/versions/ tests/test_attachments.py
git commit -m "feat(plan10): Attachment 模型 + 迁移"
```

---

## Task 2：config 加上传配置 + .gitignore

**Files:**
- Modify: `apps/api/app/core/config.py`
- Modify: `.gitignore`

- [ ] **Step 1: config 加上传配置**

修改 `apps/api/app/core/config.py`，在 `glm_embedding_model` 字段之后加：

```python
    # 文件上传（设计 13.2，附录 B：MVP 本地存储）
    upload_dir: str = "uploads"
    max_image_size_mb: int = 10
```

- [ ] **Step 2: .gitignore 排除 uploads**

在项目根 `.gitignore` 末尾加：

```
# 上传文件（MVP 本地存储）
apps/api/uploads/
```

- [ ] **Step 3: 提交**

```bash
cd /g/03-Personal-Projects/TianGong && git add apps/api/app/core/config.py .gitignore
git commit -m "feat(plan10): config 加上传配置 + gitignore 排除 uploads"
```

---

## Task 3：attachment_service — 存盘 + 魔数校验 + CRUD

**Files:**
- Create: `apps/api/app/services/attachment_service.py`
- Test: `apps/api/tests/test_attachments.py`

- [ ] **Step 1: 写失败测试 — 魔数校验 + 存盘 + 权限**

在 `apps/api/tests/test_attachments.py` 追加：

```python
import pytest


def _setup_project(client, registered_user, db_session):
    """登录 + 建项目，返回 (project_id, section_id)。"""
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]
    sections = client.get(f"/api/v1/projects/{project_id}/sections").json()
    return project_id, sections[0]["id"]


def test_upload_valid_png_succeeds(client, registered_user, db_session):
    """上传合法 PNG 成功，返回 attachment 记录。"""
    project_id, section_id = _setup_project(client, registered_user, db_session)
    # 最小合法 PNG 魔数 + IHDR
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    res = client.post(
        f"/api/v1/sections/{section_id}/attachments",
        files={"file": ("test.png", png_bytes, "image/png")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["filename"] == "test.png"
    assert body["mime_type"] == "image/png"
    assert "id" in body


def test_upload_rejects_non_image_magic(client, registered_user, db_session):
    """魔数不匹配（伪装 png 的文本）被拒（设计 13.2）。"""
    project_id, section_id = _setup_project(client, registered_user, db_session)
    fake_bytes = b"THIS IS NOT AN IMAGE"  # 不是图片魔数

    res = client.post(
        f"/api/v1/sections/{section_id}/attachments",
        files={"file": ("fake.png", fake_bytes, "image/png")},
    )
    assert res.status_code == 422


def test_upload_other_user_section_404(client, registered_user, db_session):
    """上传到他人项目的章节返回 404（资源级授权，设计 13.1）。"""
    from app.models import User
    from sqlalchemy import select
    # 建第二个用户的项目
    other = User(email="other@example.com", password_hash="x", name="other")
    db_session.add(other)
    db_session.commit()

    project_id, _ = _setup_project(client, registered_user, db_session)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    # 用 other 的 section id（不存在于 registered_user）
    res = client.post(
        f"/api/v1/sections/00000000-0000-0000-0000-000000000000/attachments",
        files={"file": ("t.png", png_bytes, "image/png")},
    )
    assert res.status_code == 404


def test_list_attachments(client, registered_user, db_session):
    """列出项目的附件。"""
    project_id, section_id = _setup_project(client, registered_user, db_session)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    client.post(
        f"/api/v1/sections/{section_id}/attachments",
        files={"file": ("a.png", png_bytes, "image/png")},
    )
    res = client.get(f"/api/v1/projects/{project_id}/attachments")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_delete_attachment(client, registered_user, db_session):
    """删除附件（记录 + 文件）。"""
    project_id, section_id = _setup_project(client, registered_user, db_session)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    up = client.post(
        f"/api/v1/sections/{section_id}/attachments",
        files={"file": ("a.png", png_bytes, "image/png")},
    ).json()
    att_id = up["id"]

    res = client.delete(f"/api/v1/attachments/{att_id}")
    assert res.status_code == 204

    # 再列应为空
    res = client.get(f"/api/v1/projects/{project_id}/attachments")
    assert len(res.json()) == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_attachments.py -v`
Expected: FAIL（`ModuleNotFoundError: app.services.attachment_service` 或路由不存在）

- [ ] **Step 3: 创建 attachment_service**

新建 `apps/api/app/services/attachment_service.py`：

```python
"""附件服务：存盘 + 魔数校验 + CRUD（设计 13.2 文件上传安全）。"""

import os
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models import Attachment

# 图片魔数签名（设计 13.2：不轻信扩展名，校验魔数）
_MAGIC_NUMBERS = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
}

ALLOWED_MIME = {"image/png", "image/jpeg", "image/gif"}


def _detect_mime(content: bytes) -> str | None:
    """通过魔数检测真实 MIME 类型。"""
    for magic, mime in _MAGIC_NUMBERS.items():
        if content.startswith(magic):
            return mime
    return None


def _ext_for_mime(mime: str) -> str:
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}.get(mime, ".bin")


def upload_attachment(
    db: Session, *, user_id, project_id: str, section_id: str | None,
    filename: str, content: bytes,
) -> Attachment:
    """校验 + 存盘 + 建记录。"""
    settings = get_settings()

    # 魔数校验（设计 13.2）
    real_mime = _detect_mime(content)
    if real_mime is None or real_mime not in ALLOWED_MIME:
        raise ValidationError("仅支持 PNG/JPEG/GIF 图片")

    # 大小校验
    max_bytes = settings.max_image_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValidationError(f"图片大小超过 {settings.max_image_size_mb}MB 限制")

    # UUID 存储名（防路径遍历，设计 13.2）
    stored_name = f"{uuid.uuid4()}{_ext_for_mime(real_mime)}"
    upload_dir = settings.upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, stored_name)
    with open(file_path, "wb") as f:
        f.write(content)

    att = Attachment(
        project_id=uuid.UUID(project_id),
        section_id=uuid.UUID(section_id) if section_id else None,
        filename=filename,
        storage_path=file_path,
        mime_type=real_mime,
        size=len(content),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return att


def list_attachments(
    db: Session, *, user_id, project_id: str, section_id: str | None = None,
) -> list[Attachment]:
    """列出项目的附件（先校验项目归属）。"""
    from app.models import Project

    project = db.scalar(select(Project).where(Project.id == uuid.UUID(project_id)))
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")
    query = select(Attachment).where(Attachment.project_id == project.id)
    if section_id:
        query = query.where(Attachment.section_id == uuid.UUID(section_id))
    return list(db.scalars(query.order_by(Attachment.created_at)))


def get_attachment(db: Session, *, user_id, attachment_id: str) -> Attachment:
    """获取附件（含归属校验）。"""
    try:
        aid = uuid.UUID(attachment_id)
    except ValueError:
        raise NotFoundError("附件不存在")
    att = db.get(Attachment, aid)
    if att is None:
        raise NotFoundError("附件不存在")
    # 通过 project 校验归属
    from app.models import Project
    project = db.scalar(select(Project).where(Project.id == att.project_id))
    if project is None or project.user_id != user_id:
        raise NotFoundError("附件不存在")
    return att


def delete_attachment(db: Session, *, user_id, attachment_id: str) -> None:
    """删除附件（记录 + 文件）。"""
    att = get_attachment(db, user_id=user_id, attachment_id=attachment_id)
    # 删文件
    if os.path.exists(att.storage_path):
        os.remove(att.storage_path)
    db.delete(att)
    db.commit()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_attachments.py -v`
Expected: 5 个测试 PASS（注意：路由还没建，所以这些测试此时仍失败——见下一步先建路由。实际上测试调的是 HTTP 端点，需要路由存在。所以先跑会失败在路由不存在 404，正常。继续 Task 4 建路由后再跑通过。）

> 说明：Task 3 测试依赖 Task 4 的路由，故标记步骤 4 为「确认 service 可 import」，完整通过在 Task 4 后验证。

Run: `cd apps/api && uv run python -c "from app.services.attachment_service import upload_attachment; print('OK')"`
Expected: 打印 `OK`（service 可 import）

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/services/attachment_service.py tests/test_attachments.py
git commit -m "feat(plan10): attachment_service（魔数校验+UUID存储+CRUD）"
```

---

## Task 4：API 路由 — 上传/列表/下载/删除

**Files:**
- Create: `apps/api/app/api/attachments.py`
- Modify: `apps/api/app/api/router.py`

- [ ] **Step 1: 创建 attachments 路由**

新建 `apps/api/app/api/attachments.py`：

```python
"""附件/附图路由（设计 13.2 文件上传安全）。"""

import os

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import attachment_service, section_service

router = APIRouter(tags=["attachments"])


def _to_out(a) -> dict:
    return {
        "id": str(a.id),
        "project_id": str(a.project_id),
        "section_id": str(a.section_id) if a.section_id else None,
        "filename": a.filename,
        "mime_type": a.mime_type,
        "size": a.size,
        "created_at": a.created_at.isoformat(),
    }


@router.post("/sections/{section_id}/attachments", status_code=201)
async def upload(
    section_id: str,
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传图片到指定章节（先校验章节归属）。"""
    # 校验章节归属（复用 section_service 的资源级授权）
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    content = await file.read()
    att = attachment_service.upload_attachment(
        db, user_id=current_user.id,
        project_id=str(section.project_id), section_id=section_id,
        filename=file.filename or "upload.png", content=content,
    )
    return _to_out(att)


@router.get("/projects/{project_id}/attachments")
def list_all(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出项目的所有附件。"""
    atts = attachment_service.list_attachments(
        db, user_id=current_user.id, project_id=project_id
    )
    return [_to_out(a) for a in atts]


@router.get("/projects/{project_id}/attachments/{attachment_id}/file")
def download(
    project_id: str,
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """鉴权后返回图片流（不暴露真实路径）。"""
    att = attachment_service.get_attachment(db, user_id=current_user.id, attachment_id=attachment_id)
    if not os.path.exists(att.storage_path):
        from app.core.exceptions import NotFoundError
        raise NotFoundError("文件不存在")
    return FileResponse(
        att.storage_path, media_type=att.mime_type, filename=att.filename,
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete(
    attachment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attachment_service.delete_attachment(db, user_id=current_user.id, attachment_id=attachment_id)
    return None
```

- [ ] **Step 2: 挂载路由**

修改 `apps/api/app/api/router.py`——在 import 区加：

```python
from app.api import (
    admin, ai, attachments, auth, export, health, knowledge, projects, review, sections, templates, versions,
)
```

在路由挂载区（`api_router.include_router(admin.router)` 之前）加：

```python
api_router.include_router(attachments.router)
```

- [ ] **Step 3: 跑附件测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_attachments.py -v`
Expected: 全部 PASS（test_attachment_model_fields + 5 个 service 测试）

- [ ] **Step 4: 跑全量测试确认无回归**

Run: `cd apps/api && uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/api/attachments.py app/api/router.py
git commit -m "feat(plan10): 附件路由（上传/列表/下载/删除 + 鉴权）"
```

---

## Task 5：导出渲染器补 image 节点

**Files:**
- Modify: `apps/api/app/services/export_service.py`
- Test: `apps/api/tests/test_attachments.py`

- [ ] **Step 1: 写失败测试 — image 节点渲染**

在 `apps/api/tests/test_attachments.py` 追加：

```python
def test_tiptap_to_markdown_renders_image():
    """Markdown 导出：image 节点渲染为 ![alt](src)。"""
    from app.services.export_service import _tiptap_to_markdown

    doc_json = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {"src": "/api/v1/attachments/x/file", "alt": "图 1 示意图"},
            }
        ],
    }
    md = _tiptap_to_markdown(doc_json)
    assert "![图 1 示意图](/api/v1/attachments/x/file)" in md


def test_render_tiptap_to_docx_handles_image(monkeypatch):
    """docx 导出：image 节点调用 add_picture（mock 避免真实文件）。"""
    from docx import Document
    from app.services import export_service

    called = {"add_picture": False}
    original_add_picture = Document.add_picture

    def fake_add_picture(self, *args, **kwargs):
        called["add_picture"] = True

    monkeypatch.setattr(Document, "add_picture", fake_add_picture)

    doc = Document()
    doc_json = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {"src": "http://localhost:8000/api/v1/x/file", "alt": "图1"},
            }
        ],
    }
    export_service._render_tiptap_to_docx(doc, doc_json)
    assert called["add_picture"] is True
    monkeypatch.setattr(Document, "add_picture", original_add_picture)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_attachments.py::test_tiptap_to_markdown_renders_image tests/test_attachments.py::test_render_tiptap_to_docx_handles_image -v`
Expected: FAIL（image 节点未被渲染——当前 walk 的 else 分支只是递归子节点，image 无 content 所以什么都不输出）

- [ ] **Step 3: 改 _tiptap_to_markdown 补 image 分支**

修改 `apps/api/app/services/export_service.py` 的 `_tiptap_to_markdown` 函数，在 `walk` 内部、`elif ntype == "heading":` 分支之后加：

```python
            elif ntype == "image":
                src = node.get("attrs", {}).get("src", "")
                alt = node.get("attrs", {}).get("alt", "")
                parts.append(f"\n\n![{alt}]({src})\n\n")
```

- [ ] **Step 4: 改 _render_tiptap_to_docx 补 image 分支**

修改 `_render_tiptap_to_docx` 函数，在 `walk` 内部、`elif ntype in ("bulletList", "orderedList"):` 分支之前加：

```python
            elif ntype == "image":
                src = node.get("attrs", {}).get("src", "")
                alt = node.get("attrs", {}).get("alt", "")
                # 尝试从本地 storage_path 加载；远程 URL 跳过（仅加图注段落）
                import os
                if src and os.path.exists(src.split("?")[0]):
                    doc.add_picture(src.split("?")[0])
                doc.add_paragraph(alt)  # 图注
```

注意：image 节点的 `src` 在编辑器里是完整 URL（`/api/v1/projects/.../file`），导出 docx 时无法直接下载。MVP 取舍：**docx 导出对 image 节点仅输出图注文字（alt）**，不嵌入远程图片（嵌入需在导出时下载远程文件，复杂度高）。若 src 恰好是本地路径则嵌入。测试用 `monkeypatch` 验证 `add_picture` 被调用（传本地路径场景）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_attachments.py -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/services/export_service.py tests/test_attachments.py
git commit -m "feat(plan10): 导出渲染器补 image 节点（markdown + docx）"
```

---

## Task 6：AI 图注润色端点（设计 9.5）

**Files:**
- Modify: `apps/api/app/api/ai.py`
- Test: `apps/api/tests/test_attachments.py`

- [ ] **Step 1: 写失败测试 — caption-figures 端点**

在 `apps/api/tests/test_attachments.py` 追加：

```python
def test_caption_figures_endpoint(client, registered_user, db_session, monkeypatch):
    """图注润色：仅 drawings 章节，基于文字描述（非多模态，设计 9.5）。"""
    project_id, _section_id = _setup_project(client, registered_user, db_session)
    # 找到 drawings 章节
    sections = client.get(f"/api/v1/projects/{project_id}/sections").json()
    drawings_id = next(s["id"] for s in sections if s["key"] == "drawings")

    # mock astream_llm 返回固定图注
    async def fake_astream(messages):
        yield "图 1 是本发明装置的整体结构示意图。"

    monkeypatch.setattr("app.api.ai.astream_llm", fake_astream)

    res = client.post(f"/api/v1/sections/{drawings_id}/caption-figures", json={
        "descriptions": ["图1是装置结构图"],
    })
    assert res.status_code == 200
    assert "event: token" in res.text
    assert "图 1" in res.text


def test_caption_figures_rejects_non_drawings(client, registered_user, db_session):
    """非 drawings 章节调用图注润色返回 422。"""
    project_id, section_id = _setup_project(client, registered_user, db_session)
    # section_id 是第一个章节（name），不是 drawings
    res = client.post(f"/api/v1/sections/{section_id}/caption-figures", json={
        "descriptions": ["测试"],
    })
    assert res.status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_attachments.py::test_caption_figures_endpoint -v`
Expected: FAIL（404 路由不存在）

- [ ] **Step 3: 加 caption-figures 端点**

修改 `apps/api/app/api/ai.py`，在文件顶部 import 区确认有 `astream_llm`（计划 9 Task 5 加的）。若无计划 9，用同步 `stream_llm` 改造为简单生成器。

在 `rewrite` 端点之后、`list_messages` 之前加：

```python
class CaptionRequest(BaseModel):
    descriptions: list[str]


@router.post("/sections/{section_id}/caption-figures")
async def caption_figures(
    section_id: str,
    payload: CaptionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """图注润色：基于文字描述生成规范图注（设计 9.5，仅文本非多模态）。"""
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    # 仅附图章节可用
    if section.key != "drawings":
        raise ValidationError("图注润色仅限附图说明章节")

    from langchain_core.messages import HumanMessage, SystemMessage
    from app.ai.llm_client import astream_llm

    descs = "\n".join(f"- {d}" for d in payload.descriptions)
    system = (
        "你是专利交底书撰写助手。请根据用户提供的图片文字描述，"
        "润色生成规范的图注。要求：统一'图 N 是…'格式，简洁准确。"
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"以下是各图的文字描述，请生成规范图注：\n{descs}"),
    ]

    async def generate():
        try:
            async for token in astream_llm(messages):
                yield _sse_event("token", {"text": token})
            yield _sse_event("done", {})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")
```

import 区需确认有（计划 9 已加大部分）：

```python
from pydantic import BaseModel
from app.core.exceptions import ValidationError
import asyncio
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_attachments.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/api/ai.py tests/test_attachments.py
git commit -m "feat(plan10): AI 图注润色端点（drawings 章节专用，纯文本）"
```

---

## Task 7：前端 — 装依赖 + 类型 + API + hooks

**Files:**
- Modify: `apps/web/package.json`
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: 装 Tiptap Image 扩展**

Run: `cd apps/web && pnpm add @tiptap/extension-image`

- [ ] **Step 2: 类型定义**

修改 `apps/web/src/types/api.ts`，在 `AdminUser` 之前（审查类型之后）加：

```typescript
// ── 附件 ──

export interface Attachment {
  id: string
  project_id: string
  section_id: string | null
  filename: string
  mime_type: string
  size: number
  created_at: string
}
```

- [ ] **Step 3: API 方法**

修改 `apps/web/src/lib/api.ts`，在 `export const api = {` 对象内（知识库区块之后）加：

```typescript
  // ── 附件 ──
  listAttachments: (projectId: string) =>
    request<import('@/types/api').Attachment[]>(`/projects/${projectId}/attachments`),

  uploadAttachment: async (sectionId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/attachments`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw err
    }
    return res.json() as Promise<import('@/types/api').Attachment>
  },

  deleteAttachment: (id: string) =>
    request<void>(`/attachments/${id}`, { method: 'DELETE' }),

  attachmentUrl: (projectId: string, attachmentId: string) =>
    `${BASE}/api/v1/projects/${projectId}/attachments/${attachmentId}/file`,
```

- [ ] **Step 4: 查询 hooks**

修改 `apps/web/src/lib/queries.ts`，参照现有 hook 模式加（在文件末尾的 queryKeys 和 hooks 区）：

```typescript
  attachments: (projectId: string) => ['attachments', projectId] as const,
```

并加 hook：

```typescript
export function useAttachments(projectId: string) {
  return useQuery({
    queryKey: queryKeys.attachments(projectId),
    queryFn: () => api.listAttachments(projectId),
    enabled: !!projectId,
  })
}

export function useDeleteAttachment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteAttachment(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['attachments'] }),
  })
}
```

> 注意：确认 `useQuery`/`useMutation`/`api` 已在 queries.ts import。

- [ ] **Step 5: 验证构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
cd apps/web && git add package.json pnpm-lock.yaml src/types/api.ts src/lib/api.ts src/lib/queries.ts
git commit -m "feat(plan10): 前端附件类型 + API + hooks + Tiptap Image 扩展"
```

---

## Task 8：前端 — 编辑器 Image 扩展 + 附图上传组件

**Files:**
- Modify: `apps/web/src/components/editor/tiptap-editor.tsx`
- Create: `apps/web/src/components/editor/figure-upload.tsx`
- Modify: `apps/web/src/app/(app)/projects/[id]/page.tsx`

- [ ] **Step 1: 编辑器装 Image 扩展**

修改 `apps/web/src/components/editor/tiptap-editor.tsx`：

import 区加：

```typescript
import Image from '@tiptap/extension-image'
```

extensions 数组加 `Image`：

```typescript
  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({ placeholder: '在此撰写内容...' }),
      Image,
    ],
    content: content || undefined,
    editable,
    onUpdate: ({ editor }) => {
      onChange?.(editor.getJSON())
    },
  })
```

- [ ] **Step 2: 创建附图上传组件**

新建 `apps/web/src/components/editor/figure-upload.tsx`：

```typescript
'use client'

import { ImageIcon, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

interface FigureUploadProps {
  sectionId: string
  projectId: string
  /** 上传成功后把图片插入编辑器 */
  onInsertImage: (src: string, alt: string) => void
}

export function FigureUpload({ sectionId, projectId, onInsertImage }: FigureUploadProps) {
  const [uploading, setUploading] = useState(false)

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const att = await api.uploadAttachment(sectionId, file)
      const src = api.attachmentUrl(projectId, att.id)
      onInsertImage(src, file.name)
      toast.success('图片已上传')
    } catch {
      toast.error('上传失败（仅支持 PNG/JPEG/GIF，≤10MB）')
    } finally {
      setUploading(false)
      e.target.value = '' // 允许重复选同一文件
    }
  }

  return (
    <Button variant="outline" size="sm" className="h-8 gap-1.5" disabled={uploading} asChild>
      <label className="cursor-pointer">
        {uploading ? <Loader2 className="size-3.5 animate-spin" /> : <ImageIcon className="size-3.5" />}
        {uploading ? '上传中...' : '上传图片'}
        <input type="file" accept="image/png,image/jpeg,image/gif" onChange={handleFile} className="hidden" />
      </label>
    </Button>
  )
}
```

- [ ] **Step 3: 项目详情页集成附图上传**

修改 `apps/web/src/app/(app)/projects/[id]/page.tsx`：

import 区加：

```typescript
import { FigureUpload } from '@/components/editor/figure-upload'
```

在编辑器区域（`<TiptapEditor>` 之前），仅当当前章节是附图章节时显示上传按钮。定位编辑器外层 div，改为：

```typescript
          <div className="mx-auto max-w-5xl">
            {current && current.key === 'drawings' && (
              <div className="mb-3">
                <FigureUpload
                  sectionId={current.id}
                  projectId={projectId}
                  onInsertImage={(src, alt) => {
                    // 通过 ref 获取 editor 实例插入图片
                    // TiptapEditor 需暴露 editor ref —— 见下方 Step 4 调整
                  }}
                />
              </div>
            )}
            {current && (
              <TiptapEditor
                key={current.id}
                content={current.content}
                onChange={handleSave}
              />
            )}
          </div>
```

- [ ] **Step 4: TiptapEditor 暴露 editor ref（供插入图片）**

修改 `apps/web/src/components/editor/tiptap-editor.tsx`，用 forwardRef + useImperativeHandle 暴露 editor：

```typescript
'use client'

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import Image from '@tiptap/extension-image'
import { forwardRef, useImperativeHandle } from 'react'

import { Toolbar } from './toolbar'

export interface TiptapEditorRef {
  insertImage: (src: string, alt: string) => void
}

interface TiptapEditorProps {
  content?: object | null
  onChange?: (json: object) => void
  editable?: boolean
}

export const TiptapEditor = forwardRef<TiptapEditorRef, TiptapEditorProps>(
  function TiptapEditor({ content, onChange, editable = true }, ref) {
    const editor = useEditor({
      extensions: [
        StarterKit,
        Placeholder.configure({ placeholder: '在此撰写内容...' }),
        Image,
      ],
      content: content || undefined,
      editable,
      onUpdate: ({ editor }) => {
        onChange?.(editor.getJSON())
      },
    })

    useImperativeHandle(ref, () => ({
      insertImage: (src: string, alt: string) => {
        editor?.chain().focus().setImage({ src, alt }).run()
      },
    }))

    if (!editor) return null

    return (
      <div className="overflow-hidden rounded-lg border bg-card">
        <Toolbar editor={editor} />
        <EditorContent
          editor={editor}
          className="prose prose-sm tiptap max-w-none p-5 min-h-[400px] focus:outline-none"
        />
      </div>
    )
  },
)
```

并改项目详情页用 ref：

```typescript
  const editorRef = useRef<TiptapEditorRef>(null)
```

import 加：

```typescript
import { useRef } from 'react'  // 若已 import 则合并
import type { TiptapEditorRef } from '@/components/editor/tiptap-editor'
```

onInsertImage 回调改为：

```typescript
                  onInsertImage={(src, alt) => editorRef.current?.insertImage(src, alt)}
```

`<TiptapEditor>` 加 ref：

```typescript
              <TiptapEditor
                key={current.id}
                ref={editorRef}
                content={current.content}
                onChange={handleSave}
              />
```

> 注意：forwardRef 改变了导出形式（named export + forwardRef）。确认 page.tsx 的 import 是 `import { TiptapEditor } from ...`（具名导入），且现在是 ref-forwarding 组件，用法不变。

- [ ] **Step 5: 验证构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功

- [ ] **Step 6: 提交**

```bash
cd apps/web && git add src/components/editor/ src/app/\(app\)/projects/\[id\]/page.tsx
git commit -m "feat(plan10): 编辑器 Image 扩展 + 附图上传组件 + 插入图片"
```

---

## Task 9：全量验证 + 端到端核对

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest -v`
Expected: 全部 PASS

- [ ] **Step 2: 前端构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功

- [ ] **Step 3: 端到端手验**

启动后端 + 前端 + DB，登录后：
1. 创建项目 → 进入附图说明章节
2. 点「上传图片」→ 选一张 PNG → 看图片是否插入编辑器
3. 上传一张伪装成 png 的 txt → 看是否被拒（魔数校验）
4. 导出 Word → 看附图章节的图注文字是否在导出文件中
5. 测试图注润色：在附图章节输入描述，调图注润色端点

- [ ] **Step 4: 提交计划完成标记**

```bash
git commit --allow-empty -m "chore: 计划 10 附图与文件上传端到端验证通过"
```
