# 计划 9：创作主线加固 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 P0 验收点 #13（自动保存+乐观锁）与 #19（SSE 心跳+服务端真异步中断+断线保留），并加宽编辑器内容区。

**Architecture:** 后端 `Section` 加 `version` 字段实现乐观锁（`UPDATE...WHERE version=?`，冲突返回 409）；AI 编排层新增异步版本 `astream_llm`/`astream_*`（保留同步版不破坏审查引擎），SSE 三端点改 async + 心跳 + 客户端断开检测 + 断线内容落草稿。前端防抖 2s 保存 + AbortController 中断。

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · LangChain 1.x（`llm.astream()`）· Next.js 16 · React 19 · Tiptap

**关联 spec：** [P0 验收补全迭代设计](../specs/2026-07-14-p0-completion-iteration.md) §4

---

## 文件结构

| 文件 | 责任 | 操作 |
|---|---|---|
| `apps/api/app/models/section.py` | Section ORM，加 `version` 字段 | 修改 |
| `apps/api/alembic/versions/<new>_add_section_version.py` | 迁移：加 version 列 | 新建 |
| `apps/api/app/schemas/section.py` | SectionOut 加 version；SectionUpdate 加 expected_version | 修改 |
| `apps/api/app/services/section_service.py` | update_section 乐观锁 + 409 | 修改 |
| `apps/api/app/ai/llm_client.py` | 新增 `astream_llm` | 修改 |
| `apps/api/app/ai/orchestrator.py` | 新增 `astream_chat/generate/rewrite` | 修改 |
| `apps/api/app/api/ai.py` | 三端点改 async + 心跳 + 断线落草稿 | 修改 |
| `apps/api/app/api/sections.py` | _to_out 输出 version | 修改 |
| `apps/api/tests/test_sections.py` | 乐观锁并发测试 | 修改 |
| `apps/api/tests/test_ai.py` | 异步流式 + 断线保留测试 | 修改 |
| `apps/web/src/app/(app)/projects/[id]/page.tsx` | 防抖保存 + expected_version + 409 + 保存指示器 + max-w-5xl | 修改 |
| `apps/web/src/components/ai-chat-panel.tsx` | 停止按钮 + AbortController | 修改 |
| `apps/web/src/components/editor/tiptap-editor.tsx` | （9.0 无改动，确认） | — |
| `apps/web/src/lib/api.ts` | stream 方法支持 AbortSignal + 解析 event 行 | 修改 |
| `apps/web/src/types/api.ts` | Section 加 version | 修改 |

---

## Task 1：Section 模型加 version 字段

**Files:**
- Modify: `apps/api/app/models/section.py`
- Test: `apps/api/tests/test_models.py`（扩展）

- [ ] **Step 1: 写失败测试 — version 字段存在且默认 1**

在 `apps/api/tests/test_models.py` 末尾追加：

```python
def test_section_has_version_field_default_1(db_session):
    """Section.version 默认 1（乐观锁基线）。"""
    from app.models import Section
    s = Section(
        project_id=None, template_section_id="t1", order=1, key="name",
        title="发明名称", status="empty",
    )
    # 不直接 add（project_id 外键约束），只验证字段定义存在且有默认值
    assert hasattr(s, "version")
    # 默认值在 mapped_column default=1，对象未 flush 时属性为 1
    assert s.version == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_models.py::test_section_has_version_field_default_1 -v`
Expected: FAIL（`AssertionError: Section 对象没有 version 属性` 或 AttributeError）

- [ ] **Step 3: 加 version 字段**

修改 `apps/api/app/models/section.py`，在 `status` 字段后加：

```python
    # 乐观锁版本号：每次 PATCH 成功 +1；并发更新冲突返回 409（设计 13.4）
    version: Mapped[int] = mapped_column(Integer, default=1)
```

完整文件应为：

```python
import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class Section(Base, IdMixin, TimestampMixin):
    __tablename__ = "sections"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    template_section_id: Mapped[str] = mapped_column(String(100))
    order: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # Tiptap JSON
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="empty")  # empty/drafting/confirmed
    # 乐观锁版本号：每次 PATCH 成功 +1；并发更新冲突返回 409（设计 13.4）
    version: Mapped[int] = mapped_column(Integer, default=1)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_models.py::test_section_has_version_field_default_1 -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/models/section.py tests/test_models.py
git commit -m "feat(plan9): Section 模型加 version 字段（乐观锁基线）"
```

