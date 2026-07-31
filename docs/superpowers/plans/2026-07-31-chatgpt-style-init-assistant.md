# ChatGPT 式项目初始化助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把项目初始化助手从「列表页弹窗」重做为 `/new` 独立全屏 ChatGPT 式两栏页（左对话列表 + 右主对话区），对话在项目创建前进行（顶层 init 会话），agent 判断时机 + 用户按扳机创建项目并跳转。

**Architecture:** 复用 Conversation/Message 表，`section_id` 改可空 + 加 `kind`/`project_id`/`user_id` 区分顶层 init 会话与项目内会话。后端新增 `/assistant/*` 端点，agent 用 `[READY_TO_CREATE]` 标记创建时机。前端新建 `/new` 两栏路由页，监听标记渲染扳机，落地后跳项目页。删除旧的弹窗形态与首轮建项目链路。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic · Next.js + shadcn/ui · SSE 流式 · react-query

**Spec reference:** `docs/superpowers/specs/2026-07-31-chatgpt-style-init-assistant-design.md`

---

## 文件结构

**后端（apps/api）**
- Modify: `app/models/conversation.py` — section_id 可空 + 加 kind/project_id/user_id
- Modify: `app/models/message.py` — section_id 可空
- Create: `alembic/versions/b7c8d9e0f1a2_assistant_conversations.py` — 迁移 + backfill
- Modify: `app/ai/init_orchestrator.py` — INIT_SYSTEM_PROMPT 加标记规则 + generate 签名改造（内部建项目）
- Create: `app/api/assistant.py` — 顶层 init 会话 CRUD + chat/generate 端点
- Modify: `app/api/router.py` — 注册 assistant.router，删 init_assistant
- Delete: `app/api/init_assistant.py` — 旧弹窗后端端点
- Modify: `app/api/projects.py` — 删 create_from_chat 端点（L34-64）
- Delete: `tests/test_init_assistant.py` — 旧测试
- Create: `tests/test_assistant.py` — 新测试

**前端（apps/web）**
- Create: `src/app/(app)/new/page.tsx` — 路由页
- Create: `src/components/assistant/init-assistant.tsx` — 两栏主体
- Create: `src/components/assistant/assistant-conversation-list.tsx` — 左侧列表
- Modify: `src/lib/api.ts` — 加 assistant 方法，删旧 init 方法
- Modify: `src/lib/queries.ts` — 加 assistant hooks + queryKeys
- Modify: `src/components/project-list.tsx` — 入口改跳 /new
- Delete: `src/components/init-assistant-dialog.tsx` — 旧弹窗组件

---

## Task 1: 数据模型 — Conversation 加字段 + section_id 可空

**Files:**
- Modify: `apps/api/app/models/conversation.py`

- [ ] **Step 1: 改 Conversation 模型**

把 `apps/api/app/models/conversation.py` 的 `Conversation` 类改成（section_id 可空 + 加三字段）：

```python
class Conversation(Base, IdMixin, TimestampMixin):
    """AI 对话会话。

    两类：
    - kind='project'：项目内对话，挂 section_id（兼容旧逻辑）。
    - kind='init'：项目初始化对话（顶层会话），section_id=NULL，user_id 记归属；
      project_id 在落地成项目后填上（落地后从助手列表消失）。
    """
    __tablename__ = "conversations"

    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    status: Mapped[str] = mapped_column(
        String(20), default=ConversationStatus.draft.value, index=True
    )
    # 会话类型：project（项目内）/ init（初始化助手顶层会话）
    kind: Mapped[str] = mapped_column(String(20), default="project")
    # init 会话落地成项目后记下（落地后列表 WHERE project_id IS NULL 不再命中）
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 顶层 init 会话归属（init 会话无 section 可反查，必须直接记 user_id）
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
```

注意：`user_id` 设为 nullable=True 是为兼容老数据 backfill 前的过渡（迁移里 backfill 后理论上全非空，但为安全留 nullable；新 init 会话写入时必填）。

- [ ] **Step 2: 加常量**

在 `ConversationStatus` enum 之后、`Conversation` 类之前加：

```python
# 会话类型
KIND_PROJECT = "project"
KIND_INIT = "init"
```

- [ ] **Step 3: 更新 models/__init__.py 导出**

确认 `apps/api/app/models/__init__.py` 已导出 `Conversation, ConversationStatus`（L6 附近）；补导出 `KIND_PROJECT, KIND_INIT`（加到 import 行 + `__all__`）。

- [ ] **Step 4: 冒烟测试 — 导入成功**

Run: `cd apps/api && uv run python -c "from app.models import Conversation, KIND_INIT, KIND_PROJECT; print(Conversation.__table__.columns.keys())"`
Expected: 输出含 `kind`, `project_id`, `user_id`, `section_id`

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/models/conversation.py apps/api/app/models/__init__.py
git commit -m "feat(model): Conversation 加 kind/project_id/user_id + section_id 可空"
```

---

## Task 2: 数据模型 — Message.section_id 可空

**Files:**
- Modify: `apps/api/app/models/message.py`

- [ ] **Step 1: 改 Message 模型**

把 `apps/api/app/models/message.py` 的 `section_id` 改可空：

```python
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), nullable=True, index=True
    )
