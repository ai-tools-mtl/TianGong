# P1：项目管理改造 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决"项目管不过来"痛点——补活 `Project.status` 状态流转、工作台加状态筛选 tab + 标题搜索、新建用户私有标签系统（先建再贴，支持重命名/合并/删除）、删除二次确认防误删。

**Architecture:** 后端新增 `Tag`（用户私有标签）+ `project_tag`（项目-标签关联）两张表及全套 CRUD 服务；在 `update_section` 末尾加 Project.status 反写逻辑（section→drafting 则项目→in_progress；全部 confirmed 则→completed）；`list_projects` 默认排除 archived 并支持 status/q/search 查询参数。前端工作台从平铺网格升级为「搜索框 + 状态 Tabs + 标签筛选 + 项目卡片网格」，卡片操作改为 DropdownMenu（重命名/贴标签/归档/删除），删除走 Dialog 二次确认。标签管理独立成页（`/tags`）。

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest（SQLite 内存库） · Next.js · React · TanStack Query · shadcn/ui（new-york） · zustand · lucide-react

**关联 grilling 结论：** 共享/权限/代理人是后续独立 P1，本次不碰。搜索只搜标题（30 项目量级），不做全文检索。

**当前 Alembic HEAD：** `2f4a6a1e8472`（add audit_logs）

---

## 文件结构

| 文件 | 责任 | 操作 |
|---|---|---|
| `apps/api/app/models/tag.py` | `Tag` 模型（用户私有标签） | 新建 |
| `apps/api/app/models/project_tag.py` | `ProjectTag` 关联模型 | 新建 |
| `apps/api/app/models/__init__.py` | 注册 Tag / ProjectTag | 修改 |
| `apps/api/alembic/versions/<新>_add_tags.py` | 建 tags + project_tags 表 | 新建 |
| `apps/api/app/schemas/tag.py` | TagCreate / TagUpdate / TagOut / TagMerge | 新建 |
| `apps/api/app/schemas/project.py` | ProjectOut 补 `tags` 字段 | 修改 |
| `apps/api/app/services/tag_service.py` | 标签 CRUD + 合并 + 按项目贴/摘 | 新建 |
| `apps/api/app/services/project_service.py` | `list_projects` 支持 status/q + 排除 archived | 修改 |
| `apps/api/app/services/section_service.py` | `update_section` 末尾反写 Project.status | 修改 |
| `apps/api/app/api/projects.py` | `list_all` 透传查询参数；`_to_out` 输出 tags | 修改 |
| `apps/api/app/api/tags.py` | 标签 CRUD + 项目贴标签端点 | 新建 |
| `apps/api/app/api/router.py` | 注册 tags router | 修改 |
| `apps/api/tests/test_status_flow.py` | Project.status 流转测试 | 新建 |
| `apps/api/tests/test_project_query.py` | list_projects 查询参数测试 | 新建 |
| `apps/api/tests/test_tags.py` | 标签服务 + 端点测试 | 新建 |
| `apps/web/src/types/api.ts` | Project 补 tags；新增 Tag 类型 | 修改 |
| `apps/web/src/lib/api.ts` | 标签 CRUD + 项目查询参数方法 | 修改 |
| `apps/web/src/lib/queries.ts` | useTags / useUpdateProject / 标签 mutation hooks | 修改 |
| `apps/web/src/components/project-list.tsx` | 搜索框 + 状态 Tabs + 标签筛选 + 重命名/删除 Dialog 接线 | 修改 |
| `apps/web/src/components/project-card.tsx` | DropdownMenu 操作 + tags 徽标 | 修改 |
| `apps/web/src/components/rename-dialog.tsx` | 重命名弹窗 | 新建 |
| `apps/web/src/components/delete-confirm-dialog.tsx` | 删除二次确认弹窗 | 新建 |
| `apps/web/src/components/project-tag-dialog.tsx` | 项目贴标签弹窗 | 新建 |
| `apps/web/src/app/(app)/tags/page.tsx` | 标签管理页 | 新建 |
| `apps/web/src/components/tag-editor.tsx` | 标签列表 + 重命名/合并/删除 | 新建 |

---

## Task 1：状态流转——section 变更反写 Project.status

**背景：** 当前 `Project.status` 只有 `draft`（默认）和 `archived`（归档时设置）两个值真的会出现。`in_progress` / `completed` 从未被写入，导致状态筛选无意义。本 Task 在 `section_service.update_section` 末尾加反写逻辑，让状态机真正运转。

**状态机定义：**
- 任一 section 转入 `drafting` 或 `confirmed` → Project.status = `in_progress`
- 全部 sections 均为 `confirmed`（且至少 1 个 section）→ Project.status = `completed`
- 上述不满足且项目非 archived → 回落为 `draft`（仅当无任何 drafting/confirmed section 时）
- `archived` 状态由归档流程设置，本处不覆盖（归档后的 section 不会变动）

**Files:**
- Modify: `apps/api/app/services/section_service.py`
- Test: `apps/api/tests/test_status_flow.py`

- [ ] **Step 1: 写失败测试 — section 进 drafting 时 project 转 in_progress**

新建 `apps/api/tests/test_status_flow.py`：

```python
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.models import Base, Project, Section, User
from app.services import project_service as ps
from app.services import section_service as ss


@pytest.fixture
def db():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = {
        name: t for name, t in Base.metadata.tables.items()
        if name != "knowledge_chunks"
    }
    for t in tables.values():
        t.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng)
    session = Session()
    yield session
    session.close()


def _make_user(db, email="u@b.com"):
    u = User(email=email, password_hash=hash_password("Pass1234!"), name="U")
    db.add(u)
    db.commit()
    return u


def _make_project_with_sections(db, user, n=2):
    """直接建一个含 n 个空 section 的项目（绕过模板依赖）。"""
    p = Project(user_id=user.id, title="测试项目")
    db.add(p)
    db.flush()
    for i in range(n):
        db.add(Section(
            project_id=p.id, template_section_id=f"s{i}", order=i,
            key=f"s{i}", title=f"章节{i}",
        ))
    db.commit()
    db.refresh(p)
    return p


def test_section_drafting_sets_project_in_progress(db):
    user = _make_user(db)
    p = _make_project_with_sections(db, user, n=2)
    assert p.status == "draft"  # 初始

    section = db.scalars(
        __import__("sqlalchemy").select(Section).where(Section.project_id == p.id)
    ).first()
    ss.update_section(db, user_id=user.id, section_id=str(section.id), status="drafting")

    db.refresh(p)
    assert p.status == "in_progress"


def test_all_sections_confirmed_sets_project_completed(db):
    user = _make_user(db)
    p = _make_project_with_sections(db, user, n=2)
    sections = list(db.scalars(
        __import__("sqlalchemy").select(Section).where(Section.project_id == p.id)
    )).all()

    for s in sections:
        ss.update_section(db, user_id=user.id, section_id=str(s.id), status="confirmed")

    db.refresh(p)
    assert p.status == "completed"


def test_partial_confirmed_sets_project_in_progress(db):
    user = _make_user(db)
    p = _make_project_with_sections(db, user, n=2)
    sections = list(db.scalars(
        __import__("sqlalchemy").select(Section).where(Section.project_id == p.id)
    )).all()

    # 只确认第一个
    ss.update_section(db, user_id=user.id, section_id=str(sections[0].id), status="confirmed")

    db.refresh(p)
    assert p.status == "in_progress"  # 不是 completed


def test_archived_project_not_overridden_by_section_update(db):
    """归档项目即使 section 变动也不回退 status（归档优先）。"""
    user = _make_user(db)
    p = _make_project_with_sections(db, user, n=1)
    p.status = "archived"
    db.commit()

    section = db.scalars(
        __import__("sqlalchemy").select(Section).where(Section.project_id == p.id)
    ).first()
    ss.update_section(db, user_id=user.id, section_id=str(section.id), status="drafting")

    db.refresh(p)
    assert p.status == "archived"  # 不被覆盖
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_status_flow.py -v`
Expected: FAIL（`assert p.status == "in_progress"` 失败，因为 `update_section` 没有反写 Project.status，status 仍为 `draft`）

- [ ] **Step 3: 实现状态反写逻辑**

在 `apps/api/app/services/section_service.py` 的 `update_section` 函数中，在 `section.version += 1` 之前（即 `db.commit()` 之前），插入状态反写逻辑。找到这段代码：

```python
    section.version += 1  # 乐观锁版本号自增
    db.commit()
    db.refresh(section)
    return section
```

替换为：

```python
    section.version += 1  # 乐观锁版本号自增

    # 反写 Project.status（状态机）：section 流转 → 项目状态联动
    _sync_project_status(db, section)

    db.commit()
    db.refresh(section)
    return section
```

然后在 `section_service.py` 文件末尾追加辅助函数：