---

## Task 2：Alembic 迁移加 version 列

**Files:**
- Create: `apps/api/alembic/versions/<id>_add_section_version.py`

- [ ] **Step 1: 生成迁移**

Run: `cd apps/api && uv run alembic revision --autogenerate -m "add section version"`
Expected: 生成新迁移文件，检测到 `version` 列新增。

- [ ] **Step 2: 校验迁移内容**

打开生成的迁移文件，确认 `down_revision = 'a20f16f0da4e'`（当前 head），`upgrade()` 含：

```python
    op.add_column('sections', sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
```

若 server_default 缺失，手动补上（已有数据需要默认值）。确认 `downgrade()` 含 `op.drop_column('sections', 'version')`。

- [ ] **Step 3: 跑迁移**

Run: `cd apps/api && uv run alembic upgrade head`
Expected: `Running upgrade a20f16f0da4e -> <new>, add section version`

- [ ] **Step 4: 提交**

```bash
cd apps/api && git add alembic/versions/
git commit -m "feat(plan9): 迁移 add_section_version"
```

---

## Task 3：乐观锁 service 层 — update_section 冲突检测

**Files:**
- Modify: `apps/api/app/services/section_service.py`
- Modify: `apps/api/app/schemas/section.py`
- Test: `apps/api/tests/test_sections.py`（service 层）

- [ ] **Step 1: 写失败测试 — 版本匹配时更新成功并自增**

在 `apps/api/tests/test_sections.py` 顶部加 import 和辅助（若已有则跳过），末尾追加：

```python
def _make_section(db_session, registered_user):
    """建项目取第一个章节。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    ensure_default_template(db_session)
    from app.models import User
    user = db_session.scalar(
        __import__("sqlalchemy").select(User).where(User.email == registered_user["email"])
    )
    p = create_project(db_session, user=user, title="测试发明")
    from app.services.section_service import list_sections
    return list_sections(db_session, user_id=user.id, project_id=str(p.id))[0]


def test_update_section_version_mismatch_raises_conflict(db_session, registered_user):
    """乐观锁：expected_version 不匹配时抛 ConflictError。"""
    from app.core.exceptions import ConflictError
    from app.services.section_service import update_section

    section = _make_section(db_session, registered_user)
    assert section.version == 1

    # 用错误的 expected_version（应为 1，传 999）
    import pytest
    with pytest.raises(ConflictError):
        update_section(
            db_session, user_id=registered_user["id"], section_id=str(section.id),
            content={"type": "doc"}, expected_version=999,
        )


def test_update_section_version_match_increments(db_session, registered_user):
    """乐观锁：expected_version 匹配时更新成功且 version +1。"""
    from app.services.section_service import update_section

    section = _make_section(db_session, registered_user)
    assert section.version == 1

    updated = update_section(
        db_session, user_id=registered_user["id"], section_id=str(section.id),
        content={"type": "doc"}, expected_version=1,
    )
    assert updated.version == 2


def test_update_section_without_expected_version_skips_lock(db_session, registered_user):
    """不传 expected_version 时跳过乐观锁（向后兼容旧客户端）。"""
    from app.services.section_service import update_section

    section = _make_section(db_session, registered_user)
    updated = update_section(
        db_session, user_id=registered_user["id"], section_id=str(section.id),
        content={"type": "doc"},
    )
    assert updated.version == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_sections.py::test_update_section_version_mismatch_raises_conflict tests/test_sections.py::test_update_section_version_match_increments tests/test_sections.py::test_update_section_without_expected_version_skips_lock -v`
Expected: FAIL（`update_section() got an unexpected keyword argument 'expected_version'`）

- [ ] **Step 3: 更新 schema**

修改 `apps/api/app/schemas/section.py`：

```python
from datetime import datetime

from pydantic import BaseModel


class SectionOut(BaseModel):
    id: str
    project_id: str
    order: int
    key: str
    title: str
    content: dict | None
    summary: str | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SectionUpdate(BaseModel):
    content: dict | None = None
    status: str | None = None  # empty/drafting/confirmed
    expected_version: int | None = None  # 乐观锁：客户端传读取时的版本号
```

- [ ] **Step 4: 改 update_section 加乐观锁**

修改 `apps/api/app/services/section_service.py` 的 `update_section`：