```

`conversation_id` 保持 NOT NULL 不变（消息必须属于某会话）。

- [ ] **Step 2: 冒烟测试**

Run: `cd apps/api && uv run python -c "from app.models import Message; print(Message.__table__.columns.section_id.nullable)"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/models/message.py
git commit -m "feat(model): Message.section_id 可空（支持顶层 init 会话消息）"
```

---

## Task 3: Alembic 迁移 — conversations/messages schema + backfill

**Files:**
- Create: `apps/api/alembic/versions/b7c8d9e0f1a2_assistant_conversations.py`

- [ ] **Step 1: 写迁移文件**

`down_revision = 'a55afec3993e'`（当前 head）。注意 conversations 原用 `sa.dialects.postgresql.UUID`，messages 用 `sa.Uuid()`，保持各方言一致。

```python
"""assistant conversations: kind/project_id/user_id + section_id nullable

Revision ID: b7c8d9e0f1a2
Revises: a55afec3993e
Create Date: 2026-07-31

顶层 init 会话：Conversation.section_id 改可空（init 会话不挂 section），
加 kind（project/init）、project_id（落地标记）、user_id（归属）。
Message.section_id 同改可空。老数据 backfill kind='project' + user_id。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'a55afec3993e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # conversations: 加列 + section_id 改 nullable
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=20), nullable=False, server_default='project'))
        batch_op.add_column(sa.Column('project_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
        batch_op.add_column(sa.Column('user_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
        batch_op.alter_column('section_id', existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=True)
    op.create_index('ix_conversations_kind', 'conversations', ['kind'])
    op.create_index('ix_conversations_project_id', 'conversations', ['project_id'])
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])
    op.create_foreign_key('fk_conversations_project_id', 'conversations', 'projects', ['project_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_conversations_user_id', 'conversations', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    # messages: section_id 改 nullable
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('section_id', existing_type=sa.Uuid(), nullable=True)

    # backfill user_id：老会话由 section_id → project → user 反查
    op.execute(
        "UPDATE conversations c SET user_id = p.user_id "
        "FROM sections s, projects p "
        "WHERE c.section_id = s.id AND s.project_id = p.id AND c.user_id IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint('fk_conversations_user_id', 'conversations', type_='foreignkey')
    op.drop_constraint('fk_conversations_project_id', 'conversations', type_='foreignkey')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_index('ix_conversations_project_id', table_name='conversations')
    op.drop_index('ix_conversations_kind', table_name='conversations')
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('section_id', existing_type=sa.Uuid(), nullable=False)
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.alter_column('section_id', existing_type=sa.dialects.postgresql.UUID(as_uuid=True), nullable=False)
        batch_op.drop_column('user_id')
        batch_op.drop_column('project_id')
        batch_op.drop_column('kind')
```

- [ ] **Step 2: 验证迁移可执行（生产 PG）**

Run: `cd apps/api && uv run alembic upgrade head`
Expected: 输出 `Running upgrade a55afec3993e -> b7c8d9e0f1a2, assistant conversations...`，无报错。

- [ ] **Step 3: 验证可回滚**

Run: `cd apps/api && uv run alembic downgrade -1` 然后 `uv run alembic upgrade head`
Expected: 来回都成功。

- [ ] **Step 4: 跑全量后端测试确认无回归**

Run: `cd apps/api && uv run pytest tests/ -q`
Expected: 全 PASS（conftest 用 Base.metadata 建表，模型改了自动生效；既有 8 个 test_init_assistant 此时仍跑旧端点，还没删，应仍 PASS）。

- [ ] **Step 5: Commit**

```bash
git add apps/api/alembic/versions/b7c8d9e0f1a2_assistant_conversations.py
git commit -m "feat(migration): 顶层 init 会话 schema + backfill user_id"
```

---

## Task 4: 后端编排 — INIT_SYSTEM_PROMPT 加 [READY_TO_CREATE] 标记规则

**Files:**
- Modify: `apps/api/app/ai/init_orchestrator.py`（L30-49 的 INIT_SYSTEM_PROMPT）

- [ ] **Step 1: 在 INIT_SYSTEM_PROMPT 规则区追加标记规则**

在 `apps/api/app/ai/init_orchestrator.py` 的 `INIT_SYSTEM_PROMPT`（L30-49）的规则列表末尾（"5. 回复简洁..." 之后）追加：

```python
6. 当你判断已经收集到足够信息（技术领域、要解决的问题、技术方案的大致轮廓、关键特征都基本清楚），
   在回复的【最末尾】单独输出一行标记 `[READY_TO_CREATE]`（必须是这个精确字符串，独占一行）。
   前端会据此提示用户「可以创建项目了」。没收集够时不要输出这个标记。
   输出标记前照常把当轮该说的话说完（如总结你理解的需求、确认要点），标记只追加在最末尾。
```

- [ ] **Step 2: 冒烟测试**

Run: `cd apps/api && uv run python -c "from app.ai.init_orchestrator import INIT_SYSTEM_PROMPT; print('[READY_TO_CREATE]' in INIT_SYSTEM_PROMPT)"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/ai/init_orchestrator.py
git commit -m "feat(ai): INIT_SYSTEM_PROMPT 加 [READY_TO_CREATE] 时机标记规则"
```

---

## Task 5: 后端编排 — astream_init_generate 改造（接 conversation，内部建项目）

**Files:**
- Modify: `apps/api/app/ai/init_orchestrator.py`（L97-160 的 astream_init_generate）

当前签名 `astream_init_generate(db, project, history, ...)`，要改为接收 `conversation` + `user`，在内部建项目。保留 `astream_init_chat` / `_build_init_chat_messages` / `_build_section_generate_messages` 不变（generate 内部建好项目后仍用 `_build_section_generate_messages`）。

- [ ] **Step 1: 改 astream_init_generate 签名与建项目逻辑**

把 `astream_init_generate`（L97-160）整体替换为：

```python
async def astream_init_generate(
    db, conversation, history: list[Message], user,
    *, llm_config: ResolvedChatConfig,
    sections: list[str] | None = None,
    usage_sink: dict | None = None,
) -> AsyncIterator[tuple[str, dict | str]]:
    """扳机落地：为 init 会话建项目 + 填充各章节初稿，流式产出进度与 token。

    接收顶层 init 会话（conversation）+ 用户（user），内部：
    1. create_project 建项目 + 8 空章节
    2. 把 conversation.project_id 填上（标记已落地）
    3. 对项目 sections 循环生成初稿（复用 _build_section_generate_messages + astream_llm）
    4. 回写 section.content + status: empty→drafting

    yield 元组：
      - ("chapter_start", {"index", "total", "title", "key"})
      - ("token", str)
      - ("chapter_done", {"index", "title", "key", "status", "error"})
      - ("project_created", {"project_id": str})  # 项目建好后即发，前端可提前拿 id
      - ("all_done", {"project_id": str})
    """
    from sqlalchemy import select

    from app.ai.markdown_to_tiptap import markdown_to_tiptap
    from app.models import Section
    from app.services.project_service import create_project

    # 1. 建项目 + 8 空章节（标题从对话首条用户消息提炼，或用会话标题）
    title = (conversation.title or "新项目").strip() or "新项目"
    project = create_project(db, user=user, title=title[:60])

    # 2. 标记会话已落地（project_id 填上 → 列表不再显示）
    conversation.project_id = project.id
    db.commit()

    yield ("project_created", {"project_id": str(project.id)})

    # 3. 循环生成各章节初稿
    stmt = select(Section).where(Section.project_id == project.id)
    if sections:
        stmt = stmt.where(Section.key.in_(sections))
    section_list = list(db.scalars(stmt.order_by(Section.order)))
    total = len(section_list)

    for idx, section in enumerate(section_list, start=1):
        yield ("chapter_start", {
            "index": idx, "total": total,
            "title": section.title, "key": section.key,
        })
        full_md = ""
        chapter_error = None
        try:
            messages = _build_section_generate_messages(section, history)
            async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage_sink):
                full_md += token
                yield ("token", token)
            section.content = markdown_to_tiptap(full_md)
            if section.status == "empty":
                section.status = "drafting"
            db.commit()
        except Exception as e:  # noqa: BLE001 — 单章失败不中断整体
            chapter_error = str(e)
            db.rollback()
            db.refresh(section)
        finally:
            yield ("chapter_done", {
                "index": idx, "title": section.title, "key": section.key,
                "status": "failed" if chapter_error else "ok",
                "error": chapter_error,
            })

    yield ("all_done", {"project_id": str(project.id)})
```

- [ ] **Step 2: 清理未使用的 import**

`init_orchestrator.py` L22 的 `from app.ai.section_prompts import get_section_prompt` 是死 import（未使用），删除该行。

- [ ] **Step 2b: 加 Project 类型 import（如 docstring/类型需要）**

文件顶部 import 区已有 `from app.models import Message, Project, Section`（L10）。新增的 `astream_init_generate` 用了 `conversation`（无类型注解）和 `user`（无类型注解），无需额外 import。确认 `Message` 已在 import 内即可。

- [ ] **Step 3: 冒烟测试 — 函数签名正确**

Run: `cd apps/api && uv run python -c "import inspect; from app.ai.init_orchestrator import astream_init_generate; print(list(inspect.signature(astream_init_generate).parameters))"`
Expected: `['db', 'conversation', 'history', 'user', 'llm_config', 'sections', 'usage_sink']`

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/ai/init_orchestrator.py
git commit -m "refactor(ai): astream_init_generate 接 conversation + 内部建项目"
```

---

## Task 6: 后端 API — assistant.py 顶层会话 CRUD

**Files:**
- Create: `apps/api/app/api/assistant.py`

- [ ] **Step 1: 写 assistant.py — CRUD 端点**

```python
"""项目初始化助手路由（/assistant/conversations/*）—— ChatGPT 式独立对话页后端。

顶层 init 会话（kind='init'，项目无关）：列表/创建/取历史/删除。
chat/generate 端点见同文件下方。
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import Conversation, KIND_INIT, Message, User

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _conv_to_dict(c: Conversation) -> dict:
    return {
        "id": str(c.id),
        "title": c.title,
        "status": c.status,
        "created_at": c.created_at.isoformat() if c.created_at else "",
        "updated_at": c.updated_at.isoformat() if c.updated_at else "",
    }


def _get_owned_conversation(db: Session, user_id, conv_id: str) -> Conversation:
    """取会话并校验归属（init 会话靠 user_id）。非本人或已落地（project_id 非 NULL）返回 404。"""
    from app.core.exceptions import NotFoundError
    try:
        cid = uuid.UUID(conv_id)
    except (ValueError, AttributeError):
        raise NotFoundError("会话不存在")
    conv = db.scalar(select(Conversation).where(
        Conversation.id == cid,
        Conversation.user_id == user_id,
        Conversation.kind == KIND_INIT,
    ))
    if conv is None:
        raise NotFoundError("会话不存在")
    return conv


@router.get("/conversations")
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的未落地 init 会话（kind=init AND project_id IS NULL）。"""
    convs = db.scalars(
        select(Conversation).where(
            Conversation.user_id == current_user.id,
            Conversation.kind == KIND_INIT,
            Conversation.project_id.is_(None),
        ).order_by(Conversation.updated_at.desc())
    ).all()
    return [_conv_to_dict(c) for c in convs]


class ConversationCreateIn(BaseModel):
    title: str | None = None


@router.post("/conversations", status_code=201)
def create_conversation(
    payload: ConversationCreateIn | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建空 init 会话。"""
    conv = Conversation(
        kind=KIND_INIT,
        user_id=current_user.id,
        section_id=None,
        title=(payload.title if payload and payload.title else "新对话"),
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _conv_to_dict(conv)


@router.get("/conversations/{conv_id}")
def get_conversation(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取会话 + 消息历史。已落地的会话（project_id 非 NULL）也允许读（用于查看历史）。"""
    from app.core.exceptions import NotFoundError
    try:
        cid = uuid.UUID(conv_id)
    except (ValueError, AttributeError):
        raise NotFoundError("会话不存在")
    conv = db.scalar(select(Conversation).where(
        Conversation.id == cid,
        Conversation.user_id == current_user.id,
        Conversation.kind == KIND_INIT,
    ))
    if conv is None:
        raise NotFoundError("会话不存在")
    messages = db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ).all()
    return {
        **_conv_to_dict(conv),
        "project_id": str(conv.project_id) if conv.project_id else None,
        "messages": [
            {"id": str(m.id), "role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat() if m.created_at else ""}
            for m in messages
        ],
    }


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除会话（级联消息）。只允许删未落地的（project_id NULL）。"""
    conv = _get_owned_conversation(db, current_user.id, conv_id)
    if conv.project_id is not None:
        from app.core.exceptions import ValidationError
        raise ValidationError("已落地为项目的会话不可删除")
    db.delete(conv)
    db.commit()
    return None
```

- [ ] **Step 2: 注册路由**

在 `apps/api/app/api/router.py`：import 加 `assistant`，在 init_assistant 注册行（L10-11）位置改为：

```python
api_router.include_router(assistant.router)
```

（注意：此时 init_assistant 还没删，先把 assistant 加上；Task 10 统一删 init_assistant。若担心冲突，可同时把 init_assistant 的 import 和注册注释掉——但为减少中间态，本任务先并存，Task 10 清理。）

- [ ] **Step 3: 冒烟测试 — 端点注册**

Run: `cd apps/api && uv run python -c "from app.main import app; paths=[p for p in app.openapi()['paths'] if '/assistant/' in p]; print(sorted(paths))"`
Expected: 含 `/api/v1/assistant/conversations`、`/api/v1/assistant/conversations/{conv_id}`（GET/DELETE）

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/api/assistant.py apps/api/app/api/router.py
git commit -m "feat(api): /assistant/conversations 顶层 init 会话 CRUD"
```

---

## Task 7: 后端 API — assistant chat 端点（SSE + [READY_TO_CREATE] 透传）

**Files:**
- Modify: `apps/api/app/api/assistant.py`（追加 chat 端点）

- [ ] **Step 1: 追加 chat 端点到 assistant.py**

在 assistant.py 末尾追加（复用 ai.py 的 SSE 模式 + init_orchestrator.astream_init_chat）：

```python
import asyncio
import time
from fastapi import Body
from fastapi.responses import StreamingResponse

from app.ai.init_orchestrator import astream_init_chat
from app.services import llm_config_service

HEARTBEAT_INTERVAL = 5.0


def _sse_event(event: str, data: dict) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class ChatRequest(BaseModel):
    message: str
    chat_source: str | None = None


@router.post("/conversations/{conv_id}/chat")
async def chat(
    conv_id: str,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """init 助手对话（SSE）。消息存到顶层会话（section_id=NULL）。

    流式 token；done 事件带 message_id + conversation_id + ready_to_create（bool）。
    ready_to_create 由 assistant 回复是否含 [READY_TO_CREATE] 标记判定。
    """
    conv = _get_owned_conversation(db, current_user.id, conv_id)
    # 取历史
    history = list(db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ))
    # 落用户消息（init 消息 section_id=NULL）
    user_msg = Message(conversation_id=conv.id, section_id=None, role="user", content=payload.message)
    db.add(user_msg)
    db.commit()

    llm_config = llm_config_service.resolve_chat_config(
        db, user_id=current_user.id, chat_source=payload.chat_source
    )

    async def generate():
        full_response = ""
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            return
        try:
            async for token in _heartbeat_wrap(astream_init_chat(
                history, payload.message, llm_config=llm_config
            )):
                if token == "__heartbeat__":
                    yield _sse_event("heartbeat", {})
                else:
                    full_response += token
                    yield _sse_event("token", {"text": token})
            # 落助手消息
            ai_msg = Message(conversation_id=conv.id, section_id=None, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()
            # 判定时机标记
            ready = "[READY_TO_CREATE]" in full_response
            yield _sse_event("done", {
                "message_id": str(ai_msg.id),
                "conversation_id": str(conv.id),
                "ready_to_create": ready,
            })
        except asyncio.CancelledError:
            if full_response:
                db.add(Message(conversation_id=conv.id, section_id=None, role="assistant", content=full_response))
                db.commit()
            raise
        except Exception as e:
            from app.ai.llm_errors import friendly_llm_error
            db.rollback()
            yield _sse_event("error", {"code": "llm_error", "message": friendly_llm_error(e)})

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _heartbeat_wrap(async_gen):
    """token 生成器心跳包装（复用 ai.py 模式）。"""
    ait = async_gen.__aiter__()
    nxt = asyncio.ensure_future(ait.__anext__())
    while True:
        done, _pending = await asyncio.wait({nxt}, timeout=HEARTBEAT_INTERVAL)
        if nxt in done:
            try:
                token = nxt.result()
            except StopAsyncIteration:
                break
            yield token
            nxt = asyncio.ensure_future(ait.__anext__())
        else:
            yield "__heartbeat__"
```

- [ ] **Step 2: 冒烟测试 — 端点注册**

Run: `cd apps/api && uv run python -c "from app.main import app; print('/api/v1/assistant/conversations/{conv_id}/chat' in app.openapi()['paths'])"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/api/assistant.py
git commit -m "feat(api): /assistant/conversations/{id}/chat SSE 对话 + 时机标记透传"
```

---

## Task 8: 后端 API — assistant generate 端点（扳机落地）

**Files:**
- Modify: `apps/api/app/api/assistant.py`（追加 generate 端点）

- [ ] **Step 1: 追加 generate 端点**

在 assistant.py 末尾追加（用户按扳机 → 建项目 + 填章 + 标记会话落地）：

```python
from app.ai.init_orchestrator import astream_init_generate


class GenerateRequest(BaseModel):
    sections: list[str] | None = None  # 按 key 过滤，默认全部
    chat_source: str | None = None


@router.post("/conversations/{conv_id}/generate")
async def generate(
    conv_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    payload: GenerateRequest | None = Body(default=None),
):
    """扳机落地：为 init 会话建项目 + 填章节初稿（SSE 进度）。

    流式事件：project_created / chapter_start / token / chapter_done / all_done。
    """
    conv = _get_owned_conversation(db, current_user.id, conv_id)
    # 防重复落地
    from app.core.exceptions import ValidationError
    if conv.project_id is not None:
        raise ValidationError("该会话已落地为项目")

    history = list(db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ))

    llm_config = llm_config_service.resolve_chat_config(
        db, user_id=current_user.id, chat_source=(payload.chat_source if payload else None)
    )
    sections_filter = payload.sections if payload else None

    async def generate_stream():
        if llm_config is None:
            yield _sse_event("error", {"code": "no_llm_config", "message": "未配置 LLM，请先在设置中配置"})
            return
        try:
            async for kind, data in astream_init_generate(
                db, conv, history, current_user,
                llm_config=llm_config, sections=sections_filter,
            ):
                if kind == "project_created":
                    yield _sse_event("project_created", data)
                elif kind == "chapter_start":
                    yield _sse_event("chapter_start", data)
                elif kind == "token":
                    yield _sse_event("token", {"text": data})
                elif kind == "chapter_done":
                    yield _sse_event("chapter_done", data)
                elif kind == "all_done":
                    yield _sse_event("done", data)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            from app.ai.llm_errors import friendly_llm_error
            db.rollback()
            yield _sse_event("error", {"code": "llm_error", "message": friendly_llm_error(e)})

    return StreamingResponse(generate_stream(), media_type="text/event-stream")
```

- [ ] **Step 2: 冒烟测试 — 端点注册**

Run: `cd apps/api && uv run python -c "from app.main import app; print('/api/v1/assistant/conversations/{conv_id}/generate' in app.openapi()['paths'])"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/api/assistant.py
git commit -m "feat(api): /assistant/conversations/{id}/generate 扳机落地建项目"
```

---

## Task 9: 后端测试 — assistant CRUD + chat + generate

**Files:**
- Create: `apps/api/tests/test_assistant.py`

- [ ] **Step 1: 写测试文件**

```python
# apps/api/tests/test_assistant.py
"""ChatGPT 式初始化助手 API 测试：顶层 init 会话 CRUD + chat + generate。"""
from uuid import UUID

from app.models import Conversation, KIND_INIT, Message, Project, Section
from app.services.seed_service import ensure_default_template


def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })


def _make_user_with_config(client, registered_user, db_session):
    """登录 + 配 LLM（端点要求生效配置）。"""
    from app.models import User, UserLLMConfig
    from app.core.security import encrypt_value
    from sqlalchemy import select

    ensure_default_template(db_session)
    user = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    db_session.add(UserLLMConfig(
        user_id=user.id, name="test", provider="custom",
        base_url="https://test.example.com",
        api_key_encrypted=encrypt_value("sk-test-key"),
        model="test-model",
    ))
    db_session.commit()
    _login(client, registered_user)
    return user


# ── CRUD ─────────────────────────────────────────────────────────────

def test_create_and_list_conversations(client, registered_user, db_session):
    """创建 init 会话，列表只列未落地的。"""
    _make_user_with_config(client, registered_user, db_session)
    # 建两个
    c1 = client.post("/api/v1/assistant/conversations", json={"title": "想法A"}).json()
    client.post("/api/v1/assistant/conversations")  # 默认标题
    assert c1["title"] == "想法A"

    res = client.get("/api/v1/assistant/conversations")
    assert res.status_code == 200
    assert len(res.json()) == 2
    assert res.json()[0]["title"] in ("想法A", "新对话")


def test_get_conversation_returns_messages(client, registered_user, db_session):
    """取会话含消息历史。"""
    user = _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()
    # 直接写消息（绕过 LLM）
    c = db_session.get(Conversation, UUID(conv["id"]))
    db_session.add(Message(conversation_id=c.id, section_id=None, role="user", content="hi"))
    db_session.commit()

    res = client.get(f"/api/v1/assistant/conversations/{conv['id']}")
    assert res.status_code == 200
    assert res.json()["project_id"] is None
    assert len(res.json()["messages"]) == 1
    assert res.json()["messages"][0]["content"] == "hi"


def test_delete_conversation(client, registered_user, db_session):
    """删除未落地会话。"""
    _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()
    res = client.delete(f"/api/v1/assistant/conversations/{conv['id']}")
    assert res.status_code == 204
    # 列表已无
    assert len(client.get("/api/v1/assistant/conversations").json()) == 0


def test_ownership_other_user_404(client, registered_user, db_session):
    """非本人会话 CRUD 返回 404。"""
    _make_user_with_config(client, registered_user, db_session)
    # 建别人的 init 会话
    from app.models import User
    other = User(username="other2", email="other2@test.com", password_hash="x", name="o")
    db_session.add(other)
    db_session.commit()
    other_conv = Conversation(kind=KIND_INIT, user_id=other.id, section_id=None, title="别人的")
    db_session.add(other_conv)
    db_session.commit()

    assert client.get(f"/api/v1/assistant/conversations/{other_conv.id}").status_code == 404
    assert client.delete(f"/api/v1/assistant/conversations/{other_conv.id}").status_code == 404


# ── chat（mock）──────────────────────────────────────────────────────

def test_chat_emits_token_done_and_ready_flag(client, registered_user, db_session, monkeypatch):
    """chat SSE：token/done + ready_to_create 由 [READY_TO_CREATE] 标记判定。"""
    _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()

    async def fake_astream_init_chat(history, user_input, **kwargs):
        yield "信息够了，可以创建了"
        yield "\n[READY_TO_CREATE]"

    monkeypatch.setattr("app.api.assistant.astream_init_chat", fake_astream_init_chat)

    res = client.post(f"/api/v1/assistant/conversations/{conv['id']}/chat", json={"message": "我想做XX"})
    assert res.status_code == 200
    body = res.text
    assert "event: token" in body
    assert "可以创建了" in body
    assert "event: done" in body
    # ready_to_create=true（因含标记）
    import json as _json
    done_line = [l for l in body.split("\n") if l.startswith("data: ") and "ready_to_create" in l][-1]
    assert _json.loads(done_line[6:])["ready_to_create"] is True

    # 消息落库（section_id=NULL）
    db_session.expire_all()
    msgs = db_session.query(Message).filter_by(conversation_id=UUID(conv["id"])).all()
    assert len(msgs) == 2  # user + assistant
    assert all(m.section_id is None for m in msgs)


def test_chat_ready_false_without_marker(client, registered_user, db_session, monkeypatch):
    """无标记时 ready_to_create=false。"""
    _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()

    async def fake_astream_init_chat(history, user_input, **kwargs):
        yield "还需要补充技术领域"

    monkeypatch.setattr("app.api.assistant.astream_init_chat", fake_astream_init_chat)

    res = client.post(f"/api/v1/assistant/conversations/{conv['id']}/chat", json={"message": "hi"})
    import json as _json
    done_line = [l for l in res.text.split("\n") if l.startswith("data: ") and "ready_to_create" in l][-1]
    assert _json.loads(done_line[6:])["ready_to_create"] is False


# ── generate（mock）──────────────────────────────────────────────────

def test_generate_creates_project_and_marks_conversation(client, registered_user, db_session, monkeypatch):
    """generate：建项目+填章+会话 project_id 填上。"""
    user = _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()

    async def fake_astream_init_generate(db, conversation, history, user, **kwargs):
        from app.services.project_service import create_project
        from app.models import Section as _S
        from sqlalchemy import select as _sel
        project = create_project(db, user=user, title="测试项目")
        conversation.project_id = project.id
        db.commit()
        yield ("project_created", {"project_id": str(project.id)})
        secs = list(db.scalars(_sel(_S).where(_S.project_id == project.id).order_by(_S.order)))
        for idx, sec in enumerate(secs, start=1):
            yield ("chapter_start", {"index": idx, "total": len(secs), "title": sec.title, "key": sec.key})
            from app.ai.markdown_to_tiptap import markdown_to_tiptap
            sec.content = markdown_to_tiptap(f"{sec.title}初稿")
            sec.status = "drafting"
            db.commit()
            yield ("chapter_done", {"index": idx, "title": sec.title, "key": sec.key, "status": "ok", "error": None})
        yield ("all_done", {"project_id": str(project.id)})

    monkeypatch.setattr("app.api.assistant.astream_init_generate", fake_astream_init_generate)

    res = client.post(f"/api/v1/assistant/conversations/{conv['id']}/generate")
    assert res.status_code == 200
    body = res.text
    assert "event: project_created" in body
    assert "event: chapter_done" in body
    assert "event: done" in body

    # 会话已落地（project_id 非 NULL）→ 列表不再显示
    db_session.expire_all()
    c = db_session.get(Conversation, UUID(conv["id"]))
    assert c.project_id is not None
    assert len(client.get("/api/v1/assistant/conversations").json()) == 0
    # 项目 + 8 章已建
    project = db_session.get(Project, c.project_id)
    assert project is not None
    secs = db_session.query(Section).filter_by(project_id=project.id).all()
    assert len(secs) == 8
    assert all(s.content is not None for s in secs)


def test_generate_rejects_already_landed(client, registered_user, db_session):
    """已落地的会话再次 generate 报错。"""
    _make_user_with_config(client, registered_user, db_session)
    conv = client.post("/api/v1/assistant/conversations").json()
    # 手动标记已落地
    c = db_session.get(Conversation, UUID(conv["id"]))
    from app.models import Project
    p = Project(user_id=c.user_id, title="x")
    db_session.add(p)
    db_session.flush()
    c.project_id = p.id
    db_session.commit()

    res = client.post(f"/api/v1/assistant/conversations/{conv['id']}/generate")
    assert res.status_code in (400, 422)
```

- [ ] **Step 2: 跑测试**

Run: `cd apps/api && uv run pytest tests/test_assistant.py -v`
Expected: 8 个测试全 PASS。

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_assistant.py
git commit -m "test(api): 顶层 init 会话 CRUD + chat + generate 测试"
```

---

## Task 10: 后端清理 — 删旧 init_assistant.py + projects.from-chat + 旧测试

**Files:**
- Delete: `apps/api/app/api/init_assistant.py`
- Modify: `apps/api/app/api/router.py`（删 init_assistant import + 注册）
- Modify: `apps/api/app/api/projects.py`（删 create_from_chat L34-64 + 删多余 Body import 若不再用）
- Delete: `apps/api/tests/test_init_assistant.py`

- [ ] **Step 1: 删 init_assistant.py + router 注销**

`git rm apps/api/app/api/init_assistant.py`。在 `apps/api/app/api/router.py`：import 列表去掉 `init_assistant`，删掉 `api_router.include_router(init_assistant.router)` 及其注释行（L10-11）。

- [ ] **Step 2: 删 projects.py 的 create_from_chat**

删 `apps/api/app/api/projects.py` 的 `create_from_chat` 端点（L34-64 整段）。检查顶部 import：若 `Body` 仅此处用，删除 `Body` from fastapi import；`Section`/`select` 若仍有其他端点用（create_project 等不用 Section，但 list/get 不用——确认后保留实际仍用到的）。

- [ ] **Step 3: 删旧测试**

`git rm apps/api/tests/test_init_assistant.py`

- [ ] **Step 4: 冒烟测试 — 旧端点已移除**

Run: `cd apps/api && uv run python -c "from app.main import app; paths=app.openapi()['paths']; print('/api/v1/projects/from-chat' not in paths and all('/init-' not in p for p in paths))"`
Expected: `True`（from-chat 和 init-* 都没了）

- [ ] **Step 5: 跑全量后端测试**

Run: `cd apps/api && uv run pytest tests/ -q`
Expected: 全 PASS（旧 init 测试已删，新 assistant 测试在）。

- [ ] **Step 6: Commit**

```bash
git add -A apps/api/app/api/init_assistant.py apps/api/app/api/router.py apps/api/app/api/projects.py apps/api/tests/test_init_assistant.py
git commit -m "chore(api): 删除旧 init-assistant 弹窗后端 + from-chat 端点 + 旧测试"
```

---

## Task 11: 前端 — api.ts 加 assistant 方法 + 删旧 init 方法

**Files:**
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: 删旧的三个 init 方法**

删 `apps/web/src/lib/api.ts` 的 `createProjectFromChat`（L261-265）、`streamInitChat`（L268-288）、`streamInitGenerate`（L297-364）及它们的注释块（L259-364 整段）。保留 `_consumeSSE`、`_sseHttpError`。

- [ ] **Step 2: 加 assistant 方法（在删的位置或 AI 区末尾）**

```typescript
  // ── 项目初始化助手（ChatGPT 式独立对话页）──
  listAssistantConversations: () =>
    request<{ id: string; title: string; status: string; created_at: string; updated_at: string }[]>(
      '/assistant/conversations',
    ),

  createAssistantConversation: (title?: string) =>
    request<{ id: string; title: string; status: string; created_at: string; updated_at: string }>(
      '/assistant/conversations',
      { method: 'POST', body: JSON.stringify({ title: title ?? null }) },
    ),

  getAssistantConversation: (id: string) =>
    request<{
      id: string; title: string; status: string; created_at: string; updated_at: string
      project_id: string | null
      messages: { id: string; role: string; content: string; created_at: string }[]
    }>(`/assistant/conversations/${id}`),

  deleteAssistantConversation: (id: string) =>
    request<void>(`/assistant/conversations/${id}`, { method: 'DELETE' }),

  /** init 助手对话（SSE）。done 事件额外带 ready_to_create。 */
  streamAssistantChat: async (
    convId: string,
    message: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
    onDone?: (d: { message_id: string; conversation_id?: string; ready_to_create?: boolean }) => void,
    chatSource?: string,
  ) => {
    const res = await fetch(`${BASE}/api/v1/assistant/conversations/${convId}/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, ...(chatSource ? { chat_source: chatSource } : {}) }),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken, onDone as never)
  },

  /** 扳机落地：建项目+填章（SSE，多事件）。 */
  streamAssistantGenerate: async (
    convId: string,
    handlers: {
      onProjectCreated?: (d: { project_id: string }) => void
      onChapterStart?: (d: { index: number; total: number; title: string; key: string }) => void
      onToken?: (t: string) => void
      onChapterDone?: (d: { index: number; title: string; key: string; status: string; error: string | null }) => void
      onAllDone?: (d: { project_id: string }) => void
    },
    signal?: AbortSignal,
    sections?: string[],
  ) => {
    const res = await fetch(`${BASE}/api/v1/assistant/conversations/${convId}/generate`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sections && sections.length ? { sections } : {}),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    if (!res.body) return
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      for (const evt of events) {
        const lines = evt.split('\n')
        let eventType = 'message'
        let dataLine = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim()
          else if (line.startsWith('data: ')) dataLine = line.slice(6)
        }
        if (!dataLine) continue
        let data: Record<string, unknown> = {}
        try { data = JSON.parse(dataLine) } catch { continue }
        if (eventType === 'error') {
          throw { code: (data.code as string) || 'llm_error', message: (data.message as string) || 'AI 服务错误' } as ApiError
        }
        if (eventType === 'project_created') handlers.onProjectCreated?.(data as { project_id: string })
        else if (eventType === 'chapter_start') handlers.onChapterStart?.(data as { index: number; total: number; title: string; key: string })
        else if (eventType === 'token') { const t = data.text as string | undefined; if (t) handlers.onToken?.(t) }
        else if (eventType === 'chapter_done') handlers.onChapterDone?.(data as { index: number; title: string; key: string; status: string; error: string | null })
        else if (eventType === 'done') handlers.onAllDone?.(data as { project_id: string })
      }
    }
  },
```

- [ ] **Step 3: typecheck**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无错误。

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/api.ts
git commit -m "feat(web): api.ts 加 assistant 方法 + 删旧 init 方法"
```

---

## Task 12: 前端 — queries.ts 加 assistant hooks + queryKeys

**Files:**
- Modify: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: 在 queryKeys 对象加 assistant 段**

在 `apps/web/src/lib/queries.ts` 的 `queryKeys` 对象（L27-76）内加：

```typescript
  assistant: {
    conversations: ['assistant', 'conversations'],
    conversation: (id: string) => ['assistant', 'conversations', id],
  },
```

- [ ] **Step 2: 加 hooks（文件末尾的 hook 区）**

```typescript
// ── 初始化助手顶层会话（ChatGPT 式对话页）──
export function useAssistantConversations() {
  return useQuery({
    queryKey: queryKeys.assistant.conversations,
    queryFn: () => api.listAssistantConversations(),
  })
}

export function useAssistantConversation(id: string | null) {
  return useQuery({
    queryKey: id ? queryKeys.assistant.conversation(id) : ['assistant', 'conversations', 'none'],
    queryFn: () => api.getAssistantConversation(id!),
    enabled: !!id,
  })
}

export function useCreateAssistantConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (title?: string) => api.createAssistantConversation(title),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.assistant.conversations }),
  })
}