```python
def _sync_project_status(db: Session, section: Section) -> None:
    """根据项目所有 section 状态反推 Project.status（设计 P1 状态机）。

    规则（归档优先，不覆盖 archived）：
    - 全部 sections 均 confirmed（≥1）→ completed
    - 任一 drafting/confirmed → in_progress
    - 否则 → draft
    """
    project = db.scalar(select(Project).where(Project.id == section.project_id))
    if project is None or project.status == "archived":
        return  # 归档项目不回退

    sections = list(db.scalars(
        select(Section).where(Section.project_id == project.id)
    ))
    if not sections:
        return

    statuses = [s.status for s in sections]
    if all(s == "confirmed" for s in statuses):
        project.status = "completed"
    elif any(s in ("drafting", "confirmed") for s in statuses):
        project.status = "in_progress"
    else:
        project.status = "draft"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_status_flow.py -v`
Expected: 4 PASS

- [ ] **Step 5: 回归测试——确保现有 section 测试不破**

Run: `cd apps/api && uv run pytest tests/ -v -k "section" --tb=short`
Expected: 全部 PASS（现有 section 测试不涉及 Project.status 断言，不应受影响）

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/services/section_service.py tests/test_status_flow.py
git commit -m "feat(p1): section 状态流转反写 Project.status（修活 in_progress/completed 两态）"
```

---

## Task 2：list_projects 支持查询参数 + 默认排除 archived

**背景：** 当前 `list_projects` 只按 `user_id` 过滤、按 `updated_at` 倒序，不排除 archived，无任何查询参数。需新增 `status`（精确匹配）、`q`（标题模糊）、`tag_id`（按标签筛）参数，且默认不返回 archived 项目（除非显式 `status=archived`）。

**Files:**
- Modify: `apps/api/app/services/project_service.py`
- Modify: `apps/api/app/api/projects.py`
- Test: `apps/api/tests/test_project_query.py`

- [ ] **Step 1: 写失败测试 — 查询参数 + archived 排除**

新建 `apps/api/tests/test_project_query.py`：

```python
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.models import Base, Project, Section, User
from app.services import project_service as ps


@pytest.fixture
def db():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = {
        name: t for name, t in Base.metadata.tables.items()
        if name != "knowledge_chunks"
    }
    for t in tables.values():
        t.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng)
    session = Session()
    yield session
    session.close()


def _make_user(db, email="u@b.com"):
    u = User(email=email, password_hash=hash_password("Pass1234!"), name="U")
    db.add(u)
    db.commit()
    return u


def _make_project(db, user, title, status="draft"):
    p = Project(user_id=user.id, title=title, status=status)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_list_excludes_archived_by_default(db):
    user = _make_user(db)
    _make_project(db, user, "进行中", status="in_progress")
    _make_project(db, user, "已归档", status="archived")

    result = ps.list_projects(db, user=user)
    titles = [p.title for p in result]
    assert "进行中" in titles
    assert "已归档" not in titles  # 默认排除


def test_list_status_filter_archived(db):
    user = _make_user(db)
    _make_project(db, user, "进行中", status="in_progress")
    _make_project(db, user, "已归档", status="archived")

    result = ps.list_projects(db, user=user, status="archived")
    titles = [p.title for p in result]
    assert titles == ["已归档"]


def test_list_status_filter_in_progress(db):
    user = _make_user(db)
    _make_project(db, user, "草稿A", status="draft")
    _make_project(db, user, "进行B", status="in_progress")
    _make_project(db, user, "完成C", status="completed")

    result = ps.list_projects(db, user=user, status="in_progress")
    titles = [p.title for p in result]
    assert titles == ["进行B"]


def test_list_search_by_title(db):
    user = _make_user(db)
    _make_project(db, user, "通信专利改进方案")
    _make_project(db, user, "机械结构设计")
    _make_project(db, user, "通信协议优化")

    result = ps.list_projects(db, user=user, q="通信")
    titles = [p.title for p in result]
    assert set(titles) == {"通信专利改进方案", "通信协议优化"}


def test_list_search_case_insensitive(db):
    user = _make_user(db)
    _make_project(db, user, "AI Patent")
    _make_project(db, user, "Other")

    result = ps.list_projects(db, user=user, q="ai")
    assert len(result) == 1
    assert result[0].title == "AI Patent"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_project_query.py -v`
Expected: FAIL（`TypeError: list_projects() got an unexpected keyword argument 'status'`）

- [ ] **Step 3: 修改 list_projects 签名与查询逻辑**

在 `apps/api/app/services/project_service.py` 中，找到：

```python
def list_projects(db: Session, *, user: User) -> list[Project]:
    return list(db.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.updated_at.desc())
    ))
```

替换为：

```python
def list_projects(
    db: Session, *, user: User,
    status: str | None = None,
    q: str | None = None,
    tag_id: str | None = None,
) -> list[Project]:
    stmt = select(Project).where(Project.user_id == user.id)
    if status is not None:
        stmt = stmt.where(Project.status == status)
    else:
        stmt = stmt.where(Project.status != "archived")  # 默认排除归档
    if q:
        stmt = stmt.where(Project.title.ilike(f"%{q}%"))
    if tag_id:
        from app.models import ProjectTag
        try:
            tid = uuid.UUID(tag_id)
        except ValueError:
            return []
        stmt = stmt.join(ProjectTag, ProjectTag.project_id == Project.id).where(ProjectTag.tag_id == tid)
    stmt = stmt.order_by(Project.updated_at.desc())
    return list(db.scalars(stmt))
```

- [ ] **Step 4: 修改 API 端点透传查询参数**

在 `apps/api/app/api/projects.py` 中，找到：

```python
@router.get("", response_model=list[ProjectOut])
def list_all(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = project_service.list_projects(db, user=current_user)
    return [_to_out(p) for p in projects]
```

替换为：

```python
@router.get("", response_model=list[ProjectOut])
def list_all(
    status: str | None = None,
    q: str | None = None,
    tag_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    projects = project_service.list_projects(
        db, user=current_user, status=status, q=q, tag_id=tag_id,
    )
    return [_to_out(p) for p in projects]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_project_query.py -v`
Expected: 5 PASS

- [ ] **Step 6: 回归——现有 projects 测试可能因 archived 排除逻辑受影响**

Run: `cd apps/api && uv run pytest tests/test_projects.py -v --tb=short`
Expected: 全部 PASS。若有测试因 archived 排除失败（例如某测试先归档再 list），该测试需补 `status="archived"` 参数或确认行为变更合理。

- [ ] **Step 7: 提交**

```bash
cd apps/api && git add app/services/project_service.py app/api/projects.py tests/test_project_query.py
git commit -m "feat(p1): list_projects 支持 status/q/tag_id 查询 + 默认排除 archived"
```

---

## Task 3：Tag + ProjectTag 模型与迁移

**背景：** 用户私有标签系统。`Tag` 是用户私有的标签词表（先建再贴），`ProjectTag` 是项目-标签多对多关联。标签归用户所有，不跨用户可见（为后续共享预留，但本次不做共享）。

**Files:**
- Create: `apps/api/app/models/tag.py`
- Create: `apps/api/app/models/project_tag.py`
- Modify: `apps/api/app/models/__init__.py`
- Create: `apps/api/alembic/versions/<autogen>_add_tags.py`

- [ ] **Step 1: 写 Tag 模型**

新建 `apps/api/app/models/tag.py`：

```python
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Tag(Base, IdMixin, TimestampMixin):
    __tablename__ = "tags"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))
```

- [ ] **Step 2: 写 ProjectTag 关联模型**

新建 `apps/api/app/models/project_tag.py`：

```python
import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