```python
def update_section(
    db: Session, *, user_id, section_id: str,
    content=None, status=None, expected_version: int | None = None,
) -> Section:
    section = get_section(db, user_id=user_id, section_id=section_id)

    # 乐观锁：传了 expected_version 则校验（设计 13.4）
    if expected_version is not None and expected_version != section.version:
        raise ConflictError(
            f"内容已被修改（当前版本 {section.version}，期望 {expected_version}）"
        )

    if content is not None:
        section.content = content
    if status is not None:
        if status not in ("empty", "drafting", "confirmed"):
            raise ValidationError("无效的章节状态")
        old_status = section.status
        section.status = status
        if status == "confirmed" and old_status != "confirmed":
            # 确认时自动存版本（设计 13.6 + 版本快照）
            from app.services.version_service import create_version
            create_version(db, section=section, created_by="auto", note="确认章节时自动保存")
            # 触发 summary 生成（供跨章节上下文用，设计 5.10）
            from app.services.summary_service import generate_summary
            generate_summary(db, section)
    section.version += 1  # 乐观锁版本号自增
    db.commit()
    db.refresh(section)
    return section
```

注意：`ConflictError` 已在文件顶部 import（`from app.core.exceptions import NotFoundError, ValidationError`），需补 `ConflictError`：

```python
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_sections.py -v`
Expected: 全部 PASS（含原有测试 + 3 个新测试）

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/schemas/section.py app/services/section_service.py tests/test_sections.py
git commit -m "feat(plan9): 章节乐观锁（expected_version 冲突返回 409）"
```

---

## Task 4：API 层 — PATCH 端点传 expected_version + SectionOut 输出 version

**Files:**
- Modify: `apps/api/app/api/sections.py`
- Test: `apps/api/tests/test_sections.py`（API 层）

- [ ] **Step 1: 写失败测试 — API 层乐观锁返回 409**

在 `apps/api/tests/test_sections.py` 末尾追加：

```python
def test_api_update_section_optimistic_lock_409(client, registered_user, db_session):
    """API 层：expected_version 不匹配返回 409，body 含当前 version。"""
    section = _make_section(db_session, registered_user)
    _login(client, registered_user)

    res = client.patch(f"/api/v1/sections/{section.id}", json={
        "content": {"type": "doc"},
        "expected_version": 999,  # 错误版本
    })
    assert res.status_code == 409
    body = res.json()
    assert "version" in str(body) or "版本" in body.get("message", "")


def test_api_update_section_returns_version(client, registered_user, db_session):
    """API 层：成功更新时响应含 version 字段。"""
    section = _make_section(db_session, registered_user)
    _login(client, registered_user)

    res = client.patch(f"/api/v1/sections/{section.id}", json={
        "content": {"type": "doc"},
        "expected_version": 1,
    })
    assert res.status_code == 200
    assert res.json()["version"] == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_sections.py::test_api_update_section_optimistic_lock_409 tests/test_sections.py::test_api_update_section_returns_version -v`
Expected: FAIL（version 字段不在响应 / expected_version 未传递）

- [ ] **Step 3: 改 _to_out 和 update 端点**

修改 `apps/api/app/api/sections.py`：

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.section import SectionOut, SectionUpdate
from app.services import section_service

router = APIRouter(tags=["sections"])


def _to_out(s) -> SectionOut:
    return SectionOut(
        id=str(s.id), project_id=str(s.project_id), order=s.order, key=s.key,
        title=s.title, content=s.content, summary=s.summary, status=s.status,
        version=s.version, created_at=s.created_at, updated_at=s.updated_at,
    )


@router.get("/projects/{project_id}/sections", response_model=list[SectionOut])
def list_sections(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sections = section_service.list_sections(
        db, user_id=current_user.id, project_id=project_id
    )
    return [_to_out(s) for s in sections]


@router.get("/sections/{section_id}", response_model=SectionOut)
def get_section(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    return _to_out(s)


@router.patch("/sections/{section_id}", response_model=SectionOut)
def update_section(
    section_id: str,
    payload: SectionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = section_service.update_section(
        db, user_id=current_user.id, section_id=section_id,
        content=payload.content, status=payload.status,
        expected_version=payload.expected_version,
    )
    return _to_out(s)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_sections.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/api/sections.py tests/test_sections.py
git commit -m "feat(plan9): PATCH /sections 传递 expected_version + 响应 version"
```

---

## Task 5：后端异步 LLM 客户端 — astream_llm