export function useDeleteAssistantConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteAssistantConversation(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.assistant.conversations }),
  })
}
```

确认文件顶部已 import `useQuery`/`useMutation`/`useQueryClient`/`api`（既有 hooks 在用，应已 import）。

- [ ] **Step 3: typecheck**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无错误。

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/queries.ts
git commit -m "feat(web): queries.ts 加 assistant 会话 hooks + queryKeys"
```

---

## Task 13: 前端 — 左侧对话列表组件

**Files:**
- Create: `apps/web/src/components/assistant/assistant-conversation-list.tsx`

- [ ] **Step 1: 写列表组件**

```tsx
'use client'

import { Loader2, MessageSquare, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

interface AssistantConversationListProps {
  conversations: { id: string; title: string; updated_at: string }[]
  currentId: string | null
  loading: boolean
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}

export function AssistantConversationList({
  conversations, currentId, loading, onSelect, onNew, onDelete,
}: AssistantConversationListProps) {
  return (
    <div className="flex h-full w-64 flex-col border-r bg-muted/30">
      <div className="p-2">
        <Button variant="outline" size="sm" className="w-full justify-start gap-1.5" onClick={onNew}>
          <Plus className="size-3.5" /> 新对话
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className="space-y-0.5 p-2">
          {loading ? (
            <div className="flex justify-center p-4">
              <Loader2 className="size-4 animate-spin text-muted-foreground" />
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-2 py-4 text-center text-xs text-muted-foreground">暂无对话</p>
          ) : (
            conversations.map((c) => (
              <div
                key={c.id}
                className={cn(
                  'group flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[13px]',
                  c.id === currentId ? 'bg-background font-medium' : 'hover:bg-background/60',
                )}
                onClick={() => onSelect(c.id)}
              >
                <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="flex-1 truncate">{c.title || '新对话'}</span>
                <button
                  type="button"
                  className="shrink-0 text-muted-foreground opacity-0 hover:text-destructive group-hover:opacity-100"
                  onClick={(e) => { e.stopPropagation(); onDelete(c.id) }}
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
```