class ProjectTag(Base, IdMixin):
    __tablename__ = "project_tags"
    __table_args__ = (
        UniqueConstraint("project_id", "tag_id", name="uq_project_tag"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True
    )
```

- [ ] **Step 3: 注册模型**

修改 `apps/api/app/models/__init__.py`，在 import 块中（按字母序插入）加两行。找到：

```python
from app.models.project import Project
```

在其**之前**加：

```python
from app.models.project_tag import ProjectTag
```

找到：

```python
from app.models.template import Template
```

在其**之前**加：

```python
from app.models.tag import Tag
```

然后在 `__all__` 列表中加入 `"Tag"` 和 `"ProjectTag"`（放在 `"Project"` 附近）。

- [ ] **Step 4: 生成 Alembic 迁移**

Run: `cd apps/api && uv run alembic revision --autogenerate -m "add tags and project_tags"`
Expected: 生成新迁移文件，内含 `op.create_table('tags', ...)` 和 `op.create_table('project_tags', ...)`。

打开生成的文件，确认：
- `tags` 表含 `id`(Uuid), `user_id`(Uuid, FK→users.id CASCADE), `name`(String(50)), `created_at`, `updated_at`，以及 `ix_tags_user_id` 索引。
- `project_tags` 表含 `id`(Uuid), `project_id`(Uuid, FK→projects.id CASCADE), `tag_id`(Uuid, FK→tags.id CASCADE), `ix_project_tags_project_id`, `ix_project_tags_tag_id`, `uq_project_tag` 唯一约束。
- `down_revision` 应为 `'2f4a6a1e8472'`。

如果 autogenerate 漏了唯一约束，手动在 `op.create_table('project_tags', ...)` 后补：

```python
    op.create_unique_constraint('uq_project_tag', 'project_tags', ['project_id', 'tag_id'])
```

并在 downgrade 里加 `op.drop_constraint('uq_project_tag', 'project_tags')`。

- [ ] **Step 5: 跑迁移确认结构正确**

Run: `cd apps/api && uv run alembic upgrade head`
Expected: 无报错。

Run: `cd apps/api && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: 降级再升级均无报错（验证 downgrade 完整）。

- [ ] **Step 6: 模型可导入测试——确认 Base.metadata 识别新表**

```bash
cd apps/api && uv run python -c "from app.models import Tag, ProjectTag; print(Tag.__tablename__, ProjectTag.__tablename__)"
```
Expected: 输出 `tags project_tags`，无 ImportError。

- [ ] **Step 7: 提交**

```bash
cd apps/api && git add app/models/tag.py app/models/project_tag.py app/models/__init__.py alembic/versions/
git commit -m "feat(p1): 新增 Tag + ProjectTag 模型与迁移（用户私有标签系统）"
```

---

## Task 4：Tag Schema 定义

**Files:**
- Create: `apps/api/app/schemas/tag.py`

- [ ] **Step 1: 写 Schema 文件**

新建 `apps/api/app/schemas/tag.py`：

```python
from datetime import datetime

from pydantic import BaseModel, Field


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class TagMerge(BaseModel):
    """合并：source_id 的所有关联转移到 target_id，然后删除 source_id。"""
    source_id: str
    target_id: str


class TagOut(BaseModel):
    id: str
    name: str
    project_count: int = 0

    model_config = {"from_attributes": True}


class ProjectTagOut(BaseModel):
    """项目视角的标签（贴标签接口返回）。"""
    id: str
    name: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: 可导入验证**

Run: `cd apps/api && uv run python -c "from app.schemas.tag import TagCreate, TagOut; print('ok')"`
Expected: 输出 `ok`。

- [ ] **Step 3: 提交**

```bash
cd apps/api && git add app/schemas/tag.py
git commit -m "feat(p1): 标签 Pydantic schema（Create/Update/Merge/Out）"
```

---

## Task 5：tag_service —— 标签 CRUD + 合并 + 按项目贴/摘

**Files:**
- Create: `apps/api/app/services/tag_service.py`
- Test: `apps/api/tests/test_tags.py`

- [ ] **Step 1: 写失败测试 —— 标签服务层**

新建 `apps/api/tests/test_tags.py`：

```python
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import hash_password
from app.models import Base, Project, User
from app.services import project_service as ps
from app.services import tag_service as ts


@pytest.fixture
def db():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = {
        name: t for name, t in Base.metadata.tables.items()
        if name != "knowledge_chunks"
    }
    for t in tables.values():
        t.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng)
    session = Session()
    yield session
    session.close()


def _make_user(db, email="u@b.com"):
    u = User(email=email, password_hash=hash_password("Pass1234!"), name="U")
    db.add(u)
    db.commit()
    return u


def _make_project(db, user, title="P1"):
    p = Project(user_id=user.id, title=title)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ── CRUD ──

def test_create_tag(db):
    user = _make_user(db)
    tag = ts.create_tag(db, user=user, name="通信")
    assert tag.id is not None
    assert tag.name == "通信"
    assert tag.user_id == user.id


def test_list_tags_returns_only_own(db):
    user_a = _make_user(db, email="a@b.com")
    user_b = _make_user(db, email="b@b.com")
    ts.create_tag(db, user=user_a, name="A的标签")
    ts.create_tag(db, user=user_b, name="B的标签")

    result = ts.list_tags(db, user=user_a)
    assert len(result) == 1
    assert result[0].name == "A的标签"


def test_list_tags_with_project_count(db):
    user = _make_user(db)
    p1 = _make_project(db, user, "P1")
    p2 = _make_project(db, user, "P2")
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p1.id), tag_id=str(tag.id))
    ts.attach_tag(db, user=user, project_id=str(p2.id), tag_id=str(tag.id))

    result = ts.list_tags(db, user=user)
    assert result[0].name == "通信"
    assert result[0].project_count == 2


def test_rename_tag(db):
    user = _make_user(db)
    tag = ts.create_tag(db, user=user, name="通信")
    updated = ts.rename_tag(db, user=user, tag_id=str(tag.id), name="通信领域")
    assert updated.name == "通信领域"


def test_rename_tag_not_owner_returns_404(db):
    user_a = _make_user(db, email="a@b.com")
    user_b = _make_user(db, email="b@b.com")
    tag = ts.create_tag(db, user=user_a, name="A的")
    with pytest.raises(NotFoundError):
        ts.rename_tag(db, user=user_b, tag_id=str(tag.id), name="改了")


def test_delete_tag_cascades_project_tags(db):
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))

    ts.delete_tag(db, user=user, tag_id=str(tag.id))

    # 标签删了，关联也没了
    from app.models import ProjectTag
    from sqlalchemy import select
    links = list(db.scalars(select(ProjectTag).where(ProjectTag.tag_id == tag.id)))
    assert len(links) == 0


def test_delete_tag_not_owner_returns_404(db):
    user_a = _make_user(db, email="a@b.com")
    user_b = _make_user(db, email="b@b.com")
    tag = ts.create_tag(db, user=user_a, name="A的")
    with pytest.raises(NotFoundError):
        ts.delete_tag(db, user=user_b, tag_id=str(tag.id))


# ── 合并 ──

def test_merge_tags_moves_links_and_deletes_source(db):
    user = _make_user(db)
    p1 = _make_project(db, user, "P1")
    p2 = _make_project(db, user, "P2")
    source = ts.create_tag(db, user=user, name="通讯")
    target = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p1.id), tag_id=str(source.id))
    ts.attach_tag(db, user=user, project_id=str(p2.id), tag_id=str(source.id))

    ts.merge_tags(db, user=user, source_id=str(source.id), target_id=str(target.id))

    # source 已删
    from app.models import Tag
    from sqlalchemy import select
    assert db.get(Tag, source.id) is None
    # target 现在有 2 个关联
    target_tags = ts.list_tags_for_project(db, user=user, project_id=str(p1.id))
    assert any(t.name == "通信" for t in target_tags)
    target_tags_p2 = ts.list_tags_for_project(db, user=user, project_id=str(p2.id))
    assert any(t.name == "通信" for t in target_tags_p2)


def test_merge_same_tag_raises_validation_error(db):
    user = _make_user(db)
    tag = ts.create_tag(db, user=user, name="通信")
    with pytest.raises(ValidationError):
        ts.merge_tags(db, user=user, source_id=str(tag.id), target_id=str(tag.id))


# ── 项目贴/摘标签 ──

def test_attach_tag(db):
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))

    tags = ts.list_tags_for_project(db, user=user, project_id=str(p.id))
    assert len(tags) == 1
    assert tags[0].name == "通信"


def test_attach_tag_idempotent(db):
    """同一标签贴两次不报错、不重复。"""
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))  # 幂等

    tags = ts.list_tags_for_project(db, user=user, project_id=str(p.id))
    assert len(tags) == 1


def test_attach_tag_other_users_project_404(db):
    user_a = _make_user(db, email="a@b.com")
    user_b = _make_user(db, email="b@b.com")
    p = _make_project(db, user_a)
    tag = ts.create_tag(db, user=user_b, name="B的标签")
    with pytest.raises(NotFoundError):
        ts.attach_tag(db, user=user_b, project_id=str(p.id), tag_id=str(tag.id))


def test_detach_tag(db):
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    ts.attach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))
    ts.detach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))

    tags = ts.list_tags_for_project(db, user=user, project_id=str(p.id))
    assert len(tags) == 0


def test_detach_not_attached_is_idempotent(db):
    user = _make_user(db)
    p = _make_project(db, user)
    tag = ts.create_tag(db, user=user, name="通信")
    # 不贴直接摘，不报错
    ts.detach_tag(db, user=user, project_id=str(p.id), tag_id=str(tag.id))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_tags.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.tag_service'`）

- [ ] **Step 3: 实现 tag_service**

新建 `apps/api/app/services/tag_service.py`：