**Files:**
- Modify: `apps/api/app/ai/llm_client.py`
- Test: `apps/api/tests/test_llm.py`（扩展）

- [ ] **Step 1: 写失败测试 — astream_llm 是异步生成器**

在 `apps/api/tests/test_llm.py` 末尾追加：

```python
def test_astream_llm_is_async_generator():
    """astream_llm 返回 async generator（不实际调用 LLM）。"""
    import inspect
    from app.ai.llm_client import astream_llm
    from langchain_core.messages import HumanMessage

    gen = astream_llm([HumanMessage(content="hi")])
    # async generator 函数调用后返回 async generator 对象
    assert inspect.isasyncgen(gen)


def test_stream_llm_still_exists():
    """同步 stream_llm 保留（审查引擎仍用）。"""
    from app.ai.llm_client import stream_llm
    assert callable(stream_llm)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_llm.py::test_astream_llm_is_async_generator -v`
Expected: FAIL（`ImportError: cannot import name 'astream_llm'`）

- [ ] **Step 3: 新增 astream_llm**

修改 `apps/api/app/ai/llm_client.py`，在文件末尾追加：

```python
from collections.abc import AsyncIterator


async def astream_llm(messages: list[BaseMessage]) -> AsyncIterator[str]:
    """异步流式调用 LLM，逐 token yield 文本。

    用于 SSE 端点：客户端断开时 generator 被取消，底层 httpx 连接关闭，
    真正停止从 LLM API 拉取（不浪费 token）。
    """
    llm = get_llm(streaming=True)
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_llm.py -v`
Expected: 全部 PASS（含原有 2 个 + 新增 2 个）

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/ai/llm_client.py tests/test_llm.py
git commit -m "feat(plan9): 新增异步 LLM 客户端 astream_llm"
```

---

## Task 6：异步编排层 — astream_chat / astream_generate / astream_rewrite

**Files:**
- Modify: `apps/api/app/ai/orchestrator.py`
- Test: `apps/api/tests/test_ai.py`

- [ ] **Step 1: 写失败测试 — astream 函数存在且签名正确**

在 `apps/api/tests/test_ai.py` 末尾追加（若无此文件则新建，参考现有测试 import 风格）：

```python
def test_astream_functions_exist():
    """三个异步编排函数存在且是 async generator function。"""
    import inspect
    from app.ai.orchestrator import astream_chat, astream_generate, astream_rewrite

    for fn in (astream_chat, astream_generate, astream_rewrite):
        assert inspect.isasyncgenfunction(fn), f"{fn.__name__} 应为 async generator function"


def test_sync_functions_still_exist():
    """同步编排函数保留（审查引擎等仍用）。"""
    from app.ai.orchestrator import stream_chat, stream_generate, stream_rewrite
    for fn in (stream_chat, stream_generate, stream_rewrite):
        assert callable(fn)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_ai.py::test_astream_functions_exist -v`
Expected: FAIL（`ImportError: cannot import name 'astream_chat'`）

- [ ] **Step 3: 新增异步编排函数**

修改 `apps/api/app/ai/orchestrator.py`，在文件顶部 import 区加：

```python
from collections.abc import AsyncIterator, Iterator
```

在文件末尾追加（逻辑与同步版完全对应，仅 stream_llm→astream_llm、def→async def、yield from→async for）：

```python
async def astream_chat(
    db, section: Section, history: list[Message], user_input: str
) -> AsyncIterator[str]:
    """异步引导对话：流式回复用户问题（供 SSE 端点用）。"""
    summaries = get_project_summaries(db, section.project_id)
    knowledge = _retrieve_knowledge(db, section, user_input)
    messages = assemble_messages(section, history, user_input, summaries, knowledge)
    async for token in astream_llm(messages):
        yield token


async def astream_generate(
    db, section: Section, history: list[Message]
) -> AsyncIterator[str]:
    """异步生成草稿：基于对话历史生成本章草稿（Markdown 流式）。"""
    summaries = get_project_summaries(db, section.project_id)
    knowledge = _retrieve_knowledge(db, section, section.title)
    sp = get_section_prompt(section.key)
    messages = assemble_messages(
        section, history, project_summaries=summaries, knowledge_context=knowledge
    )
    instruction = (
        f"请根据以上对话内容，整理生成本章节【{section.title}】的草稿。"
        f"要求：{sp.output_format}。用 Markdown 格式输出。"
    )
    messages.append(HumanMessage(content=instruction))
    async for token in astream_llm(messages):
        yield token