- [ ] **Step 2: typecheck**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无错误（组件未被引用时也应编译）。

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/assistant/assistant-conversation-list.tsx
git commit -m "feat(web): 初始化助手左侧对话列表组件"
```

---

## Task 14: 前端 — 两栏主体组件 init-assistant.tsx

**Files:**
- Create: `apps/web/src/components/assistant/init-assistant.tsx`

这是核心组件：左列表 + 右对话区 + 监听 [READY_TO_CREATE] 渲染扳机 + generate 进度 + 跳转。

- [ ] **Step 1: 写主组件**

```tsx
'use client'

import { Loader2, RotateCcw, Sparkles } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import ReactMarkdown from 'react-markdown'

import { AssistantConversationList } from '@/components/assistant/assistant-conversation-list'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import { queryKeys, useAssistantConversation, useAssistantConversations, useCreateAssistantConversation, useDeleteAssistantConversation } from '@/lib/queries'
import { cn } from '@/lib/utils'

const READY_MARKER = '[READY_TO_CREATE]'
const GUIDE = '描述你的发明想法，我帮你理清思路并生成交底书初稿。'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  // assistant 消息是否触发过创建扳机（含 READY 标记）
  ready?: boolean
}

interface ChapterProgress {
  index: number; total: number; title: string; key: string
  status: 'generating' | 'ok' | 'failed'; error: string | null
}