```python
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Project, ProjectTag, Tag, User


def _get_tag_owned(db: Session, *, user: User, tag_id: str) -> Tag:
    """获取标签并校验归属（非本人返回 404，防探测）。"""
    try:
        tid = uuid.UUID(tag_id)
    except ValueError:
        raise NotFoundError("标签不存在")
    tag = db.get(Tag, tid)
    if tag is None or tag.user_id != user.id:
        raise NotFoundError("标签不存在")
    return tag


def _get_project_owned(db: Session, *, user: User, project_id: str) -> Project:
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")
    project = db.get(Project, pid)
    if project is None or project.user_id != user.id:
        raise NotFoundError("项目不存在")
    return project


# ── 标签 CRUD ──

def create_tag(db: Session, *, user: User, name: str) -> Tag:
    tag = Tag(user_id=user.id, name=name.strip())
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def list_tags(db: Session, *, user: User) -> list[Tag]:
    """列出用户所有标签，按名称排序。返回的 Tag 对象附带 project_count 属性。"""
    # 子查询统计每个标签关联的项目数
    count_sub = (
        select(ProjectTag.tag_id, func.count(ProjectTag.project_id).label("cnt"))
        .group_by(ProjectTag.tag_id)
        .subquery()
    )
    rows = db.execute(
        select(Tag, func.coalesce(count_sub.c.cnt, 0))
        .outerjoin(count_sub, count_sub.c.cnt != None, Tag.id == count_sub.c.tag_id)
        .where(Tag.user_id == user.id)
        .order_by(Tag.name)
    ).all()
    result = []
    for tag, cnt in rows:
        tag.project_count = cnt  # 动态附加属性
        result.append(tag)
    return result


def rename_tag(db: Session, *, user: User, tag_id: str, name: str) -> Tag:
    tag = _get_tag_owned(db, user=user, tag_id=tag_id)
    tag.name = name.strip()
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, *, user: User, tag_id: str) -> None:
    """删除标签。project_tags 关联因 ON DELETE CASCADE 自动摘除。"""
    tag = _get_tag_owned(db, user=user, tag_id=tag_id)
    db.delete(tag)
    db.commit()


def merge_tags(db: Session, *, user: User, source_id: str, target_id: str) -> Tag:
    """合并标签：source 的所有项目关联转移到 target，然后删除 source。

    幂等处理：source 和 target 都关联了同一项目时，避免唯一约束冲突。
    """
    if source_id == target_id:
        raise ValidationError("不能合并到自身")
    source = _get_tag_owned(db, user=user, tag_id=source_id)
    target = _get_tag_owned(db, user=user, tag_id=target_id)

    # 找出 source 关联的所有项目
    source_links = list(db.scalars(
        select(ProjectTag).where(ProjectTag.tag_id == source.id)
    ))
    target_project_ids = set(db.scalars(
        select(ProjectTag.project_id).where(ProjectTag.tag_id == target.id)
    ))

    for link in source_links:
        if link.project_id not in target_project_ids:
            # 转移：改 tag_id 指向 target
            link.tag_id = target.id
            target_project_ids.add(link.project_id)
        else:
            # target 已有此项目，删掉重复的 source link
            db.delete(link)

    db.delete(source)
    db.commit()
    db.refresh(target)
    return target


# ── 项目-标签关联 ──

def attach_tag(db: Session, *, user: User, project_id: str, tag_id: str) -> ProjectTag:
    """给项目贴标签。幂等：已存在则不重复创建。"""
    project = _get_project_owned(db, user=user, project_id=project_id)
    tag = _get_tag_owned(db, user=user, tag_id=tag_id)

    existing = db.scalar(
        select(ProjectTag).where(
            (ProjectTag.project_id == project.id) & (ProjectTag.tag_id == tag.id)
        )
    )
    if existing is not None:
        return existing  # 幂等

    link = ProjectTag(project_id=project.id, tag_id=tag.id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def detach_tag(db: Session, *, user: User, project_id: str, tag_id: str) -> None:
    """摘除项目标签。幂等：不存在则无操作。"""
    project = _get_project_owned(db, user=user, project_id=project_id)
    try:
        tid = uuid.UUID(tag_id)
    except ValueError:
        return  # 无效 id，幂等无操作

    link = db.scalar(
        select(ProjectTag).where(
            (ProjectTag.project_id == project.id) & (ProjectTag.tag_id == tid)
        )
    )
    if link is not None:
        db.delete(link)
        db.commit()


def list_tags_for_project(db: Session, *, user: User, project_id: str) -> list[Tag]:
    """列出项目上的所有标签。"""
    project = _get_project_owned(db, user=user, project_id=project_id)
    return list(db.scalars(
        select(Tag)
        .join(ProjectTag, ProjectTag.tag_id == Tag.id)
        .where(ProjectTag.project_id == project.id)
        .order_by(Tag.name)
    ))


def list_tag_ids_for_projects(db: Session, *, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """批量查询多个项目的标签 id（用于 list_projects 时填充 tags 字段）。

    返回 {project_id: [tag_id_str, ...]}。
    """
    if not project_ids:
        return {}
    rows = db.execute(
        select(ProjectTag.project_id, ProjectTag.tag_id)
        .where(ProjectTag.project_id.in_(project_ids))
    ).all()
    result: dict[uuid.UUID, list[str]] = {}
    for pid, tid in rows:
        result.setdefault(pid, []).append(str(tid))
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_tags.py -v`
Expected: 16 PASS

> **如果 `list_tags` 的 outerjoin 写法在 SQLite 报错**，改为更简单的两步实现（先查 tags，再单独查 count）：

```python
def list_tags(db: Session, *, user: User) -> list[Tag]:
    tags = list(db.scalars(
        select(Tag).where(Tag.user_id == user.id).order_by(Tag.name)
    ))
    if not tags:
        return tags
    tag_ids = [t.id for t in tags]
    counts = dict(db.execute(
        select(ProjectTag.tag_id, func.count(ProjectTag.project_id))
        .where(ProjectTag.tag_id.in_(tag_ids))
        .group_by(ProjectTag.tag_id)
    ).all())
    for t in tags:
        t.project_count = counts.get(t.id, 0)
    return tags
```

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/services/tag_service.py tests/test_tags.py
git commit -m "feat(p1): tag_service 标签 CRUD + 合并 + 项目贴/摘（含归属校验与幂等）"
```

---

## Task 6：tags API 端点 + ProjectOut 输出 tags

**Files:**
- Create: `apps/api/app/api/tags.py`
- Modify: `apps/api/app/api/router.py`
- Modify: `apps/api/app/schemas/project.py`（ProjectOut 加 tags）
- Modify: `apps/api/app/api/projects.py`（_to_out 填充 tags + 新增项目贴标签端点）
- Test: `apps/api/tests/test_tags.py`（追加 API 层测试）

- [ ] **Step 1: 写失败测试 —— API 层**

在 `apps/api/tests/test_tags.py` 末尾追加：

```python
# ── API 层 ──

def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })


def test_api_list_tags_empty(client, registered_user):
    _login(client, registered_user)
    res = client.get("/api/v1/tags")
    assert res.status_code == 200
    assert res.json() == []


def test_api_create_and_list_tag(client, registered_user):
    _login(client, registered_user)
    res = client.post("/api/v1/tags", json={"name": "通信"})
    assert res.status_code == 201
    assert res.json()["name"] == "通信"

    res = client.get("/api/v1/tags")
    assert len(res.json()) == 1
    assert res.json()[0]["name"] == "通信"
    assert res.json()[0]["project_count"] == 0


def test_api_rename_tag(client, registered_user):
    _login(client, registered_user)
    tag_id = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]
    res = client.patch(f"/api/v1/tags/{tag_id}", json={"name": "通信领域"})
    assert res.status_code == 200
    assert res.json()["name"] == "通信领域"


def test_api_merge_tags(client, registered_user):
    _login(client, registered_user)
    source_id = client.post("/api/v1/tags", json={"name": "通讯"}).json()["id"]
    target_id = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]
    res = client.post("/api/v1/tags/merge", json={"source_id": source_id, "target_id": target_id})
    assert res.status_code == 200

    # source 已删
    tags = client.get("/api/v1/tags").json()
    assert len(tags) == 1
    assert tags[0]["name"] == "通信"


def test_api_delete_tag(client, registered_user):
    _login(client, registered_user)
    tag_id = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]
    res = client.delete(f"/api/v1/tags/{tag_id}")
    assert res.status_code == 204
    assert client.get("/api/v1/tags").json() == []


def test_api_attach_tag_to_project(client, registered_user, db_session):
    _login(client, registered_user)
    # 先建项目和标签
    pid = client.post("/api/v1/projects", json={"title": "P1"}).json()["id"]
    tid = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]

    res = client.post(f"/api/v1/projects/{pid}/tags/{tid}")
    assert res.status_code == 200
    tags = res.json()
    assert len(tags) == 1
    assert tags[0]["name"] == "通信"


def test_api_project_out_includes_tags(client, registered_user, db_session):
    """GET /projects 返回的项目对象含 tags 字段。"""
    _login(client, registered_user)
    pid = client.post("/api/v1/projects", json={"title": "P1"}).json()["id"]
    tid = client.post("/api/v1/tags", json={"name": "通信"}).json()["id"]
    client.post(f"/api/v1/projects/{pid}/tags/{tid}")

    res = client.get("/api/v1/projects")
    assert res.status_code == 200
    projects = res.json()
    assert len(projects) == 1
    assert projects[0]["tags"] == [tid]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_tags.py -v -k "api"`
Expected: FAIL（`404 Not Found`——tags 路由未注册）

- [ ] **Step 3: ProjectOut 加 tags 字段**

修改 `apps/api/app/schemas/project.py`，在 `ProjectOut` 中 `archived_at` 之后、`created_at` 之前加：

```python
    tags: list[str] = []  # 关联的 tag id 列表
```

完整 `ProjectOut` 应为：

```python
class ProjectOut(BaseModel):
    id: str
    title: str
    stage: str
    status: str
    progress_pct: int
    metadata: dict[str, Any] | None = None
    archived_at: datetime | None = None
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: 修改 projects.py 的 _to_out 和 list_all，新增贴标签端点**

修改 `apps/api/app/api/projects.py`。