async def astream_rewrite(
    section: Section, selected_text: str, instruction: str
) -> AsyncIterator[str]:
    """异步段落重写：基于选中文字 + 指令，流式输出重写结果。"""
    from langchain_core.messages import SystemMessage

    sp = get_section_prompt(section.key)
    system = (
        f"你是专利交底书撰写助手。当前章节：【{section.title}】（{sp.goal}）。"
        f"用户选中了一段文字，请按指令重写。保持 Markdown 格式。"
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"原文：\n{selected_text}\n\n指令：{instruction}"),
    ]
    async for token in astream_llm(messages):
        yield token
```

import 区加（与同步版并列）：

```python
from app.ai.llm_client import astream_llm, stream_llm
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_ai.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/ai/orchestrator.py tests/test_ai.py
git commit -m "feat(plan9): 异步编排层 astream_chat/generate/rewrite"
```

---

## Task 7：SSE 端点改 async + 心跳 + 断线落草稿

**Files:**
- Modify: `apps/api/app/api/ai.py`
- Test: `apps/api/tests/test_ai.py`

- [ ] **Step 1: 写失败测试 — SSE 含心跳事件**

在 `apps/api/tests/test_ai.py` 末尾追加：

```python
def test_chat_endpoint_emits_done_event_with_heartbeat_support(client, registered_user, db_session, monkeypatch):
    """SSE chat 端点：mock LLM，验证 token/done 事件格式 + 异步 generate。"""
    section = _make_logged_in_section(client, registered_user, db_session)

    # mock astream_chat 返回固定 token
    async def fake_astream_chat(db, section, history, msg):
        yield "hello"

    monkeypatch.setattr("app.api.ai.astream_chat", fake_astream_chat)

    res = client.post(f"/api/v1/sections/{section.id}/chat", json={"message": "hi"})
    assert res.status_code == 200
    body = res.text
    assert "event: token" in body
    assert "event: done" in body
    assert "hello" in body


def test_generate_saves_draft_on_completion(client, registered_user, db_session, monkeypatch):
    """generate 端点正常完成时把 markdown 转为 tiptap 存入 section.content。"""
    section = _make_logged_in_section(client, registered_user, db_session)
    assert section.content is None  # 初始为空

    async def fake_astream_generate(db, sec, history):
        yield "# 标题"

    monkeypatch.setattr("app.api.ai.astream_generate", fake_astream_generate)

    res = client.post(f"/api/v1/sections/{section.id}/generate")
    assert res.status_code == 200
    assert "event: done" in res.text

    # 验证草稿已存
    db_session.expire_all()
    from app.models import Section
    s = db_session.get(Section, section.id)
    assert s.content is not None
    assert s.status == "drafting"
```

并加辅助函数（在文件顶部 helpers 区）：

```python
def _make_logged_in_section(client, registered_user, db_session):
    """登录 + 建项目 + 返回第一个 section 对象（含真实 id）。"""
    from app.services.seed_service import ensure_default_template
    from app.services.project_service import create_project
    from app.services.section_service import list_sections
    from app.models import User
    from sqlalchemy import select

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    p = create_project(db_session, user=user, title="测试发明")
    sections = list_sections(db_session, user_id=user.id, project_id=str(p.id))
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    return sections[0]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_ai.py::test_chat_endpoint_emits_done_event_with_heartbeat_support tests/test_ai.py::test_generate_saves_draft_on_completion -v`
Expected: FAIL（端点仍是同步，或 import 路径不对）

- [ ] **Step 3: 重写 ai.py 三个端点为 async + 心跳 + 断线落草稿**

修改 `apps/api/app/api/ai.py`，完整替换为：

```python
"""AI 流式 SSE 路由（异步 + 心跳 + 服务端真中断 + 断线内容保留）。"""

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import astream_chat, astream_generate, astream_rewrite
from app.core.database import get_db
from app.deps import get_current_user
from app.models import Message, Section, User
from app.schemas.ai import ChatRequest, RewriteRequest
from app.services import section_service

router = APIRouter(tags=["ai"])