export function InitAssistant() {
  const router = useRouter()
  const qc = useQueryClient()
  const { data: conversations, isLoading: listLoading } = useAssistantConversations()
  const createConv = useCreateAssistantConversation()
  const deleteConv = useDeleteAssistantConversation()

  const [currentId, setCurrentId] = useState<string | null>(null)
  const { data: current } = useAssistantConversation(currentId)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null)
  const [chapters, setChapters] = useState<ChapterProgress[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 首次加载：若无会话则建一个；有则选第一个
  useEffect(() => {
    if (!listLoading && conversations) {
      if (conversations.length === 0) {
        createConv.mutate(undefined, { onSuccess: (c) => setCurrentId(c.id) })
      } else if (!currentId) {
        setCurrentId(conversations[0].id)
      }
    }
  }, [listLoading, conversations, currentId, createConv])

  // 切换会话：加载历史消息
  useEffect(() => {
    if (current) {
      setMessages(current.messages.map((m) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        ready: m.role === 'assistant' && m.content.includes(READY_MARKER),
      })))
      setCreatedProjectId(current.project_id)
      setGenerating(false)
      setChapters([])
    }
  }, [current?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  // 自动滚底
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages])

  function handleNew() {
    createConv.mutate(undefined, { onSuccess: (c) => setCurrentId(c.id) })
  }

  function handleSelect(id: string) {
    setCurrentId(id)
  }

  function handleDelete(id: string) {
    deleteConv.mutate(id, {
      onSuccess: () => {
        if (id === currentId) setCurrentId(null)
      },
    })
  }

  async function handleSend() {
    if (!input.trim() || !currentId || sending) return
    const msg = input.trim()
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: msg }, { role: 'assistant', content: '' }])
    setSending(true)
    const ac = new AbortController()
    abortRef.current = ac
    let full = ''
    try {
      await api.streamAssistantChat(
        currentId, msg,
        (t) => {
          full += t
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last && last.role === 'assistant') {
              next[next.length - 1] = { role: 'assistant', content: full, ready: full.includes(READY_MARKER) }
            }
            return next
          })
        },
        ac.signal,
        (done) => {
          // ready 也以 done 事件为准（兜底）
          if (done.ready_to_create) {
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              if (last && last.role === 'assistant') next[next.length - 1] = { ...last, ready: true }
              return next
            })
          }
        },
      )
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') {
        toast.error('回复失败：' + ((e as { message?: string })?.message ?? String(e)))
      }
    } finally {
      setSending(false)
    }
  }

  async function handleGenerate(isRetry = false) {
    if (!currentId) return
    const targetSections = isRetry ? chapters.filter((c) => c.status === 'failed').map((c) => c.key) : undefined
    setGenerating(true)
    if (!isRetry) setChapters([])
    const ac = new AbortController()
    abortRef.current = ac
    const failedKeys = new Set<string>()
    try {
      await api.streamAssistantGenerate(
        currentId,
        {
          onProjectCreated: (d) => setCreatedProjectId(d.project_id),
          onChapterStart: (d) => setChapters((prev) => {
            const exists = prev.find((c) => c.key === d.key)
            if (exists) return prev.map((c) => c.key === d.key ? { ...c, status: 'generating' } : c)
            return [...prev, { ...d, status: 'generating', error: null }]
          }),
          onToken: () => {},
          onChapterDone: (d) => {
            if (d.status === 'failed') failedKeys.add(d.key)
            else failedKeys.delete(d.key)
            setChapters((prev) => prev.map((c) => c.key === d.key ? { ...c, status: d.status as 'ok' | 'failed', error: d.error } : c))
          },
          onAllDone: () => {
            qc.invalidateQueries({ queryKey: queryKeys.assistant.conversations })
            if (!isRetry && failedKeys.size === 0) {
              toast.success('项目初稿已生成')
            } else if (failedKeys.size > 0) {
              toast.warning('部分章节失败，可重试')
            }
          },
        },
        ac.signal,
        targetSections,
      )
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') {
        toast.error('生成失败：' + ((e as { message?: string })?.message ?? String(e)))
      }
    }
  }

  const hasFailed = chapters.some((c) => c.status === 'failed')
  const showChapterProgress = generating || chapters.length > 0

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <AssistantConversationList
        conversations={conversations ?? []}
        currentId={currentId}
        loading={listLoading}
        onSelect={handleSelect}
        onNew={handleNew}
        onDelete={handleDelete}
      />
      <div className="flex flex-1 flex-col">
        {/* 右侧主对话区 */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
            {messages.length === 0 && !showChapterProgress && (
              <div className="mt-20 text-center">
                <Sparkles className="mx-auto mb-3 size-8 text-primary" />
                <p className="text-lg font-medium">{GUIDE}</p>
                <p className="mt-1 text-sm text-muted-foreground">在下方输入框开始描述</p>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                <div className={cn(
                  'max-w-[85%] rounded-lg px-3 py-2 text-[13px] leading-relaxed',
                  m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted',
                )}>
                  {m.role === 'assistant' ? (
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown>{m.content.replace(READY_MARKER, '').trim() || '…'}</ReactMarkdown>
                    </div>
                  ) : (
                    <span className="whitespace-pre-wrap">{m.content}</span>
                  )}
                </div>
              </div>
            ))}
            {/* 创建扳机（当 assistant 标记 ready 且未生成中） */}
            {!generating && messages.some((m) => m.ready) && !showChapterProgress && (
              <div className="flex justify-center">
                <Button onClick={() => handleGenerate(false)} className="gap-1.5">
                  <Sparkles className="size-3.5" /> 信息已理清，创建项目
                </Button>
              </div>
            )}
            {/* 章节生成进度 */}
            {showChapterProgress && (
              <div className="space-y-2 rounded-lg border p-3">
                <p className="text-xs font-medium text-muted-foreground">生成项目初稿…</p>
                {chapters.map((c) => (
                  <div key={c.key} className="flex items-center justify-between text-[13px]">
                    <span>{c.index}/{c.total} {c.title}</span>
                    {c.status === 'generating' && <Loader2 className="size-3.5 animate-spin text-primary" />}
                    {c.status === 'ok' && <span className="text-xs text-green-600">✓</span>}
                    {c.status === 'failed' && <span className="text-xs text-destructive">✗</span>}
                  </div>
                ))}
                {!generating && (
                  <div className="flex items-center justify-end gap-2 border-t pt-2">
                    {hasFailed && (
                      <Button variant="outline" size="sm" onClick={() => handleGenerate(true)} className="gap-1.5">
                        <RotateCcw className="size-3.5" /> 重试失败
                      </Button>
                    )}
                    {createdProjectId && (
                      <Button size="sm" onClick={() => router.push(`/projects/${createdProjectId}`)}>
                        进入项目
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}
            {/* 已落地跳转卡片（generate 完成后） */}
            {!generating && createdProjectId && !showChapterProgress && (
              <div className="flex justify-center">
                <div className="rounded-lg border bg-muted/50 px-4 py-2 text-center text-[13px]">
                  项目已创建 <Button variant="link" className="h-auto p-0" onClick={() => router.push(`/projects/${createdProjectId}`)}>点此进入 →</Button>
                </div>
              </div>
            )}
          </div>
        </div>
        {/* 输入框 */}
        <div className="border-t">
          <div className="mx-auto flex max-w-3xl gap-2 px-4 py-3">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="描述你的发明想法…（Enter 发送，Shift+Enter 换行）"
              className="min-h-[44px] resize-none"
              disabled={sending || generating}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
              }}
            />
            <Button size="icon" onClick={handleSend} disabled={!input.trim() || sending || generating}>
              <Sparkles className="size-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: typecheck**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无错误。

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/assistant/init-assistant.tsx
git commit -m "feat(web): ChatGPT 式初始化助手两栏主体组件"
```

---

## Task 15: 前端 — /new 路由页 + project-list 入口改造

**Files:**
- Create: `apps/web/src/app/(app)/new/page.tsx`
- Modify: `apps/web/src/components/project-list.tsx`
- Delete: `apps/web/src/components/init-assistant-dialog.tsx`

- [ ] **Step 1: 建 /new 路由页**

```tsx
// apps/web/src/app/(app)/new/page.tsx
import { InitAssistant } from '@/components/assistant/init-assistant'

export default function NewProjectPage() {
  return <InitAssistant />
}
```

- [ ] **Step 2: project-list 入口改跳 /new**

`apps/web/src/components/project-list.tsx`：
- 删 `import { InitAssistantDialog } from '@/components/init-assistant-dialog'`（L7）
- PageHeader 里的 `<InitAssistantDialog />` 替换为跳 `/new` 的链接按钮：
```tsx
import Link from 'next/link'
import { Sparkles } from 'lucide-react'
// ...在 PageHeader 的 div 里：
<Button variant="outline" asChild className="gap-1.5">
  <Link href="/new"><Sparkles className="size-3.5" /> AI 对话新建</Button>
</Button>
```
（注意 `asChild` + Link 的用法，参考项目其他 Link 按钮；若 Button 不支持 asChild 则用 onClick router.push）

- [ ] **Step 3: 删旧弹窗组件**

`git rm apps/web/src/components/init-assistant-dialog.tsx`

- [ ] **Step 4: typecheck + build**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm build`
Expected: 无错误，build 成功，路由表含 `/new`。

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/(app)/new/page.tsx apps/web/src/components/project-list.tsx
git rm apps/web/src/components/init-assistant-dialog.tsx
git commit -m "feat(web): /new 路由页 + project-list 入口跳转 + 删旧弹窗组件"
```

---

## Task 16: 全量验证 + 收尾

- [ ] **Step 1: 后端全量测试**

Run: `cd apps/api && uv run pytest tests/ -q`
Expected: 全 PASS（含新 test_assistant.py 8 个，旧 test_init_assistant.py 已删）。

- [ ] **Step 2: 前端 typecheck + build**

Run: `cd apps/web && pnpm exec tsc --noEmit && pnpm build`
Expected: 无错误。

- [ ] **Step 3: 端到端冒烟（手动）**

启动后端 + 前端，访问 `/new`：确认两栏、新对话、输入对话、agent 回复、ready 扳机、生成进度、跳转项目页。记下任何异常。

- [ ] **Step 4: 合并到 main（finishing-a-development-branch）**

跑测试通过后，用 finishing-a-development-branch skill 合并 feat/chatgpt-init-assistant 到 main。

---

## Self-Review 记录

- **Spec 覆盖**：§2 形态（Task 13/14/15）✓；§3 数据模型（Task 1/2/3）✓；§4 后端 API（Task 6/7/8）+ 删旧（Task 10）✓；§5 前端（Task 11/12/13/14/15）✓；§6 测试（Task 9）✓；§7 风险（归属校验 Task 9、防重复落地 Task 8/9、手动扳机兜底 Task 14）✓。
- **类型一致性**：`astream_init_generate(db, conversation, history, user, ...)` 签名在 Task 5 定义、Task 8 调用、Task 9 mock 一致 ✓；`[READY_TO_CREATE]` 标记 Task 4 定义、Task 7 透传、Task 14 前端消费一致 ✓。
- **无占位符**：所有步骤含完整代码/命令。