首先在文件顶部 import 区加 `tag_service`：

找到：
```python
from app.services import archive_service, project_service, skill_service
```
改为：
```python
from app.services import archive_service, project_service, skill_service, tag_service
```

然后修改 `_to_out` 函数，加 `tags` 参数：

找到：
```python
def _to_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=str(p.id), title=p.title, stage=p.stage, status=p.status,
        progress_pct=p.progress_pct, metadata=p.metadata_,
        archived_at=p.archived_at, created_at=p.created_at, updated_at=p.updated_at,
    )
```

替换为：
```python
def _to_out(p: Project, tags: list[str] | None = None) -> ProjectOut:
    return ProjectOut(
        id=str(p.id), title=p.title, stage=p.stage, status=p.status,
        progress_pct=p.progress_pct, metadata=p.metadata_,
        archived_at=p.archived_at,
        tags=tags if tags is not None else getattr(p, "_tag_ids", []),
        created_at=p.created_at, updated_at=p.updated_at,
    )
```

然后修改 `list_all`，批量填充 tags。找到 Task 2 中改过的 `list_all`：

```python
@router.get("", response_model=list[ProjectOut])
def list_all(
    status: str | None = None,
    q: str | None = None,
    tag_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    projects = project_service.list_projects(
        db, user=current_user, status=status, q=q, tag_id=tag_id,
    )
    return [_to_out(p) for p in projects]
```

替换为：
```python
@router.get("", response_model=list[ProjectOut])
def list_all(
    status: str | None = None,
    q: str | None = None,
    tag_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    projects = project_service.list_projects(
        db, user=current_user, status=status, q=q, tag_id=tag_id,
    )
    # 批量填充 tags（避免 N+1）
    from app.services.tag_service import list_tag_ids_for_projects
    tag_map = list_tag_ids_for_projects(db, project_ids=[p.id for p in projects])
    return [_to_out(p, tags=tag_map.get(p.id, [])) for p in projects]
```

同样修改 `get_one` 端点，填 tags：

找到：
```python
@router.get("/{project_id}", response_model=ProjectOut)
def get_one(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.get_project(db, user=current_user, project_id=project_id)
    return _to_out(p)
```

替换为：
```python
@router.get("/{project_id}", response_model=ProjectOut)
def get_one(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.get_project(db, user=current_user, project_id=project_id)
    from app.services.tag_service import list_tags_for_project
    tag_ids = [str(t.id) for t in tag_service.list_tags_for_project(db, user=current_user, project_id=project_id)]
    return _to_out(p, tags=tag_ids)
```

最后，在 `archive` 端点之前（`delete` 端点之后），新增项目贴/摘标签端点：

```python
@router.post("/{project_id}/tags/{tag_id}")
def attach_tag(project_id: str, tag_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tag_service.attach_tag(db, user=current_user, project_id=project_id, tag_id=tag_id)
    tags = tag_service.list_tags_for_project(db, user=current_user, project_id=project_id)
    return [{"id": str(t.id), "name": t.name} for t in tags]


@router.delete("/{project_id}/tags/{tag_id}")
def detach_tag(project_id: str, tag_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tag_service.detach_tag(db, user=current_user, project_id=project_id, tag_id=tag_id)
    tags = tag_service.list_tags_for_project(db, user=current_user, project_id=project_id)
    return [{"id": str(t.id), "name": t.name} for t in tags]
```

- [ ] **Step 5: 写 tags API 路由**

新建 `apps/api/app/api/tags.py`：

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.tag import TagCreate, TagMerge, TagOut, TagUpdate
from app.services import tag_service

router = APIRouter(prefix="/tags", tags=["tags"])


def _to_out(t, project_count: int | None = None) -> TagOut:
    return TagOut(
        id=str(t.id),
        name=t.name,
        project_count=project_count if project_count is not None else getattr(t, "project_count", 0),
    )


@router.get("", response_model=list[TagOut])
def list_all(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tags = tag_service.list_tags(db, user=current_user)
    return [_to_out(t) for t in tags]


@router.post("", response_model=TagOut, status_code=201)
def create(payload: TagCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = tag_service.create_tag(db, user=current_user, name=payload.name)
    return _to_out(t, project_count=0)


@router.patch("/{tag_id}", response_model=TagOut)
def rename(tag_id: str, payload: TagUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = tag_service.rename_tag(db, user=current_user, tag_id=tag_id, name=payload.name)
    return _to_out(t)


@router.post("/merge", response_model=TagOut)
def merge(payload: TagMerge, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = tag_service.merge_tags(
        db, user=current_user, source_id=payload.source_id, target_id=payload.target_id,
    )
    return _to_out(t)


@router.delete("/{tag_id}", status_code=204)
def delete(tag_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tag_service.delete_tag(db, user=current_user, tag_id=tag_id)
    return None
```

- [ ] **Step 6: 注册 tags router**

修改 `apps/api/app/api/router.py`，在 import 块中加入 `tags`：

找到：
```python
from app.api import (
    admin, ai, attachments, auth, export, health, knowledge, projects, review, sections, templates, versions,
)
```
改为：
```python
from app.api import (
    admin, ai, attachments, auth, export, health, knowledge, projects, review, sections, tags, templates, versions,
)
```

然后在 `api_router.include_router(review.router)` 之后加：
```python
api_router.include_router(tags.router)
```

- [ ] **Step 7: 跑全部 tags 测试**

Run: `cd apps/api && uv run pytest tests/test_tags.py -v`
Expected: 全部 PASS（服务层 16 + API 层 7 = 23）

- [ ] **Step 8: 回归——全量后端测试**

Run: `cd apps/api && uv run pytest -v --tb=short`
Expected: 全部 PASS（含原有 ~170 + 新增 ~28）。若有失败多为 `_to_out` 签名变更引起——检查所有调用 `_to_out` 的地方是否兼容（新参数有默认值，应兼容）。

- [ ] **Step 9: 提交**

```bash
cd apps/api && git add app/api/tags.py app/api/router.py app/api/projects.py app/schemas/project.py tests/test_tags.py
git commit -m "feat(p1): tags API 端点 + ProjectOut 输出 tags + 项目贴/摘标签端点"
```

---

## Task 7：前端类型与 API 客户端

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: 扩展类型定义**

修改 `apps/web/src/types/api.ts`。

在 `Project` interface 中，`archived_at` 之后加 `tags`：

找到：
```typescript
  archived_at: string | null
  created_at: string
  updated_at: string
}
```
改为：
```typescript
  archived_at: string | null
  tags: string[]
  created_at: string
  updated_at: string
}
```

然后在文件末尾追加 Tag 相关类型：

```typescript

// ── 标签 ──
export interface Tag {
  id: string
  name: string
  project_count: number
}

export interface TagCreate {
  name: string
}

export interface TagUpdate {
  name: string
}

export interface TagMerge {
  source_id: string
  target_id: string
}

export interface ProjectTag {
  id: string
  name: string
}
```

- [ ] **Step 2: 扩展 api 客户端**

修改 `apps/web/src/lib/api.ts`，在 `deleteProject` 方法之后（项目区块内）追加：

```typescript
  // ── 项目查询参数 ──
  listProjectsFiltered: (params: { status?: string; q?: string; tag_id?: string }) =>
    request<Project[]>(`/projects?${new URLSearchParams(
      Object.entries(params).filter(([, v]) => v).map(([k, v]) => [k, v!])
    ).toString()}`),
```

然后在文件中项目区块之后，新增标签区块（找到 `// ── 用户 ──` 之前插入）：

```typescript
  // ── 标签 ──
  listTags: () => request<Tag[]>('/tags'),

  createTag: (data: TagCreate) =>
    request<Tag>('/tags', { method: 'POST', body: JSON.stringify(data) }),

  renameTag: (id: string, data: TagUpdate) =>
    request<Tag>(`/tags/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteTag: (id: string) =>
    request<void>(`/tags/${id}`, { method: 'DELETE' }),

  mergeTags: (data: TagMerge) =>
    request<Tag>('/tags/merge', { method: 'POST', body: JSON.stringify(data) }),

  attachProjectTag: (projectId: string, tagId: string) =>
    request<ProjectTag[]>(`/projects/${projectId}/tags/${tagId}`, { method: 'POST' }),

  detachProjectTag: (projectId: string, tagId: string) =>
    request<ProjectTag[]>(`/projects/${projectId}/tags/${tagId}`, { method: 'DELETE' }),
```

同时在 api.ts 顶部的 type import 中加入新类型。找到：
```typescript
import type { Project, ProjectCreate, Section, TemplateSummary } from '@/types/api'
```
改为：
```typescript
import type {
  Project, ProjectCreate, ProjectTag, Section, Tag, TagCreate, TagMerge, TagUpdate, TemplateSummary,
} from '@/types/api'
```

- [ ] **Step 3: 扩展 React Query hooks**

修改 `apps/web/src/lib/queries.ts`。

首先在 `queryKeys` 中加 tags：

找到：
```typescript
export const queryKeys = {
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  me: ['me'] as const,
  templates: ['templates'] as const,
  sections: (id: string) => ['sections', id] as const,
  attachments: (projectId: string) => ['attachments', projectId] as const,
  skills: (id: string) => ['skills', id] as const,
}
```
改为：
```typescript
export const queryKeys = {
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  me: ['me'] as const,
  templates: ['templates'] as const,
  sections: (id: string) => ['sections', id] as const,
  attachments: (projectId: string) => ['attachments', projectId] as const,
  skills: (id: string) => ['skills', id] as const,
  tags: ['tags'] as const,
}
```

然后在 `useArchiveProject` 之后（项目区块末尾），加 `useUpdateProject`：

```typescript
export function useUpdateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { title?: string; metadata?: Record<string, unknown> | null } }) =>
      api.updateProject(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}
```

在文件末尾（skills 区块之后）加标签 hooks：

```typescript

// ── 标签 ──
export function useTags() {
  return useQuery<Tag[]>({
    queryKey: queryKeys.tags,
    queryFn: api.listTags,
  })
}

export function useCreateTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TagCreate) => api.createTag(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.tags }),
  })
}