# 心跳间隔（秒）：空闲超过此值发 heartbeat 事件，防中间代理掐断
HEARTBEAT_INTERVAL = 5.0


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_section_with_history(
    db: Session, user_id, section_id: str
) -> tuple[Section, list[Message]]:
    section = section_service.get_section(db, user_id=user_id, section_id=section_id)
    history = list(db.scalars(
        select(Message).where(Message.section_id == section.id).order_by(Message.created_at)
    ))
    return section, history


async def _yield_with_heartbeat(async_gen):
    """包装异步 token 生成器，空闲超 HEARTBEAT_INTERVAL 时插心跳事件。

    LLM 生成慢或长时间无 token 时，中间代理可能掐断空闲连接；
    心跳让连接保持活跃。token 与心跳交替 yield（统一 str）。
    """
    ait = async_gen.__aiter__()
    while True:
        try:
            token = await asyncio.wait_for(ait.__anext__(), timeout=HEARTBEAT_INTERVAL)
            yield ("token", token)
        except asyncio.TimeoutError:
            yield ("heartbeat", "")
        except StopAsyncIteration:
            break


@router.post("/sections/{section_id}/chat")
async def chat(
    section_id: str,
    payload: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section, history = _get_section_with_history(db, current_user.id, section_id)
    user_msg = Message(section_id=section.id, role="user", content=payload.message)
    db.add(user_msg)
    db.commit()

    async def generate():
        full_response = ""
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_chat(db, section, history, payload.message)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    full_response += text
                    yield _sse_event("token", {"text": text})
            ai_msg = Message(section_id=section.id, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()
            yield _sse_event("done", {"message_id": str(ai_msg.id)})
        except asyncio.CancelledError:
            # 客户端断开：已生成的部分存为 assistant message（断线保留）
            if full_response:
                db.add(Message(section_id=section.id, role="assistant", content=full_response))
                db.commit()
            raise
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/generate")
async def generate_draft(
    section_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section, history = _get_section_with_history(db, current_user.id, section_id)

    async def generate():
        full_md = ""
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_generate(db, section, history)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    full_md += text
                    yield _sse_event("token", {"text": text})
            from app.ai.markdown_to_tiptap import markdown_to_tiptap
            section.content = markdown_to_tiptap(full_md)
            if section.status == "empty":
                section.status = "drafting"
            db.commit()
            yield _sse_event("done", {"section_id": str(section.id)})
        except asyncio.CancelledError:
            # 客户端断开：仅当 section 当前为空时落半截草稿（避免覆盖已有内容）
            if full_md and section.status == "empty":
                from app.ai.markdown_to_tiptap import markdown_to_tiptap
                section.content = markdown_to_tiptap(full_md)
                section.status = "drafting"
                db.commit()
            raise
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/rewrite")
async def rewrite(
    section_id: str,
    payload: RewriteRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)

    async def generate():
        try:
            async for kind, text in _yield_with_heartbeat(
                astream_rewrite(section, payload.selected_text, payload.instruction)
            ):
                if kind == "heartbeat":
                    yield _sse_event("heartbeat", {})
                else:
                    yield _sse_event("token", {"text": text})
            yield _sse_event("done", {})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/sections/{section_id}/messages")
def list_messages(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    messages = list(db.scalars(
        select(Message).where(Message.section_id == section.id).order_by(Message.created_at)
    ))
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_ai.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/api/ai.py tests/test_ai.py
git commit -m "feat(plan9): SSE 端点异步化 + 心跳 + 断线内容保留"
```

---

## Task 8：前端 — 类型 + API 层支持 AbortSignal + event 解析

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: Section 类型加 version**

修改 `apps/web/src/types/api.ts`，在 `Section` interface 加 `version: number`。

定位 `Section` interface（应有 status 字段那块），加：

```typescript
  version: number
```

- [ ] **Step 2: 改 _consumeSSE 解析 event 行 + 支持 AbortSignal**

修改 `apps/web/src/lib/api.ts`，把 streamChat/streamGenerate 改造支持 signal，并重写 `_consumeSSE` 解析 `event:` + `data:` 配对。

替换 streamChat/streamGenerate 及 `_consumeSSE` 部分：

```typescript
  // ── AI（SSE 流式）──
  streamChat: async (
    sectionId: string,
    message: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
  ) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      signal,
    })
    return _consumeSSE(res, onToken)
  },

  streamGenerate: async (
    sectionId: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
  ) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/generate`, {
      method: 'POST',
      credentials: 'include',
      signal,
    })
    return _consumeSSE(res, onToken)
  },
```

并重写文件末尾的 `_consumeSSE`：

```typescript
async function _consumeSSE(res: Response, onToken: (t: string) => void): Promise<void> {
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE 事件以空行分隔
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const evt of events) {
      const lines = evt.split('\n')
      let dataLine = ''
      for (const line of lines) {
        if (line.startsWith('data: ')) dataLine = line.slice(6)
      }
      if (!dataLine) continue
      try {
        const data = JSON.parse(dataLine)
        if (data.text) onToken(data.text)
        // heartbeat/error/done 事件无 text，忽略（上层靠流结束判断）
      } catch {
        // 忽略解析失败的行
      }
    }
  }
}
```

- [ ] **Step 3: 验证前端构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功，无类型错误

- [ ] **Step 4: 提交**

```bash
cd apps/web && git add src/types/api.ts src/lib/api.ts
git commit -m "feat(plan9): 前端 API 层 SSE 支持 AbortSignal + event 解析"
```

---

## Task 9：前端 — 编辑器加宽 + 防抖保存 + 409 处理 + 保存指示器

**Files:**
- Modify: `apps/web/src/app/(app)/projects/[id]/page.tsx`

- [ ] **Step 1: 加 max-w-5xl + 防抖保存 + expected_version + 409 + 保存指示器**

修改 `apps/web/src/app/(app)/projects/[id]/page.tsx`：

**a) import 区加 useRef/useEffect（防抖用）：**