export function useRenameTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.renameTag(id, { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.tags }),
  })
}

export function useDeleteTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteTag(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tags })
      qc.invalidateQueries({ queryKey: queryKeys.projects })  // 项目卡片的标签也要刷新
    },
  })
}

export function useMergeTags() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TagMerge) => api.mergeTags(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tags })
      qc.invalidateQueries({ queryKey: queryKeys.projects })
    },
  })
}

export function useAttachProjectTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, tagId }: { projectId: string; tagId: string }) =>
      api.attachProjectTag(projectId, tagId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}

export function useDetachProjectTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, tagId }: { projectId: string; tagId: string }) =>
      api.detachProjectTag(projectId, tagId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}
```

同时更新 queries.ts 顶部的 import：

找到：
```typescript
import type { Project, ProjectCreate, Section, TemplateSummary } from '@/types/api'
```
改为：
```typescript
import type {
  Project, ProjectCreate, Section, Tag, TagCreate, TagMerge, TemplateSummary,
} from '@/types/api'
```

- [ ] **Step 4: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无类型错误。

- [ ] **Step 5: 提交**

```bash
cd apps/web && git add src/types/api.ts src/lib/api.ts src/lib/queries.ts
git commit -m "feat(p1): 前端类型 + API 客户端 + React Query hooks（标签 + 项目更新）"
```

---

## Task 8：前端 UI 组件——shadcn 组件 + 三个 Dialog

**背景：** 需要安装缺失的 shadcn 组件（tabs、dropdown-menu），并新建重命名/删除确认/项目贴标签三个 Dialog 组件。

**Files:**
- Install: `tabs`, `dropdown-menu` via shadcn
- Create: `apps/web/src/components/rename-dialog.tsx`
- Create: `apps/web/src/components/delete-confirm-dialog.tsx`
- Create: `apps/web/src/components/project-tag-dialog.tsx`

- [ ] **Step 1: 安装缺失的 shadcn 组件**

Run: `cd apps/web && pnpm dlx shadcn@latest add tabs dropdown-menu`
Expected: 在 `src/components/ui/` 下生成 `tabs.tsx` 和 `dropdown-menu.tsx`，自动安装依赖（radix-ui 已在）。

确认：`ls src/components/ui/` 应能看到 `tabs.tsx` 和 `dropdown-menu.tsx`。

- [ ] **Step 2: 写 RenameDialog 组件**

新建 `apps/web/src/components/rename-dialog.tsx`：

```tsx
'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useUpdateProject } from '@/lib/queries'

interface RenameDialogProps {
  projectId: string
  currentTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function RenameDialog({ projectId, currentTitle, open, onOpenChange }: RenameDialogProps) {
  const update = useUpdateProject()
  const [title, setTitle] = useState(currentTitle)

  // 每次打开时同步当前标题
  useEffect(() => {
    if (open) setTitle(currentTitle)
  }, [open, currentTitle])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim() || title.trim() === currentTitle) {
      onOpenChange(false)
      return
    }
    update.mutate(
      { id: projectId, data: { title: title.trim() } },
      {
        onSuccess: () => {
          toast.success('已重命名')
          onOpenChange(false)
        },
        onError: () => toast.error('重命名失败'),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>重命名项目</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="rename-title">项目名称</Label>
            <Input
              id="rename-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={update.isPending || !title.trim()}>
              {update.isPending ? '保存中...' : '保存'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 3: 写 DeleteConfirmDialog 组件**

新建 `apps/web/src/components/delete-confirm-dialog.tsx`：

```tsx
'use client'

import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useDeleteProject } from '@/lib/queries'

interface DeleteConfirmDialogProps {
  projectId: string
  projectTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DeleteConfirmDialog({ projectId, projectTitle, open, onOpenChange }: DeleteConfirmDialogProps) {
  const del = useDeleteProject()

  function handleConfirm() {
    del.mutate(projectId, {
      onSuccess: () => {
        toast.success('已删除')
        onOpenChange(false)
      },
      onError: () => toast.error('删除失败'),
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>确认删除</DialogTitle>
          <DialogDescription>
            确认删除「{projectTitle}」？此操作不可恢复，项目及其所有章节将被永久删除。
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

- [ ] **Step 4: 写 ProjectTagDialog 组件（项目贴标签弹窗）**

新建 `apps/web/src/components/project-tag-dialog.tsx`：

```tsx
'use client'

import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { useAttachProjectTag, useDetachProjectTag, useTags } from '@/lib/queries'

interface ProjectTagDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  attachedTagIds: string[]
}

export function ProjectTagDialog({ projectId, open, onOpenChange, attachedTagIds }: ProjectTagDialogProps) {
  const { data: tags, isLoading } = useTags()
  const attach = useAttachProjectTag()
  const detach = useDetachProjectTag()
  const attachedSet = new Set(attachedTagIds)

  function handleToggle(tagId: string, isAttached: boolean) {
    const mutation = isAttached ? detach : attach
    mutation.mutate(
      { projectId, tagId },
      {
        onError: () => toast.error(isAttached ? '摘除失败' : '贴标签失败'),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>管理标签</DialogTitle>
          <DialogDescription>
            为本项目贴标签。标签可在「标签管理」页创建。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">加载中...</p>
          ) : !tags || tags.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              还没有标签，请先到「标签管理」页创建标签。
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => {
                const isAttached = attachedSet.has(tag.id)
                return (
                  <Badge
                    key={tag.id}
                    variant={isAttached ? 'default' : 'outline'}
                    className="cursor-pointer select-none"
                    onClick={() => handleToggle(tag.id, isAttached)}
                  >
                    {tag.name}
                  </Badge>
                )
              })}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 5: 类型检查 + 构建**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无类型错误。

- [ ] **Step 6: 提交**

```bash
cd apps/web && git add src/components/ui/tabs.tsx src/components/ui/dropdown-menu.tsx src/components/rename-dialog.tsx src/components/delete-confirm-dialog.tsx src/components/project-tag-dialog.tsx
git commit -m "feat(p1): 重命名/删除确认/项目贴标签 Dialog 组件 + shadcn tabs/dropdown-menu"
```

---

## Task 9：改造 project-card —— DropdownMenu 操作 + tags 显示

**背景：** 当前 ProjectCard 的操作按钮是 hover 显示的裸 Button。改为 DropdownMenu（更多操作），含：重命名、贴标签、归档、删除。卡片上显示 tags 徽标。

**Files:**
- Modify: `apps/web/src/components/project-card.tsx`

- [ ] **Step 1: 重写 project-card.tsx**

用以下内容完整替换 `apps/web/src/components/project-card.tsx`：

```tsx
'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { MoreHorizontal, Tag as TagIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { DeleteConfirmDialog } from '@/components/delete-confirm-dialog'
import { ProjectTagDialog } from '@/components/project-tag-dialog'
import { RenameDialog } from '@/components/rename-dialog'
import { useArchiveProject, useTags } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { Project } from '@/types/api'

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  in_progress: '进行中',
  completed: '已完成',
  archived: '已归档',
}

const STATUS_TONE: Record<string, string> = {
  draft: 'bg-muted text-muted-foreground',
  in_progress: 'bg-info/10 text-info',
  completed: 'bg-success/10 text-success',
  archived: 'bg-muted text-muted-foreground',
}

export function ProjectCard({ project }: { project: Project }) {
  const router = useRouter()
  const archive = useArchiveProject()
  const { data: allTags } = useTags()
  const [renameOpen, setRenameOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [tagOpen, setTagOpen] = useState(false)

  // 解析项目上的标签 id → 名称
  const tagMap = new Map((allTags ?? []).map((t) => [t.id, t.name]))
  const projectTags = (project.tags ?? []).map((id) => tagMap.get(id)).filter(Boolean) as string[]

  function handleArchive() {
    archive.mutate(project.id, {
      onSuccess: (res) => toast.success(`已归档到知识库（${res.chunks} 个知识块）`),
      onError: () => toast.error('归档失败'),
    })
  }

  return (
    <>
      <Card
        className="group cursor-pointer transition-colors hover:border-foreground/20"
        onClick={() => router.push(`/projects/${project.id}`)}
      >
        <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
          <CardTitle className="text-[15px] leading-snug">{project.title}</CardTitle>
          <div className="flex items-center gap-1">
            <Badge
              variant="secondary"
              className={cn('shrink-0', STATUS_TONE[project.status])}
            >
              {STATUS_LABEL[project.status] || project.status}
            </Badge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="opacity-0 group-hover:opacity-100"
                  onClick={(e) => e.stopPropagation()}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                <DropdownMenuItem onClick={() => setRenameOpen(true)}>
                  重命名
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTagOpen(true)}>
                  <TagIcon className="mr-2 size-4" />
                  标签
                </DropdownMenuItem>
                {(project.status === 'completed' || project.status === 'archived') && (
                  <DropdownMenuItem onClick={handleArchive} disabled={archive.isPending}>
                    {project.status === 'archived' ? '更新知识库' : '归档'}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={() => setDeleteOpen(true)}
                >
                  删除
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span>{project.stage}</span>
              <span className="tabular-nums">{project.progress_pct}%</span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${project.progress_pct}%` }}
              />
            </div>
          </div>
          {projectTags.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {projectTags.map((name) => (
                <Badge key={name} variant="outline" className="text-[10px] font-normal">
                  {name}
                </Badge>
              ))}
            </div>
          )}
          <div className="flex items-center justify-between pt-1">
            <p className="text-[11px] text-muted-foreground">
              {new Date(project.updated_at).toLocaleDateString('zh-CN')}
            </p>
          </div>
        </CardContent>
      </Card>