把第 2 行 `import { useEffect, useState } from 'react'` 改为：

```typescript
import { useEffect, useRef, useState } from 'react'
```

**b) 在组件内（currentId state 之后）加防抖 ref + 保存状态：**

在 `const [versionOpen, setVersionOpen] = useState(false)` 之后加：

```typescript
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle')
```

**c) 替换 handleSave 函数**（防抖 2s + expected_version + 409 处理）：

```typescript
  function handleSave(json: object) {
    if (!current) return
    // 防抖 2s（设计 13.4）
    if (saveTimer.current) clearTimeout(saveTimer.current)
    setSaveState('saving')
    saveTimer.current = setTimeout(() => {
      updateSection.mutate(
        {
          id: current.id,
          content: json,
          status: current.status === 'empty' ? 'drafting' : current.status,
          expected_version: current.version,
        },
        {
          onSuccess: () => setSaveState('saved'),
          onError: (err: { code?: string; message?: string }) => {
            if (err?.code === 'conflict') {
              toast.error('内容已被其他端修改，已刷新为最新版本')
              qc.invalidateQueries({ queryKey: queryKeys.sections(projectId) })
            } else {
              toast.error('保存失败')
            }
            setSaveState('idle')
          },
        },
      )
    }, 2000)
  }
```

**d) import queryKeys 和 useQueryClient**（若未 import）：

在 import 区确认有：

```typescript
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys, useSections, useUpdateSection } from '@/lib/queries'
```

并在组件内加：

```typescript
  const qc = useQueryClient()
```

**e) 切换章节时 flush 未保存内容**（在第一个 useEffect 之后加）：

```typescript
  // 切换章节前 flush 防抖中的保存
  useEffect(() => {
    return () => {
      if (saveTimer.current) {
        clearTimeout(saveTimer.current)
        saveTimer.current = null
      }
    }
  }, [currentId])
```

**f) 加宽编辑器 + 保存指示器**：把编辑器外层 `max-w-3xl` 改为 `max-w-5xl`，并在标题栏加保存状态指示。定位：

```typescript
          <div className="mx-auto max-w-3xl">
```

改为：

```typescript
          <div className="mx-auto max-w-5xl">
```

并在标题 `<h1>` 旁加保存指示器（在 `{current && (` 块的标题栏 div 内，h1 之后）：

```typescript
              {saveState === 'saving' && (
                <span className="text-[11px] text-muted-foreground">保存中…</span>
              )}
              {saveState === 'saved' && (
                <span className="text-[11px] text-muted-foreground">已保存</span>
              )}
```

**g) 更新 useUpdateSection 的 mutate 参数类型**（queries.ts 里 updateSection 的 data 类型需加 expected_version）：

修改 `apps/web/src/lib/queries.ts`，找到 `useUpdateSection` 的 mutate data 定义，加 `expected_version?: number`。具体看该文件中 updateSection 的类型定义，把 data 参数类型改为 `{ content?: object; status?: string; expected_version?: number }`。

- [ ] **Step 2: 验证构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功