      <RenameDialog
        projectId={project.id}
        currentTitle={project.title}
        open={renameOpen}
        onOpenChange={setRenameOpen}
      />
      <ProjectTagDialog
        projectId={project.id}
        open={tagOpen}
        onOpenChange={setTagOpen}
        attachedTagIds={project.tags ?? []}
      />
      <DeleteConfirmDialog
        projectId={project.id}
        projectTitle={project.title}
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
      />
    </>
  )
}
```

- [ ] **Step 2: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无类型错误。

- [ ] **Step 3: 构建验证**

Run: `cd apps/web && pnpm build`
Expected: 构建成功。

- [ ] **Step 4: 提交**

```bash
cd apps/web && git add src/components/project-card.tsx
git commit -m "feat(p1): ProjectCard 改 DropdownMenu 操作 + 标签徽标显示"
```

---

## Task 10：改造 project-list —— 搜索 + 状态 Tabs + 标签筛选

**Files:**
- Modify: `apps/web/src/components/project-list.tsx`

- [ ] **Step 1: 重写 project-list.tsx**

用以下内容完整替换 `apps/web/src/components/project-list.tsx`：

```tsx
'use client'

import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'

import { CreateProjectDialog } from '@/components/create-project-dialog'
import { PageHeader, PageShell } from '@/components/page-shell'
import { ProjectCard } from '@/components/project-card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useProjects, useTags } from '@/lib/queries'
import type { Project } from '@/types/api'

const STATUS_TABS = [
  { value: 'all', label: '全部' },
  { value: 'draft', label: '草稿' },
  { value: 'in_progress', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'archived', label: '已归档' },
]

export function ProjectList() {
  const { data: rawProjects, isLoading, isError } = useProjects()
  const { data: allTags } = useTags()
  const projects: Project[] = rawProjects ?? []

  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [tagFilter, setTagFilter] = useState<string | null>(null)

  // 前端二次筛选（后端已支持参数，但为保持 debounce 简单这里前端筛）
  const filtered = useMemo(() => {
    let result = projects
    if (statusFilter !== 'all') {
      result = result.filter((p) => p.status === statusFilter)
    }
    if (tagFilter) {
      result = result.filter((p) => (p.tags ?? []).includes(tagFilter))
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      result = result.filter((p) => p.title.toLowerCase().includes(q))
    }
    return result
  }, [projects, statusFilter, tagFilter, search])

  const tagMap = new Map((allTags ?? []).map((t) => [t.id, t]))

  return (
    <PageShell>
      <PageHeader title="我的项目" description="管理你的专利交底书">
        <CreateProjectDialog />
      </PageHeader>

      <div className="space-y-4 py-6">
        {/* 搜索框 */}
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索项目标题..."
            className="pl-9"
          />
        </div>

        {/* 状态 Tabs */}
        <Tabs value={statusFilter} onValueChange={setStatusFilter}>
          <TabsList>
            {STATUS_TABS.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        {/* 标签筛选（仅有标签时显示） */}
        {allTags && allTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">标签：</span>
            <Button
              variant={tagFilter === null ? 'secondary' : 'ghost'}
              size="xs"
              onClick={() => setTagFilter(null)}
            >
              全部
            </Button>
            {allTags.map((tag) => (
              <Badge
                key={tag.id}
                variant={tagFilter === tag.id ? 'default' : 'outline'}
                className="cursor-pointer select-none"
                onClick={() => setTagFilter(tagFilter === tag.id ? null : tag.id)}
              >
                {tag.name}
              </Badge>
            ))}
          </div>
        )}

        {/* 项目网格 */}
        {isLoading ? (
          <p className="text-sm text-muted-foreground">加载中...</p>
        ) : isError ? (
          <p className="text-sm text-destructive">加载失败，请重试</p>
        ) : filtered.length === 0 ? (
          <div className="rounded-lg border border-dashed p-12 text-center text-sm text-muted-foreground">
            {projects.length === 0
              ? '还没有项目，点击右上角「新建项目」开始你的第一份交底书'
              : '没有符合条件的项目'}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
```

- [ ] **Step 2: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无类型错误。

- [ ] **Step 3: 构建验证**

Run: `cd apps/web && pnpm build`
Expected: 构建成功。

- [ ] **Step 4: 提交**

```bash
cd apps/web && git add src/components/project-list.tsx
git commit -m "feat(p1): 工作台搜索框 + 状态 Tabs + 标签筛选"
```

---

## Task 11：标签管理页

**背景：** 独立的 `/tags` 页面，用于查看所有标签、创建、重命名、合并、删除。

**Files:**
- Create: `apps/web/src/app/(app)/tags/page.tsx`
- Create: `apps/web/src/components/tag-editor.tsx`

- [ ] **Step 1: 写 TagEditor 组件**

新建 `apps/web/src/components/tag-editor.tsx`：

```tsx
'use client'

import { useState } from 'react'
import { Merge, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  useCreateTag, useDeleteTag, useMergeTags, useRenameTag, useTags,
} from '@/lib/queries'

export function TagEditor() {
  const { data: tags, isLoading } = useTags()
  const create = useCreateTag()
  const rename = useRenameTag()
  const del = useDeleteTag()
  const merge = useMergeTags()

  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [mergeOpen, setMergeOpen] = useState(false)
  const [mergeSource, setMergeSource] = useState('')
  const [mergeTarget, setMergeTarget] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string; count: number } | null>(null)

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    create.mutate(
      { name: newName.trim() },
      {
        onSuccess: () => { toast.success('标签已创建'); setNewName('') },
        onError: () => toast.error('创建失败'),
      },
    )
  }

  function handleRename(id: string) {
    if (!editingName.trim()) return
    rename.mutate(
      { id, name: editingName.trim() },
      {
        onSuccess: () => { toast.success('已重命名'); setEditingId(null) },
        onError: () => toast.error('重命名失败'),
      },
    )
  }

  function handleMerge(e: React.FormEvent) {
    e.preventDefault()
    if (!mergeSource || !mergeTarget || mergeSource === mergeTarget) {
      toast.error('请选择两个不同的标签')
      return
    }
    merge.mutate(
      { source_id: mergeSource, target_id: mergeTarget },
      {
        onSuccess: () => { toast.success('已合并'); setMergeOpen(false); setMergeSource(''); setMergeTarget('') },
        onError: () => toast.error('合并失败'),
      },
    )
  }

  function handleDelete() {
    if (!deleteTarget) return
    del.mutate(deleteTarget.id, {
      onSuccess: () => { toast.success('已删除'); setDeleteTarget(null) },
      onError: () => toast.error('删除失败'),
    })
  }

  return (
    <div className="space-y-6">
      {/* 创建新标签 */}
      <form onSubmit={handleCreate} className="flex max-w-md gap-2">
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="新标签名称"
        />
        <Button type="submit" disabled={create.isPending || !newName.trim()}>
          创建
        </Button>
      </form>

      {/* 标签列表 */}
      {isLoading ? (
        <p className="text-sm text-muted-foreground">加载中...</p>
      ) : !tags || tags.length === 0 ? (
        <p className="text-sm text-muted-foreground">还没有标签。</p>
      ) : (
        <div className="space-y-2">
          {tags.map((tag) => (
            <div
              key={tag.id}
              className="flex items-center justify-between rounded-md border px-3 py-2"
            >
              {editingId === tag.id ? (
                <div className="flex flex-1 items-center gap-2">
                  <Input
                    value={editingName}
                    onChange={(e) => setEditingName(e.target.value)}
                    className="h-7 max-w-[200px]"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleRename(tag.id)
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                  />
                  <Button size="xs" onClick={() => handleRename(tag.id)} disabled={rename.isPending}>
                    保存
                  </Button>
                  <Button size="xs" variant="ghost" onClick={() => setEditingId(null)}>
                    取消
                  </Button>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{tag.name}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {tag.project_count} 个项目
                    </span>
                  </div>
                  <div className="flex gap-1">
                    <Button
                      size="xs" variant="ghost"
                      onClick={() => { setEditingId(tag.id); setEditingName(tag.name) }}
                    >
                      重命名
                    </Button>
                    <Button
                      size="xs" variant="ghost" className="text-destructive"
                      onClick={() => setDeleteTarget({ id: tag.id, name: tag.name, count: tag.project_count })}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 合并按钮（需 ≥2 个标签） */}
      {tags && tags.length >= 2 && (
        <Button variant="outline" onClick={() => setMergeOpen(true)}>
          <Merge className="mr-2 size-4" />
          合并标签
        </Button>
      )}

      {/* 合并弹窗 */}
      <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>合并标签</DialogTitle>
            <DialogDescription>
              将源标签的所有项目关联转移到目标标签，然后删除源标签。此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleMerge} className="space-y-4">
            <div className="space-y-2">
              <Label>源标签（将被删除）</Label>
              <select
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                value={mergeSource}
                onChange={(e) => setMergeSource(e.target.value)}
              >
                <option value="">选择...</option>
                {tags?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
            <div className="space-y-2">
              <Label>目标标签（保留）</Label>
              <select
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                value={mergeTarget}
                onChange={(e) => setMergeTarget(e.target.value)}
              >
                <option value="">选择...</option>
                {tags?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={merge.isPending || !mergeSource || !mergeTarget}>
                {merge.isPending ? '合并中...' : '确认合并'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 删除确认弹窗 */}
      <Dialog open={!!deleteTarget} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除标签</DialogTitle>
            <DialogDescription>
              确认删除标签「{deleteTarget?.name}」？
              {deleteTarget && deleteTarget.count > 0 && (
                <>它将从 {deleteTarget.count} 个项目上摘除（项目本身不受影响）。</>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={del.isPending}>
              {del.isPending ? '删除中...' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
```

- [ ] **Step 2: 写标签管理页**

新建 `apps/web/src/app/(app)/tags/page.tsx`：

```tsx
import { TagEditor } from '@/components/tag-editor'
import { PageHeader, PageShell } from '@/components/page-shell'

export default function TagsPage() {
  return (
    <PageShell>
      <PageHeader title="标签管理" description="管理你的项目标签词表" />
      <div className="py-6">
        <TagEditor />
      </div>
    </PageShell>
  )
}
```

- [ ] **Step 3: 类型检查 + 构建**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm build`
Expected: 无错误。

- [ ] **Step 4: 提交**

```bash
cd apps/web && git add src/app/\(app\)/tags/page.tsx src/components/tag-editor.tsx
git commit -m "feat(p1): 标签管理页（创建/重命名/合并/删除）"
```

---

## Task 12：Navbar 加标签管理入口

**Files:**
- Modify: `apps/web/src/components/navbar.tsx`

- [ ] **Step 1: 在 NAV_ITEMS 中加入标签管理**

读取 `apps/web/src/components/navbar.tsx`，找到 `NAV_ITEMS` 数组（约 31-36 行）。当前内容形如：

```typescript
const NAV_ITEMS = [
  { href: '/dashboard', label: '工作台' },
  { href: '/templates', label: '模板' },
  { href: '/admin', label: '管理', adminOnly: true },
  { href: '/settings', label: '设置' },
]
```

在 `/templates` 之后加标签管理项：

```typescript
const NAV_ITEMS = [
  { href: '/dashboard', label: '工作台' },
  { href: '/templates', label: '模板' },
  { href: '/tags', label: '标签' },
  { href: '/admin', label: '管理', adminOnly: true },
  { href: '/settings', label: '设置' },
]
```

> **注意：** 先 Read 文件确认 `NAV_ITEMS` 的确切结构（字段名可能不同），照原结构加一项。

- [ ] **Step 2: 构建验证**

Run: `cd apps/web && pnpm build`
Expected: 构建成功，导航栏出现「标签」入口。

- [ ] **Step 3: 提交**

```bash
cd apps/web && git add src/components/navbar.tsx
git commit -m "feat(p1): Navbar 加标签管理入口"
```

---

## Task 13：端到端验收

**目标：** 全量测试 + 构建 + 手动验证清单，确认整个 P1 改造闭环。

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest -v --tb=short`
Expected: 全部 PASS（原有 ~170 + 新增约 28 = ~198）

- [ ] **Step 2: 前端构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功，无类型错误。

- [ ] **Step 3: 手动验证清单（前后端均启动）**

启动后端：`cd apps/api && uv run uvicorn app.main:app --reload`
启动前端：`cd apps/web && pnpm dev`

打开 `http://localhost:3000`，登录后逐项验证：

**状态流转：**
- [ ] 新建项目 → 工作台显示「草稿」徽标
- [ ] 进入项目，让 AI 生成一个章节草稿 → 回工作台，项目变「进行中」
- [ ] 确认所有章节 → 回工作台，项目变「已完成」
- [ ] 归档项目 → 工作台默认列表不显示它；切到「已归档」Tab 能看到

**搜索：**
- [ ] 搜索框输入标题关键词 → 列表实时过滤
- [ ] 清空搜索 → 恢复全部

**状态 Tabs：**
- [ ] 点击「草稿」「进行中」「已完成」「已归档」→ 分别只显示对应状态项目
- [ ] 「全部」→ 显示除已归档外的所有项目

**标签：**
- [ ] 导航栏有「标签」入口
- [ ] 标签管理页创建标签「通信」→ 列表显示
- [ ] 重命名「通信」→「通信领域」→ 列表更新
- [ ] 回工作台，项目卡片 DropdownMenu → 标签 → 贴上「通信领域」→ 卡片显示标签徽标
- [ ] 标签筛选条点「通信领域」→ 只显示贴了该标签的项目
- [ ] 标签管理页合并两个标签 → 源标签删除，项目关联转移

**删除确认：**
- [ ] 项目卡片 DropdownMenu → 删除 → 弹出确认弹窗（不是浏览器原生 confirm）
- [ ] 取消 → 不删；确认删除 → 项目消失

- [ ] **Step 4: 全量提交（如有未提交的改动）**

```bash
git status  # 确认工作区干净
```

- [ ] **Step 5: 更新 AGENTS.md（可选）**

在 `AGENTS.md` 的项目简介中，将"当前阶段"更新为"P1 项目管理改造完成"，或追加说明本次新增的能力（状态流转、搜索、标签）。

---

## Self-Review

### Spec 覆盖核对

| grilling 锁定的需求 | 对应 Task | 状态 |
|---|---|---|
| 状态流转修复（B 方案：section 反写 Project.status） | Task 1 | ✅ |
| list_projects 默认排除 archived | Task 2 | ✅ |
| list_projects 支持 status 查询参数 | Task 2 | ✅ |
| 标题搜索（后端 ilike + 前端过滤） | Task 2（后端）+ Task 10（前端） | ✅ |
| 标签系统：先建再贴 | Task 3-6（后端）+ Task 8-11（前端） | ✅ |
| 标签管理页：查看/创建/重命名/合并/删除 | Task 11 | ✅ |
| 删除二次确认（替换原生 confirm） | Task 8 DeleteConfirmDialog + Task 9 接线 | ✅ |
| ProjectCard 加重命名入口 | Task 9 DropdownMenu | ✅ |
| 标签按用户私有 | Task 3 模型（user_id FK）+ Task 5 归属校验 | ✅ |

### 未在范围（正确排除）

- ❌ 共享/权限/代理人 —— 不碰
- ❌ 全文搜索 —— 只搜标题
- ❌ 邀请注册/邮件服务 —— 不做

### 类型一致性核对

- `tag_service.create_tag(db, *, user, name)` → API `POST /tags` ✅
- `tag_service.list_tags` 返回带 `project_count` 动态属性 → `TagOut.project_count` ✅
- `_to_out(p, tags=...)` 签名 → `list_all` / `get_one` 调用一致 ✅
- 前端 `Project.tags: string[]` ← 后端 `ProjectOut.tags: list[str]` ✅
- `useAttachProjectTag` / `useDetachProjectTag` 调用签名 `{ projectId, tagId }` ← api 方法签名一致 ✅

### 已知风险点

1. **Task 5 的 `list_tags` outerjoin 写法**：在 SQLite 测试库上可能行为异常，已提供 fallback 两步实现。
2. **Task 6 的 `get_one` 端点**：N+1 查询（单项目查标签），但单项目场景可接受。
3. **`project_count` 动态属性**：直接挂在 ORM 对象上，不是声明的 mapped_column。`_to_out` 用 `getattr(t, "project_count", 0)` 兜底，安全。
4. **前端筛选是客户端做的**（`project-list.tsx` 的 `useMemo`），没有调后端查询参数。这是因为 `useProjects()` 一次拉全量、30 个项目客户端过滤足够快。后端参数（Task 2）已就绪，将来项目量大时可无缝切到服务端筛选。