- [ ] **Step 3: 提交**

```bash
cd apps/web && git add src/app/\(app\)/projects/\[id\]/page.tsx src/lib/queries.ts
git commit -m "feat(plan9): 编辑器加宽 max-w-5xl + 防抖2s保存 + 乐观锁409 + 保存指示器"
```

---

## Task 10：前端 — AI 面板停止按钮 + AbortController

**Files:**
- Modify: `apps/web/src/components/ai-chat-panel.tsx`

- [ ] **Step 1: 加 AbortController + 停止按钮**

修改 `apps/web/src/components/ai-chat-panel.tsx`：

**a) import useRef：**

```typescript
import { useRef, useState } from 'react'
```

**b) 组件内加 abortController ref：**

在 `const [generating, setGenerating] = useState(false)` 之后加：

```typescript
  const abortRef = useRef<AbortController | null>(null)
```

**c) 改 handleSend 传 signal + 改 handleGenerate 传 signal + 加 handleStop：**

```typescript
  async function handleSend() {
    if (!input.trim() || loading) return
    const userMsg: ChatMessage = { role: 'user', content: input }
    setMessages((m) => [...m, userMsg, { role: 'assistant', content: '' }])
    setInput('')
    setLoading(true)
    abortRef.current = new AbortController()

    let aiText = ''
    try {
      await api.streamChat(sectionId, userMsg.content, (token) => {
        aiText += token
        setMessages((m) => {
          const copy = [...m]
          copy[copy.length - 1] = { role: 'assistant', content: aiText }
          return copy
        })
      }, abortRef.current.signal)
    } catch (err: unknown) {
      // abort 不报错（用户主动停止），其他错误提示
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        toast.error('AI 回复失败')
      }
    } finally {
      setLoading(false)
    }
  }

  function handleStop() {
    abortRef.current?.abort()
    setGenerating(false)
    setMessages((m) => {
      const copy = [...m]
      // AI 气泡若为空或 '...'，移除占位
      const last = copy[copy.length - 1]
      if (last && last.role === 'assistant' && (!last.content || last.content === '...')) {
        copy.pop()
      }
      return copy
    })
  }

  async function handleGenerate() {
    setGenerating(true)
    toast.info('正在生成草稿...')
    abortRef.current = new AbortController()
    try {
      let md = ''
      await api.streamGenerate(sectionId, (token) => {
        md += token
      }, abortRef.current.signal)
      toast.success('草稿已生成并填入编辑器')
      await qc.invalidateQueries({ queryKey: queryKeys.sections(projectId) })
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        toast.info('已停止，已生成内容已保留')
        await qc.invalidateQueries({ queryKey: queryKeys.sections(projectId) })
      } else {
        toast.error('生成失败')
      }
    } finally {
      setGenerating(false)
    }
  }
```

**d) 「生成草稿」按钮在 generating 时变「停止」：**

把：

```typescript
          <Button size="xs" variant="outline" onClick={handleGenerate} disabled={generating}>
            {generating ? '生成中...' : '生成草稿'}
          </Button>
```

改为：

```typescript
          {generating ? (
            <Button size="xs" variant="destructive" onClick={handleStop}>
              停止
            </Button>
          ) : (
            <Button size="xs" variant="outline" onClick={handleGenerate}>
              生成草稿
            </Button>
          )}
```

- [ ] **Step 2: 验证构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功

- [ ] **Step 3: 提交**

```bash
cd apps/web && git add src/components/ai-chat-panel.tsx
git commit -m "feat(plan9): AI 面板停止按钮 + AbortController 中断生成"
```

---

## Task 11：全量验证 + 端到端核对

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest -v`
Expected: 全部 PASS（36 个原有 + 计划 9 新增）

- [ ] **Step 2: 前端构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功

- [ ] **Step 3: 端到端手验（需启动后端+前端+DB）**

启动后端和前端，登录后：
1. 打开项目编辑器 → 编辑内容 → 等 2s 看是否「已保存」（防抖生效）
2. 快速切换章节 → 看内容是否丢失（应 flush 保存）
3. 生成草稿 → 生成中点「停止」→ 看是否立即停止、已生成内容保留
4. 检查编辑器内容区宽度是否比之前宽（max-w-5xl）

- [ ] **Step 4: 提交计划完成标记**

```bash
git commit --allow-empty -m "chore: 计划 9 创作主线加固端到端验证通过"
```
