# LLM chat / embedding 独立凭据改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把天工的 chat 与 embedding LLM 凭据拆成两套完全独立的链路（独立表、dataclass、resolve 函数、source 维度），支持跨供应商混搭（如智谱 chat + OpenAI embedding），并顺路删除 `allowed_models`。

**Architecture:** 后端：新建 `UserEmbeddingConfig` 表 + 迁移；`ResolvedLLMConfig` 拆成 `ResolvedChatConfig`/`ResolvedEmbeddingConfig`；`resolve_llm_config` 拆成 `resolve_chat_config`/`resolve_embedding_config`（两条 fallback 完全独立，不互通）；用户新增 `/settings/embedding/*` 端点镜像 chat 一套；admin 全局配置 JSON 拆两套；5 个内部 caller 按用途切到对应 resolve 函数。前端：`/settings` 与 `/admin/console/llm` 各拆对话区 + 嵌入区；`LLMConfigEditPanel` 去 adminMode + allowed_models；localStorage 拆双 key。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + alembic（后端）；Next.js + React Query + shadcn/ui 3.x（前端）；pytest + SQLite 内存库（测试）。

**Spec:** `docs/superpowers/specs/2026-07-24-llm-chat-embedding-split-design.md`

**关键实施顺序**（保证中间状态可编译可测）：先建新表/新 dataclass/新 resolve（不删老的）→ 切 caller 到新函数 → 删老 `ResolvedLLMConfig`/`resolve_llm_config`/老列。任务 1-N 按"建新 → 切 → 删老"排，每个任务结束都能跑测试。

---

## 文件结构

### 后端（apps/api/）
| 文件 | 职责 | 动作 |
|---|---|---|
| `app/models/user_embedding_config.py` | 新表 `UserEmbeddingConfig` | 新建 |
| `app/models/user_llm_config.py` | 删 `embedding_model` 列 | 改 |
| `app/models/__init__.py` | 导出 `UserEmbeddingConfig` | 改 |
| `alembic/versions/b_split_embedding_config.py` | 建新表 + 删老列 | 新建 |
| `app/services/llm_config_service.py` | 核心：拆 dataclass/resolve/build/fallback/CRUD/global；删 allowed_models | 改（大） |
| `app/ai/llm_client.py` | `get_llm` 收 `ResolvedChatConfig` | 改 |
| `app/rag/embedding.py` | `get_embedder` 收 `ResolvedEmbeddingConfig` | 改 |
| `app/rag/archiver.py` | 改调 `resolve_embedding_config` | 改 |
| `app/rag/retriever.py` | 改调 `resolve_embedding_config` | 改 |
| `app/services/knowledge_service.py` | 改调 `resolve_embedding_config` | 改 |
| `app/services/review_service.py` | 改调 `resolve_chat_config` | 改 |
| `app/services/summary_service.py` | 改调 `resolve_chat_config` | 改 |
| `app/services/conversation_service.py` | 类型换 `ResolvedChatConfig` | 改 |
| `app/api/ai.py` | 4 端点用 `chat_source` + `resolve_chat_config`；改 `CaptionRequest`/schema | 改 |
| `app/schemas/ai.py` | `source` → `chat_source` | 改 |
| `app/api/settings.py` | chat 端点去 embedding_model；新增 `/settings/embedding/*` | 改 |
| `app/api/admin/console.py` | global 拆两套；test/models 拆四端点；删 allowed_models | 改 |
| `app/core/config.py` | （可选）env 字段说明，实际不改（chat/embedding 共用 glm_* env） | 不改 |
| 测试（多个） | 见各任务 | 新建/改 |

### 前端（apps/web/src/）
| 文件 | 职责 | 动作 |
|---|---|---|
| `types/api.ts` | 新 `UserEmbeddingConfig`；`GlobalLLMSettings` 拆；删 allowed_models；test 响应语义 | 改 |
| `lib/api.ts` | embedding 端点 client；global 拆；test 语义 | 改 |
| `lib/queries.ts` | embedding hooks；global hooks 拆 | 改 |
| `lib/llm-source.ts` | 双 key + 双函数 | 改 |
| `components/llm-config/LLMConfigEditPanel.tsx` | 去 adminMode + allowed_models | 改 |
| `components/llm-config/EmbeddingConfigRow.tsx` | 镜像 LLMConfigRow | 新建 |
| `app/(app)/settings/page.tsx` | 拆两区 | 改 |
| `app/(app)/admin/console/llm/page.tsx` | 拆两区 + test/models 拆 | 改 |

---

## Task 1: 新建 `UserEmbeddingConfig` 表 + 模型导出

**Files:**
- Create: `apps/api/app/models/user_embedding_config.py`
- Modify: `apps/api/app/models/__init__.py`
- Test: `apps/api/tests/test_embedding_config_model.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_embedding_config_model.py`:

```python
"""UserEmbeddingConfig 表模型测试。"""

from app.models import UserEmbeddingConfig, Base


def test_model_imported():
    """UserEmbeddingConfig 可从 app.models 导入（确认 __init__ 导出）。"""
    assert UserEmbeddingConfig is not None


def test_model_in_metadata():
    """表注册在 Base.metadata（conftest 建表依赖此）。"""
    assert "user_embedding_configs" in Base.metadata.tables


def test_model_columns(db_session, registered_user):
    """可插入并读回一条 embedding 配置（覆盖所有列）。"""
    from app.core.security import encrypt_value
    cfg = UserEmbeddingConfig(
        user_id=registered_user["id"],
        name="智谱 embedding",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_encrypted=encrypt_value("sk-test-1234567890"),
        model="embedding-3",
    )
    db_session.add(cfg)
    db_session.commit()
    db_session.refresh(cfg)
    assert cfg.id is not None
    assert cfg.name == "智谱 embedding"
    assert cfg.model == "embedding-3"
    assert cfg.user_id is not None
    assert cfg.created_at is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_embedding_config_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'UserEmbeddingConfig'`

- [ ] **Step 3: 新建模型**

Create `apps/api/app/models/user_embedding_config.py`:

```python
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class UserEmbeddingConfig(Base, IdMixin, TimestampMixin):
    """用户的 embedding 配置（与 chat 配置独立——支持跨供应商混搭）。

    与 UserLLMConfig 对称：同样列结构，只是语义是 embedding 凭据。
    source 协议前缀 custom-emb:{id} 指向本表的行。
    """

    __tablename__ = "user_embedding_configs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))  # 如「智谱 embedding」
    base_url: Mapped[str] = mapped_column(String(255))
    api_key_encrypted: Mapped[str] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(100))  # embedding 模型名
```

- [ ] **Step 4: 导出**

Modify `apps/api/app/models/__init__.py` — add the import (after line 26 `from app.models.user_llm_config import UserLLMConfig`):

```python
from app.models.user_embedding_config import UserEmbeddingConfig
```

And add `"UserEmbeddingConfig",` to the `__all__` list (after `"UserLLMConfig",` on line 34).

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_embedding_config_model.py -v`
Expected: PASS (3 tests). 注：此时表还没迁移，但 conftest 的 `engine` fixture 用 `Base.metadata.create_all` 建表（新模型已注册到 metadata），所以测试库里表已存在。生产库的迁移在 Task 2。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/models/user_embedding_config.py app/models/__init__.py tests/test_embedding_config_model.py
git commit -m "feat(models): 新建 UserEmbeddingConfig 表（与 chat 配置独立）"
```

---

## Task 2: 迁移——建 user_embedding_configs 表 + 删 user_llm_configs.embedding_model

**Files:**
- Create: `apps/api/alembic/versions/b_split_embedding_config.py`

> 先确认当前 head revision：`cd apps/api && uv run alembic heads`。下面的 `down_revision` 填当前 head。如果 head 不是 `c1a2b3c4d5e6`，按实际填。

- [ ] **Step 1: 确认当前 head**

Run: `cd apps/api && uv run alembic heads`
记录输出的 revision id（记为 `$HEAD`）。

- [ ] **Step 2: 新建迁移文件**

Create `apps/api/alembic/versions/b_split_embedding_config.py`（revision id 用 `b_split_emb_config`，down_revision 填 `$HEAD`）:

```python
"""split embedding config: 新建 user_embedding_configs 表 + 删 user_llm_configs.embedding_model

Revision ID: b_split_emb_config
Revises: $HEAD
Create Date: 2026-07-24

开发阶段：纯 schema 变更，不保数据（老 embedding_model 数据丢弃，用户重建）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b_split_emb_config"
down_revision = "$HEAD"  # ← 替换为 Step 1 的实际 head
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 新建 user_embedding_configs 表（与 user_llm_configs 同构，去掉 provider/embedding_model）
    op.create_table(
        "user_embedding_configs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("api_key_encrypted", sa.String(length=512), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # 2. 删 user_llm_configs.embedding_model 列
    with op.batch_alter_table("user_llm_configs", schema=None) as batch_op:
        batch_op.drop_column("embedding_model")


def downgrade() -> None:
    with op.batch_alter_table("user_llm_configs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("embedding_model", sa.String(length=100), nullable=True))
    op.drop_table("user_embedding_configs")
```

> 注：`id` 用 `String(36)` 是因为 `IdMixin` 用 UUID（存为字符串）。确认 `IdMixin` 的实际列类型——读 `apps/api/app/models/base.py` 的 `IdMixin`，若它是 `String(36)` 则上面正确；若是 `UUID` 则改成 `sa.UUID()`。`created_at`/`updated_at` 同理确认 `TimestampMixin`。**实施时先读 base.py 核对列类型再定稿迁移**。

- [ ] **Step 3: 同步改 UserLLMConfig 模型（删 embedding_model 列声明）**

Modify `apps/api/app/models/user_llm_config.py` — delete line 20:
```python
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
```
（删这一行。`String` import 若变成未使用也删掉——检查 `from sqlalchemy import ForeignKey, String`，`String` 仍被 `name`/`base_url`/`api_key_encrypted`/`model`/`provider` 用，保留。）

- [ ] **Step 4: 测试迁移可跑**

开发库重置 + 升级（开发阶段不保数据）:
```bash
cd apps/api && uv run alembic upgrade head
```
Expected: 无报错，`b_split_emb_config` 成为新 head。

- [ ] **Step 5: 改造现有受影响测试（UserLLMConfig 不再有 embedding_model）**

grep 全测试目录 `embedding_model`：`cd apps/api && grep -rn "embedding_model" tests/`。对每个命中：
- `test_custom_key_crud_api.py` 的 `_make_config`（设了 `embedding_model="other-embed"`）→ 删该字段。
- `test_global_llm_config.py` 的多处 set_global_llm_settings(embedding_model=...) → 这些是全局配置测试，Task 6 改 global settings 时一起改；**本任务先不动 global 测试**（global JSON 暂时还接受 embedding_model key，service 改之前不会报错）。只改 `UserLLMConfig` 直接构造的地方（test_custom_key_crud_api）。
- `test_llm.py` / `test_llm_test_connection.py` 等用 `ResolvedLLMConfig(embedding_model=...)` 的 → Task 3 拆 dataclass 时一起改；本任务不动。

本任务只改 `test_custom_key_crud_api.py` 里直接构造 `UserLLMConfig(..., embedding_model=...)` 的地方（删 `embedding_model=` kwarg）。

Run: `cd apps/api && uv run pytest tests/test_custom_key_crud_api.py -v`
Expected: PASS（删字段后构造仍成功）。

- [ ] **Step 6: 跑全量回归（确认删 embedding_model 列没破坏现有逻辑）**

Run: `cd apps/api && uv run pytest -q`
Expected: 大部分通过。**预期会有 failures**——凡是读 `cfg.embedding_model` 的地方（`config_to_dict`、`resolve_llm_config` 的 custom 分支等）现在会 AttributeError。**这些 failures 是预期的**，会在后续 Task 3-5 修复。记录失败清单，确认它们都是 embedding_model 相关的 AttributeError，不是别的。

> 关键：本任务结束时测试有预期失败是 OK 的——我们在做"删老列"的第一步，后续任务会把读老列的代码也删掉。**不要在本任务里去修这些 failures**，那是 Task 3-5 的工作。

- [ ] **Step 7: 提交**

```bash
cd apps/api && git add alembic/versions/b_split_embedding_config.py app/models/user_llm_config.py tests/test_custom_key_crud_api.py
git commit -m "feat(db): 迁移——建 user_embedding_configs 表 + 删 user_llm_configs.embedding_model 列"
```

---

## Task 3: 拆 dataclass + 新建 chat/embedding resolve 函数（保留老的）

**Files:**
- Modify: `apps/api/app/services/llm_config_service.py`
- Test: `apps/api/tests/test_chat_embedding_resolution.py`

> 策略：本任务**新增** `ResolvedChatConfig`/`ResolvedEmbeddingConfig` + `resolve_chat_config`/`resolve_embedding_config` + 对应的 `_build_*`/`_resolve_*_fallback`/CRUD/global settings（embedding 版），**暂不删**老的 `ResolvedLLMConfig`/`resolve_llm_config`。老的和新的并存，让后续 Task 4-7 能逐步切 caller。Task 8 再删老的。
>
> 这样每个任务结束都能编译能测。

- [ ] **Step 1: 写失败测试（chat + embedding resolve 全分支）**

Create `apps/api/tests/test_chat_embedding_resolution.py`:

```python
"""resolve_chat_config / resolve_embedding_config 解析测试（chat/embedding 独立）。"""

import pytest

from app.core.security import encrypt_value
from app.models import SystemSetting, User, UserEmbeddingConfig, UserGlobalLLMGrant, UserLLMConfig
from app.services.llm_config_service import (
    resolve_chat_config, resolve_embedding_config,
    set_global_chat_settings, set_global_embedding_settings,
)


# ── chat resolve ──

def test_chat_resolve_custom(db_session, registered_user):
    cfg = UserLLMConfig(
        user_id=registered_user["id"], name="chat",
        base_url="https://chat.example.com/v1",
        api_key_encrypted=encrypt_value("sk-chat-1234567890"),
        model="glm-4",
    )
    db_session.add(cfg); db_session.commit(); db_session.refresh(cfg)

    resolved = resolve_chat_config(db_session, user_id=registered_user["id"], chat_source=f"custom-chat:{cfg.id}")
    assert resolved is not None
    assert resolved.base_url == "https://chat.example.com/v1"
    assert resolved.model == "glm-4"
    assert resolved.source == "user"


def test_chat_resolve_global_for_admin(db_session):
    admin = User(username="admin", password_hash="x", name="A", role="admin")
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    set_global_chat_settings(db_session, enabled=True, base_url="https://g-chat.com",
                             api_key="sk-g-1234567890", model="g-chat-model")
    resolved = resolve_chat_config(db_session, user_id=admin.id, chat_source="global")
    assert resolved is not None
    assert resolved.model == "g-chat-model"
    assert resolved.source == "admin"


def test_chat_resolve_env_when_nothing_else(db_session, registered_user, monkeypatch):
    # 无自定义、无 grant、admin 未配 global → env
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "glm_api_key", "sk-env")
    resolved = resolve_chat_config(db_session, user_id=registered_user["id"], chat_source="env")
    assert resolved is not None
    assert resolved.source == "env"


def test_chat_resolve_global_requires_grant_for_non_admin(db_session, registered_user):
    set_global_chat_settings(db_session, enabled=True, api_key="sk-g-1234567890", model="g")
    from app.core.exceptions import ForbiddenError
    with pytest.raises(ForbiddenError):
        resolve_chat_config(db_session, user_id=registered_user["id"], chat_source="global")


def test_chat_resolve_custom_foreign_returns_not_found(db_session, registered_user):
    from app.models import User
    other = User(username="other", password_hash="x", name="O")
    db_session.add(other); db_session.commit(); db_session.refresh(other)
    cfg = UserLLMConfig(user_id=other.id, name="x", base_url="u", api_key_encrypted="e", model="m")
    db_session.add(cfg); db_session.commit(); db_session.refresh(cfg)
    from app.core.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        resolve_chat_config(db_session, user_id=registered_user["id"], chat_source=f"custom-chat:{cfg.id}")


# ── embedding resolve ──

def test_embedding_resolve_custom(db_session, registered_user):
    cfg = UserEmbeddingConfig(
        user_id=registered_user["id"], name="emb",
        base_url="https://emb.example.com/v1",
        api_key_encrypted=encrypt_value("sk-emb-1234567890"),
        model="text-embedding-3-small",
    )
    db_session.add(cfg); db_session.commit(); db_session.refresh(cfg)

    resolved = resolve_embedding_config(db_session, user_id=registered_user["id"], embedding_source=f"custom-emb:{cfg.id}")
    assert resolved is not None
    assert resolved.base_url == "https://emb.example.com/v1"
    assert resolved.model == "text-embedding-3-small"
    assert resolved.source == "user"


def test_embedding_resolve_global_for_admin(db_session):
    admin = User(username="admin2", password_hash="x", name="A", role="admin")
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    set_global_embedding_settings(db_session, enabled=True, base_url="https://g-emb.com",
                                  api_key="sk-ge-1234567890", model="g-emb-model")
    resolved = resolve_embedding_config(db_session, user_id=admin.id, embedding_source="global")
    assert resolved is not None
    assert resolved.model == "g-emb-model"
    assert resolved.source == "admin"


# ── 独立性：chat 与 embedding 各自解析，互不影响 ──

def test_chat_and_embedding_resolve_independently(db_session, registered_user):
    """chat 配 base_url A，embedding 配 base_url B → 各自解析到不同的 base_url。"""
    chat_cfg = UserLLMConfig(
        user_id=registered_user["id"], name="c",
        base_url="https://CHAT.example.com/v1",
        api_key_encrypted=encrypt_value("sk-c-1234567890"), model="chat-model",
    )
    emb_cfg = UserEmbeddingConfig(
        user_id=registered_user["id"], name="e",
        base_url="https://EMB.example.com/v1",
        api_key_encrypted=encrypt_value("sk-e-1234567890"), model="emb-model",
    )
    db_session.add_all([chat_cfg, emb_cfg]); db_session.commit()
    db_session.refresh(chat_cfg); db_session.refresh(emb_cfg)

    chat = resolve_chat_config(db_session, user_id=registered_user["id"], chat_source=f"custom-chat:{chat_cfg.id}")
    emb = resolve_embedding_config(db_session, user_id=registered_user["id"], embedding_source=f"custom-emb:{emb_cfg.id}")
    assert chat.base_url == "https://CHAT.example.com/v1"
    assert emb.base_url == "https://EMB.example.com/v1"
    assert chat.base_url != emb.base_url  # 核心 invariant


# ── fallback 不互通（D4）──

def test_embedding_fallback_no_crosstalk_to_chat(db_session, registered_user):
    """只配了 chat 配置、没配 embedding → resolve_embedding_config 返回 None，不回退 chat。"""
    chat_cfg = UserLLMConfig(
        user_id=registered_user["id"], name="c",
        base_url="https://chat.example.com/v1",
        api_key_encrypted=encrypt_value("sk-c-1234567890"), model="chat-model",
    )
    db_session.add(chat_cfg); db_session.commit()
    # 无 embedding 配置、无 grant、env 假设没配 glm_api_key（conftest 默认空）
    resolved = resolve_embedding_config(db_session, user_id=registered_user["id"])  # fallback
    assert resolved is None  # 不回退到 chat 凭据
```

> 注：`set_global_chat_settings`/`set_global_embedding_settings` 本任务也要新建（见 Step 3）。env 测试依赖 `glm_api_key` 默认空——conftest 里 Settings 从 .env 读，测试环境通常没配，若配了需 monkeypatch 清空。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_chat_embedding_resolution.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_chat_config'` 等。

- [ ] **Step 3: 在 llm_config_service.py 新增 chat/embedding 全套（保留老的）**

Modify `apps/api/app/services/llm_config_service.py` — 在文件末尾（`test_llm_connection` 之后）新增一整块。**不删老代码**。

先加 import（顶部，line 24 之后加 `UserEmbeddingConfig`）:
```python
from app.models import SystemSetting, User, UserEmbeddingConfig, UserGlobalLLMGrant, UserLLMConfig
```

文件末尾追加:

```python


# ════════════════════════════════════════════════════════════
# chat / embedding 独立凭据（B 轮拆分）
# 与上面的耦合版（ResolvedLLMConfig/resolve_llm_config）并存，
# Task 4-7 切 caller 后，Task 8 删掉老的。
# ════════════════════════════════════════════════════════════


@dataclass
class ResolvedChatConfig:
    """解析后的 chat 配置（独立于 embedding）。"""
    base_url: str
    api_key: str
    model: str
    source: str = "user"


@dataclass
class ResolvedEmbeddingConfig:
    """解析后的 embedding 配置（独立于 chat）。"""
    base_url: str
    api_key: str
    model: str
    source: str = "user"


# ── chat 解析 ──

def resolve_chat_config(db: Session, *, user_id, chat_source: str | None = None) -> ResolvedChatConfig | None:
    """解析 chat 配置。

    chat_source 取值：
    - "global"：全局 chat Key（admin 免授权；非 admin 须有效 grant）
    - "custom-chat:{id}"：用户自配的指定 chat 配置（越权 NotFound）
    - "env"：env 兜底
    - None：内部 fallback（admin→global chat→env；非 admin→grant→global chat→最早 chat 配置→env）
    """
    user = db.get(User, user_id)
    if chat_source is None:
        return _resolve_chat_fallback(db, user=user, user_id=user_id)

    if chat_source == "global":
        if user and user.role == "admin":
            return _build_global_chat_config(db, source="admin")
        grant = _get_active_grant(db, user_id)
        if not grant:
            raise ForbiddenError("未授权使用全局 chat Key，请在设置中添加自定义配置")
        return _build_global_chat_config(db, source="global")

    if chat_source.startswith("custom-chat:"):
        config_id = chat_source[len("custom-chat:"):]
        cfg = _get_chat_config_by_id(db, user_id=user_id, config_id=config_id)
        if cfg is None:
            raise NotFoundError("chat 配置不存在")
        return ResolvedChatConfig(
            base_url=cfg.base_url,
            api_key=decrypt_value(cfg.api_key_encrypted),
            model=cfg.model,
            source="user",
        )

    if chat_source == "env":
        return _build_env_chat_config()

    raise ValidationError(f"无效的 chat_source: {chat_source}")


def _resolve_chat_fallback(db: Session, *, user, user_id) -> ResolvedChatConfig | None:
    if user and user.role == "admin":
        cfg = _build_global_chat_config(db, source="admin")
        if cfg:
            return cfg
        return _build_env_chat_config()
    grant = _get_active_grant(db, user_id)
    if grant:
        cfg = _build_global_chat_config(db, source="global")
        if cfg:
            return cfg
    user_cfg = db.scalar(
        select(UserLLMConfig)
        .where(UserLLMConfig.user_id == user_id)
        .order_by(UserLLMConfig.created_at)
    )
    if user_cfg:
        return ResolvedChatConfig(
            base_url=user_cfg.base_url,
            api_key=decrypt_value(user_cfg.api_key_encrypted),
            model=user_cfg.model,
            source="user",
        )
    return _build_env_chat_config()


def _build_global_chat_config(db: Session, *, source: str) -> ResolvedChatConfig | None:
    enabled_setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if enabled_setting and enabled_setting.value and enabled_setting.value.get("enabled") is False:
        return None
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_chat_config"))
    if cfg and cfg.value and cfg.value.get("api_key_encrypted") and cfg.value.get("model"):
        v = cfg.value
        return ResolvedChatConfig(
            base_url=v.get("base_url", ""),
            api_key=decrypt_value(v["api_key_encrypted"]),
            model=v.get("model", ""),
            source=source,
        )
    return None


def _build_env_chat_config() -> ResolvedChatConfig | None:
    from app.core.config import get_settings
    s = get_settings()
    if s.glm_api_key:
        return ResolvedChatConfig(
            base_url=s.glm_base_url,
            api_key=s.glm_api_key,
            model=s.glm_model,
            source="env",
        )
    return None


def _get_chat_config_by_id(db: Session, *, user_id, config_id) -> UserLLMConfig | None:
    try:
        cid = uuid.UUID(config_id) if isinstance(config_id, str) else config_id
    except (ValueError, AttributeError):
        return None
    cfg = db.get(UserLLMConfig, cid)
    if cfg is None or cfg.user_id != user_id:
        return None
    return cfg


# ── embedding 解析 ──

def resolve_embedding_config(db: Session, *, user_id, embedding_source: str | None = None) -> ResolvedEmbeddingConfig | None:
    """解析 embedding 配置。与 chat 完全独立（fallback 不互通，D4）。

    embedding_source 取值：
    - "global"：全局 embedding Key（admin 免授权；非 admin 须有效 grant）
    - "custom-emb:{id}"：用户自配的指定 embedding 配置（越权 NotFound）
    - "env"：env 兜底
    - None：内部 fallback（admin→global emb→env；非 admin→grant→global emb→最早 emb 配置→env）
    """
    user = db.get(User, user_id)
    if embedding_source is None:
        return _resolve_embedding_fallback(db, user=user, user_id=user_id)

    if embedding_source == "global":
        if user and user.role == "admin":
            return _build_global_embedding_config(db, source="admin")
        grant = _get_active_grant(db, user_id)
        if not grant:
            raise ForbiddenError("未授权使用全局 embedding Key，请在设置中添加自定义配置")
        return _build_global_embedding_config(db, source="global")

    if embedding_source.startswith("custom-emb:"):
        config_id = embedding_source[len("custom-emb:"):]
        cfg = _get_embedding_config_by_id(db, user_id=user_id, config_id=config_id)
        if cfg is None:
            raise NotFoundError("embedding 配置不存在")
        return ResolvedEmbeddingConfig(
            base_url=cfg.base_url,
            api_key=decrypt_value(cfg.api_key_encrypted),
            model=cfg.model,
            source="user",
        )

    if embedding_source == "env":
        return _build_env_embedding_config()

    raise ValidationError(f"无效的 embedding_source: {embedding_source}")


def _resolve_embedding_fallback(db: Session, *, user, user_id) -> ResolvedEmbeddingConfig | None:
    if user and user.role == "admin":
        cfg = _build_global_embedding_config(db, source="admin")
        if cfg:
            return cfg
        return _build_env_embedding_config()
    grant = _get_active_grant(db, user_id)
    if grant:
        cfg = _build_global_embedding_config(db, source="global")
        if cfg:
            return cfg
    emb_cfg = db.scalar(
        select(UserEmbeddingConfig)
        .where(UserEmbeddingConfig.user_id == user_id)
        .order_by(UserEmbeddingConfig.created_at)
    )
    if emb_cfg:
        return ResolvedEmbeddingConfig(
            base_url=emb_cfg.base_url,
            api_key=decrypt_value(emb_cfg.api_key_encrypted),
            model=emb_cfg.model,
            source="user",
        )
    return _build_env_embedding_config()


def _build_global_embedding_config(db: Session, *, source: str) -> ResolvedEmbeddingConfig | None:
    enabled_setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if enabled_setting and enabled_setting.value and enabled_setting.value.get("enabled") is False:
        return None
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_embedding_config"))
    if cfg and cfg.value and cfg.value.get("api_key_encrypted") and cfg.value.get("model"):
        v = cfg.value
        return ResolvedEmbeddingConfig(
            base_url=v.get("base_url", ""),
            api_key=decrypt_value(v["api_key_encrypted"]),
            model=v.get("model", ""),
            source=source,
        )
    return None


def _build_env_embedding_config() -> ResolvedEmbeddingConfig | None:
    from app.core.config import get_settings
    s = get_settings()
    if s.glm_api_key and s.glm_embedding_model:
        return ResolvedEmbeddingConfig(
            base_url=s.glm_base_url,
            api_key=s.glm_api_key,
            model=s.glm_embedding_model,
            source="env",
        )
    return None


def _get_embedding_config_by_id(db: Session, *, user_id, config_id) -> UserEmbeddingConfig | None:
    try:
        cid = uuid.UUID(config_id) if isinstance(config_id, str) else config_id
    except (ValueError, AttributeError):
        return None
    cfg = db.get(UserEmbeddingConfig, cid)
    if cfg is None or cfg.user_id != user_id:
        return None
    return cfg


def _get_active_grant(db: Session, user_id):
    """共享辅助：查有效 grant（chat 与 embedding 共用一个 grant，D5）。"""
    return db.scalar(select(UserGlobalLLMGrant).where(
        (UserGlobalLLMGrant.user_id == user_id) &
        (UserGlobalLLMGrant.revoked_at.is_(None))
    ))


# ── embedding 配置 CRUD（镜像 chat）──

def list_user_embedding_configs(db: Session, *, user_id) -> list[dict]:
    cfgs = db.scalars(
        select(UserEmbeddingConfig)
        .where(UserEmbeddingConfig.user_id == user_id)
        .order_by(UserEmbeddingConfig.created_at)
    ).all()
    return [embedding_config_to_dict(c) for c in cfgs]


def create_user_embedding_config(
    db: Session, *, user_id, name: str, base_url: str,
    api_key: str, model: str,
) -> UserEmbeddingConfig:
    cfg = UserEmbeddingConfig(
        user_id=user_id, name=name, base_url=base_url,
        api_key_encrypted=encrypt_value(api_key), model=model,
    )
    db.add(cfg); db.commit(); db.refresh(cfg)
    return cfg


def update_user_embedding_config(
    db: Session, *, user_id, config_id, name: str | None = None,
    base_url: str | None = None, api_key: str | None = None, model: str | None = None,
) -> UserEmbeddingConfig:
    cfg = _get_owned_embedding_config(db, user_id=user_id, config_id=config_id)
    if name is not None:
        cfg.name = name
    if base_url is not None:
        cfg.base_url = base_url
    if api_key is not None:
        cfg.api_key_encrypted = encrypt_value(api_key)
    if model is not None:
        cfg.model = model
    db.commit(); db.refresh(cfg)
    return cfg


def delete_user_embedding_config(db: Session, *, user_id, config_id) -> None:
    cfg = _get_owned_embedding_config(db, user_id=user_id, config_id=config_id)
    db.delete(cfg); db.commit()


def _get_owned_embedding_config(db: Session, *, user_id, config_id) -> UserEmbeddingConfig:
    try:
        cid = uuid.UUID(config_id) if isinstance(config_id, str) else config_id
    except (ValueError, AttributeError):
        raise NotFoundError("embedding 配置不存在")
    cfg = db.get(UserEmbeddingConfig, cid)
    if cfg is None or cfg.user_id != user_id:
        raise NotFoundError("embedding 配置不存在")
    return cfg


def embedding_config_to_dict(cfg: UserEmbeddingConfig) -> dict:
    return {
        "id": str(cfg.id),
        "name": cfg.name,
        "base_url": cfg.base_url,
        "api_key_masked": _mask_key(decrypt_value(cfg.api_key_encrypted)),
        "model": cfg.model,
    }


# ── 全局 chat / embedding 配置（拆两套 SystemSetting key）──

def get_global_chat_settings(db: Session) -> dict:
    enabled = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_chat_config"))
    return {
        "base_url": cfg.value.get("base_url", "") if cfg else "",
        "api_key_masked": _mask_key(decrypt_value(cfg.value["api_key_encrypted"])) if cfg and cfg.value.get("api_key_encrypted") else "",
        "model": cfg.value.get("model", "") if cfg else "",
    }


def set_global_chat_settings(
    db: Session, *, enabled: bool, base_url: str | None = None,
    api_key: str | None = None, model: str | None = None,
) -> dict:
    """注意：enabled 开关是 chat+embedding 共用的（llm_global_enabled）。本函数也写它。"""
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if setting:
        setting.value = {"enabled": enabled}
    else:
        db.add(SystemSetting(key="llm_global_enabled", value={"enabled": enabled}))

    if base_url or api_key or model:
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_chat_config"))
        current = cfg.value if cfg else {}
        new_value = {
            "base_url": base_url or current.get("base_url", ""),
            "model": model or current.get("model", ""),
        }
        if api_key:
            new_value["api_key_encrypted"] = encrypt_value(api_key)
        elif current.get("api_key_encrypted"):
            new_value["api_key_encrypted"] = current["api_key_encrypted"]
        if cfg:
            cfg.value = new_value
        else:
            db.add(SystemSetting(key="llm_global_chat_config", value=new_value))
    db.commit()
    return get_global_chat_settings(db)


def get_global_embedding_settings(db: Session) -> dict:
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_embedding_config"))
    return {
        "base_url": cfg.value.get("base_url", "") if cfg else "",
        "api_key_masked": _mask_key(decrypt_value(cfg.value["api_key_encrypted"])) if cfg and cfg.value.get("api_key_encrypted") else "",
        "model": cfg.value.get("model", "") if cfg else "",
    }


def set_global_embedding_settings(
    db: Session, *, enabled: bool, base_url: str | None = None,
    api_key: str | None = None, model: str | None = None,
) -> dict:
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if setting:
        setting.value = {"enabled": enabled}
    else:
        db.add(SystemSetting(key="llm_global_enabled", value={"enabled": enabled}))

    if base_url or api_key or model:
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_embedding_config"))
        current = cfg.value if cfg else {}
        new_value = {
            "base_url": base_url or current.get("base_url", ""),
            "model": model or current.get("model", ""),
        }
        if api_key:
            new_value["api_key_encrypted"] = encrypt_value(api_key)
        elif current.get("api_key_encrypted"):
            new_value["api_key_encrypted"] = current["api_key_encrypted"]
        if cfg:
            cfg.value = new_value
        else:
            db.add(SystemSetting(key="llm_global_embedding_config", value=new_value))
    db.commit()
    return get_global_embedding_settings(db)
```

> 注：`set_global_chat_settings`/`set_global_embedding_settings` 都写 `llm_global_enabled`（共用开关，D5）。重复写同一个 key 是幂等的（值相同）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_chat_embedding_resolution.py -v`
Expected: PASS（全部新测试）。

- [ ] **Step 5: 跑全量回归（老的还在，应不破坏）**

Run: `cd apps/api && uv run pytest -q`
Expected: Task 2 遗留的 embedding_model 相关 failures 仍在（预期），新增的不引入新 failure。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/services/llm_config_service.py tests/test_chat_embedding_resolution.py
git commit -m "feat(llm): 新增 chat/embedding 独立 resolve + CRUD + global settings（与老的并存）"
```

---

## Task 4: 改造内部 chat caller（review/summary/conversation）用 resolve_chat_config

**Files:**
- Modify: `apps/api/app/services/review_service.py`
- Modify: `apps/api/app/services/summary_service.py`
- Modify: `apps/api/app/services/conversation_service.py`
- Test: `apps/api/tests/test_internal_callers_switched.py`（部分）

- [ ] **Step 1: 写失败测试（chat caller 切到 resolve_chat_config）**

Create `apps/api/tests/test_internal_callers_switched.py`:

```python
"""确认内部 caller 调用了正确的 resolve 函数（chat caller → resolve_chat_config）。"""

from unittest.mock import patch, MagicMock


def test_review_service_calls_resolve_chat_config(db_session):
    """review_service.run_review 应调 resolve_chat_config（不是 resolve_llm_config）。"""
    from app.services import review_service
    fake_cfg = MagicMock()
    fake_cfg.model = "glm-4"
    with patch("app.services.review_service.resolve_chat_config", return_value=fake_cfg) as m, \
         patch("app.services.review_service.get_llm") as m_llm, \
         patch("app.services.review_service.get_effective_rubric"), \
         patch("app.services.review_service._get_section_texts", return_value={}), \
         patch("app.services.review_service._get_last_review"):
        m_llm.return_value.invoke.return_value = MagicMock(content='{"score":5,"reason":"r","evidence":"e"}')
        # 需要 project + user；构造最小
        from app.models import User, Project
        import uuid
        u = User(username="rv", password_hash="x", name="R")
        db_session.add(u); db_session.commit(); db_session.refresh(u)
        p = Project(id=uuid.uuid4(), user_id=u.id, title="t")
        db_session.add(p); db_session.commit()
        try:
            review_service.run_review(db_session, user_id=u.id, project_id=str(p.id))
        except Exception:
            pass  # 只关心 resolve 被调对
    m.assert_called()


def test_summary_service_calls_resolve_chat_config(db_session):
    from app.services import summary_service
    from app.models import Section, Project
    import uuid
    fake_cfg = MagicMock()
    with patch("app.services.summary_service.resolve_chat_config", return_value=fake_cfg) as m:
        # 构造 section；summary 内部 try/except，失败也走 fallback
        u_proj = Project(id=uuid.uuid4(), user_id=uuid.uuid4(), title="t")
        db_session.add(u_proj); db_session.commit()
        s = Section(id=uuid.uuid4(), project_id=u_proj.id, title="t", content="内容", section_key="k")
        db_session.add(s); db_session.commit()
        summary_service.generate_summary(db_session, s)
    m.assert_called()
```

> 注：`Section`/`Project` 的必填字段以实际模型为准——实施时若构造报错，按模型补字段。这俩测试主要验证"调了 resolve_chat_config"。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_internal_callers_switched.py -v`
Expected: FAIL（caller 还调 resolve_llm_config，patch 的 resolve_chat_config 没被调）。

- [ ] **Step 3: 改 review_service.py**

Modify `apps/api/app/services/review_service.py`:
- Line 18 改 import：`from app.services.llm_config_service import ResolvedLLMConfig, resolve_llm_config` → `from app.services.llm_config_service import ResolvedChatConfig, resolve_chat_config`
- Line 45 改调用：`llm_config = resolve_llm_config(db, user_id=user_id)` → `llm_config = resolve_chat_config(db, user_id=user_id)`
- Line 110-111 改类型注解：`def _score_dimension(criterion: dict, sections: dict[str, str], llm_config: ResolvedLLMConfig)` → `... llm_config: ResolvedChatConfig)`
- grep 文件内其它 `ResolvedLLMConfig`/`resolve_llm_config` 残留，全改成 chat 版。

- [ ] **Step 4: 改 summary_service.py**

Modify `apps/api/app/services/summary_service.py`:
- Line 26 import 改：`from app.services.llm_config_service import resolve_llm_config` → `from app.services.llm_config_service import resolve_chat_config`
- Line 33 调用改：`llm_config = resolve_llm_config(db, user_id=project.user_id)` → `llm_config = resolve_chat_config(db, user_id=project.user_id)`

- [ ] **Step 5: 改 conversation_service.py（类型注解）**

Modify `apps/api/app/services/conversation_service.py`:
- Line 7 import 改：`from app.services.llm_config_service import ResolvedLLMConfig` → `from app.services.llm_config_service import ResolvedChatConfig`
- Line 15 类型注解改：`llm_config: ResolvedLLMConfig | None = None` → `llm_config: ResolvedChatConfig | None = None`
- docstring 里的 `resolve_llm_config` 引用改成 `resolve_chat_config`。

- [ ] **Step 6: 跑测试确认通过 + 回归**

Run: `cd apps/api && uv run pytest tests/test_internal_callers_switched.py tests/test_conversation_title.py tests/test_review*.py tests/test_summary*.py -v`（若 review/summary 没专门测试文件，跳过）。
Expected: 通过。

Run: `cd apps/api && uv run pytest -q`
Expected: 不引入新 failure（Task 2 的 embedding_model failure 仍在预期）。

- [ ] **Step 7: 提交**

```bash
cd apps/api && git add app/services/review_service.py app/services/summary_service.py app/services/conversation_service.py tests/test_internal_callers_switched.py
git commit -m "refactor(llm): 内部 chat caller 切到 resolve_chat_config（review/summary/conversation）"
```

---

## Task 5: 改造内部 embedding caller（archiver/retriever/knowledge）用 resolve_embedding_config

**Files:**
- Modify: `apps/api/app/rag/embedding.py`
- Modify: `apps/api/app/rag/archiver.py`
- Modify: `apps/api/app/rag/retriever.py`
- Modify: `apps/api/app/services/knowledge_service.py`
- Test: `apps/api/tests/test_internal_callers_switched.py`（追加）

- [ ] **Step 1: 追加失败测试**

Append to `apps/api/tests/test_internal_callers_switched.py`:

```python
def test_archiver_calls_resolve_embedding_config(db_session):
    """archiver.archive_project 应调 resolve_embedding_config。"""
    from app.rag import archiver
    with patch("app.rag.archiver.resolve_embedding_config", return_value=None) as m:
        from app.models import Project
        import uuid
        p = Project(id=uuid.uuid4(), user_id=uuid.uuid4(), title="t")
        db_session.add(p); db_session.commit()
        archiver.archive_project(db_session, project=p, user_id=p.user_id)
    m.assert_called()


def test_retriever_calls_resolve_embedding_config(db_session):
    from app.rag import retriever
    with patch("app.rag.retriever.resolve_embedding_config", return_value=None) as m:
        retriever.retrieve(db_session, user_id="00000000-0000-0000-0000-000000000000", query="q")
    m.assert_called()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_internal_callers_switched.py -v -k archiver or retriever`
Expected: FAIL。

- [ ] **Step 3: 改 embedding.py（get_embedder 收 ResolvedEmbeddingConfig）**

Modify `apps/api/app/rag/embedding.py` — 全文替换为:

```python
"""Embedding 封装。用 LangChain OpenAIEmbeddings（OpenAI 兼容协议）。"""

from langchain_openai import OpenAIEmbeddings

from app.services.llm_config_service import ResolvedEmbeddingConfig


def get_embedder(embed_config: ResolvedEmbeddingConfig) -> OpenAIEmbeddings:
    """构造 embedder。用解析后的 embedding 配置（与 chat 独立）。

    embed_config 由 resolve_embedding_config 产出，model 已保证非空（resolve 的 build 分支都校验过）。
    """
    if not embed_config.model:
        raise ValueError("embedding 配置缺少 model")
    return OpenAIEmbeddings(
        model=embed_config.model,
        base_url=embed_config.base_url,
        api_key=embed_config.api_key,
    )


def embed_text(text: str, *, embed_config: ResolvedEmbeddingConfig) -> list[float]:
    """单文本向量化。"""
    return get_embedder(embed_config).embed_query(text)


def embed_texts(texts: list[str], *, embed_config: ResolvedEmbeddingConfig) -> list[list[float]]:
    """批量向量化。"""
    return get_embedder(embed_config).embed_documents(texts)
```

- [ ] **Step 4: 改 archiver.py**

Modify `apps/api/app/rag/archiver.py`:
- Line 11 import 改：`from app.services.llm_config_service import resolve_llm_config` → `from app.services.llm_config_service import resolve_embedding_config`
- Line 16 改：`embed_config = resolve_llm_config(db, user_id=user_id)` → `embed_config = resolve_embedding_config(db, user_id=user_id)`
- 错误信息（若有）改成 embedding 语义。

- [ ] **Step 5: 改 retriever.py**

Modify `apps/api/app/rag/retriever.py`:
- Line 10 import 改：`from app.services.llm_config_service import resolve_llm_config` → `from app.services.llm_config_service import resolve_embedding_config`
- Line 27 改：`embed_config = resolve_llm_config(db, user_id=user_id)` → `embed_config = resolve_embedding_config(db, user_id=user_id)`

- [ ] **Step 6: 改 knowledge_service.py**

Modify `apps/api/app/services/knowledge_service.py`:
- import（约 line 25）改：`resolve_llm_config` → `resolve_embedding_config`
- Line 252 改：`embed_config = resolve_llm_config(db, user_id=user_id)` → `embed_config = resolve_embedding_config(db, user_id=user_id)`

- [ ] **Step 7: 跑测试 + 回归**

Run: `cd apps/api && uv run pytest tests/test_internal_callers_switched.py -v`
Expected: 全通过。

Run: `cd apps/api && uv run pytest -q`
Expected: 不引入新 failure。

- [ ] **Step 8: 提交**

```bash
cd apps/api && git add app/rag/embedding.py app/rag/archiver.py app/rag/retriever.py app/services/knowledge_service.py tests/test_internal_callers_switched.py
git commit -m "refactor(rag): 内部 embedding caller 切到 resolve_embedding_config（archiver/retriever/knowledge）"
```

---

## Task 6: 改造 AI 端点用 chat_source + resolve_chat_config

**Files:**
- Modify: `apps/api/app/schemas/ai.py`
- Modify: `apps/api/app/api/ai.py`（4 端点 + CaptionRequest）
- Test: `apps/api/tests/test_ai_endpoints_chat_source.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_ai_endpoints_chat_source.py`:

```python
"""AI 端点接受 chat_source（不再是 source）。"""

from unittest.mock import patch, MagicMock


def _login(client, db_session):
    from app.core.security import hash_password
    from app.models import User
    u = User(username="aiu", email="aiu@example.com", password_hash=hash_password("P1!"), name="A")
    db_session.add(u); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "aiu", "password": "P1!"})
    return u


def test_chat_endpoint_accepts_chat_source(client, db_session):
    """POST /sections/{id}/chat 接受 chat_source 字段。"""
    _login(client, db_session)
    # 构造 section
    from app.models import Project, Section
    import uuid
    p = Project(id=uuid.uuid4(), user_id=db_session.query(db_session.bind.dialect.name).first() and uuid.uuid4(), title="t")
    # 简化：用注册用户建 project + section
    # ...（实施时补完整构造）
    fake_cfg = MagicMock()
    fake_cfg.model = "glm-4"; fake_cfg.source = "user"
    with patch("app.api.ai.llm_config_service.resolve_chat_config", return_value=fake_cfg):
        # 发 chat 请求带 chat_source
        res = client.post(f"/api/v1/sections/{uuid.uuid4()}/chat", json={"message": "hi", "chat_source": "env"})
    # 主要验证：不因字段名 source 报 422（chat_source 被接受）
    assert res.status_code != 422
```

> 注：构造完整 project+section 较繁，这测试主要验证 schema 接受 `chat_source`。实施时若端点需要真实 section，补 fixture；或简化为只测 schema：`from app.schemas.ai import ChatRequest; ChatRequest(message="hi", chat_source="env")` 不报错。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_ai_endpoints_chat_source.py -v`
Expected: FAIL（schema 还叫 source）。

- [ ] **Step 3: 改 schemas/ai.py**

Modify `apps/api/app/schemas/ai.py` — 把所有 `source: str | None = None` 改成 `chat_source: str | None = None`:

```python
class ChatRequest(BaseModel):
    message: str
    chat_source: str | None = None  # "global" / "custom-chat:{id}" / "env"；None 走 fallback
    conversation_id: str | None = None


class GenerateRequest(BaseModel):
    chat_source: str | None = None


class RewriteRequest(BaseModel):
    selected_text: str
    instruction: str = "重写这段内容，使其更清晰规范"
    chat_source: str | None = None
```

- [ ] **Step 4: 改 ai.py 的 4 端点 + CaptionRequest**

Modify `apps/api/app/api/ai.py`:
- `CaptionRequest`（line 576-578）：`source: str | None = None` → `chat_source: str | None = None`
- 4 端点的 resolve 调用：
  - Line 204：`resolve_llm_config(db, user_id=current_user.id, source=payload.source)` → `resolve_chat_config(db, user_id=current_user.id, chat_source=payload.chat_source)`
  - Line 300：`resolve_llm_config(db, user_id=current_user.id, source=source)` 其中 `source = payload.source if payload else None` → 改 `chat_source = payload.chat_source if payload else None`，resolve 调用 `resolve_chat_config(db, user_id=current_user.id, chat_source=chat_source)`
  - Line 382：`source=payload.source` → `chat_source=payload.chat_source`
  - Line 601：`source=payload.source` → `chat_source=payload.chat_source`
- import 改：`resolve_llm_config` → `resolve_chat_config`（grep ai.py 的 import 行，line 附近）。
- 凡是变量名 `source` 改成 `chat_source`（仅这 4 端点相关；日志用的 `_resolve_provider`/`_effective_model` 读 `llm_config.model`/`.source` 不变——`ResolvedChatConfig` 仍有 `.source` 字段）。

- [ ] **Step 5: 跑测试 + 回归**

Run: `cd apps/api && uv run pytest tests/test_ai_endpoints_chat_source.py tests/test_ai.py -v`
Expected: 通过。`test_ai.py` 若用到 `source` 字段需同步改 `chat_source`（grep `source=` 在 test_ai.py）。

Run: `cd apps/api && uv run pytest -q`
Expected: 不引入新 failure。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/schemas/ai.py app/api/ai.py tests/test_ai_endpoints_chat_source.py tests/test_ai.py
git commit -m "refactor(api): AI 端点用 chat_source + resolve_chat_config（4 端点 + CaptionRequest）"
```

---

## Task 7: 改 get_llm 收 ResolvedChatConfig

**Files:**
- Modify: `apps/api/app/ai/llm_client.py`
- Test: `apps/api/tests/test_llm.py`（已有，改类型）

- [ ] **Step 1: 改 llm_client.py**

Modify `apps/api/app/ai/llm_client.py`:
- Line 8 import 改：`from app.services.llm_config_service import ResolvedLLMConfig` → `from app.services.llm_config_service import ResolvedChatConfig`
- Line 11 签名改：`def get_llm(llm_config: ResolvedLLMConfig, ...)` → `def get_llm(llm_config: ResolvedChatConfig, ...)`
- Line 27、Line 36 同理改 `ResolvedLLMConfig` → `ResolvedChatConfig`。

- [ ] **Step 2: 改 test_llm.py 的类型**

Modify `apps/api/tests/test_llm.py` — 把 `ResolvedLLMConfig(` 改成 `ResolvedChatConfig(`，import 改 `from app.services.llm_config_service import ResolvedChatConfig`。这些测试构造的 cfg 本来就只用 chat 字段（model/base_url/api_key），去掉 `embedding_model=` kwarg（ResolvedChatConfig 没这字段）。

- [ ] **Step 3: 跑测试**

Run: `cd apps/api && uv run pytest tests/test_llm.py -v`
Expected: PASS。

- [ ] **Step 4: 提交**

```bash
cd apps/api && git add app/ai/llm_client.py tests/test_llm.py
git commit -m "refactor(ai): get_llm 收 ResolvedChatConfig"
```

---

## Task 8: 删除老的 ResolvedLLMConfig / resolve_llm_config / 耦合 CRUD / allowed_models

**Files:**
- Modify: `apps/api/app/services/llm_config_service.py`（删老块）
- Modify: `apps/api/app/api/settings.py`（chat 端点去 embedding_model）
- Modify: `apps/api/app/api/admin/console.py`（拆两套 + 删 allowed_models，见 Task 9-10）
- Test: 改造现有耦合测试

> 这是"删老"任务。前面 Task 3-7 已把所有 caller 切到新函数。现在 grep 确认无人用老的，然后删。

- [ ] **Step 1: grep 确认老的无人用**

Run: `cd apps/api && grep -rn "resolve_llm_config\|ResolvedLLMConfig" app/`
Expected: 只剩 `llm_config_service.py` 里的定义（应该没人调了）。若有残留 caller，先改掉再继续。

- [ ] **Step 2: 删 llm_config_service.py 的老块**

Modify `apps/api/app/services/llm_config_service.py` — 删除：
- `ResolvedLLMConfig` dataclass（lines 27-34）
- `resolve_llm_config`（lines 37-85）
- `_resolve_fallback`（lines 88-129）
- `_build_global_config`（lines 132-158）
- `_build_env_config`（lines 161-173）
- `create_user_llm_config`/`update_user_llm_config` 里的 `embedding_model` 参数（删参数 + 函数体里 `embedding_model=embedding_model`）
- `config_to_dict` 里的 `"embedding_model": cfg.embedding_model,` 行
- `get_global_llm_settings`（老的，读 `llm_global_config`）—— 整个删（Task 9-10 admin 端点改用新 `get_global_chat_settings`/`get_global_embedding_settings`）
- `set_global_llm_settings`（老的）—— 整个删
- 保留：`_get_user_config_by_id`/`_get_owned_config`（chat 用）、`list_user_llm_configs`/`create_user_llm_config`/`update_user_llm_config`/`delete_user_llm_config`/`config_to_dict`（去 embedding_model）、`_mask_key`、`list_provider_models`、`test_llm_connection`、以及 Task 3 新增的全套。

> `test_llm_connection` 现在签名带 `embedding_model` 参数——它是"测试连通性"的通用函数，chat 端点测 chat、embedding 端点测 embedding。**保留它的 embedding_model 参数**（embedding test 端点会传）。只是 chat test 端点不传 embedding_model（只测 chat）。

- [ ] **Step 3: 改 settings.py chat 端点去 embedding_model**

Modify `apps/api/app/api/settings.py`:
- `UserLLMCreateRequest`：删 `embedding_model: str | None = None` 字段
- `UserLLMUpdateRequest`：删 `embedding_model: str | None = None`
- `UserLLMTestRequest`：删 `embedding_model`（chat test 只测 chat）
- `create_my_llm`/`update_my_llm` 调用 service 时去掉 `embedding_model=` 参数
- `test_my_llm` 调用 `test_llm_connection` 时不传 `embedding_model`（只测 chat）

- [ ] **Step 4: 改造耦合测试**

- `test_global_llm_config.py`：老的 set_global_llm_settings/get_global_llm_settings 测试改成 set_global_chat_settings/get_global_chat_settings + set_global_embedding_settings。把 `embedding_model` 断言移到 embedding 测试。
- `test_llm_config_endpoints.py`：chat 端点测试去掉 embedding_model 字段；test 端点响应断言去掉 embedding 子对象（chat test 只返 chat）。
- `test_custom_key_crud_api.py`：CRUD 测试去掉 embedding_model（Task 2 已部分改）。
- grep `embedding_model` in tests/ 全过一遍。

- [ ] **Step 5: 跑全量回归**

Run: `cd apps/api && uv run pytest -q`
Expected: **全绿**（老的删了，所有 caller 切完了，耦合测试也改了）。Task 2 的预期 failure 应全部消除。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/services/llm_config_service.py app/api/settings.py tests/
git commit -m "refactor(llm): 删除老的 ResolvedLLMConfig/resolve_llm_config/耦合 CRUD；chat 端点去 embedding_model"
```

---

## Task 9: 用户侧 embedding 端点（/settings/embedding/*）

**Files:**
- Modify: `apps/api/app/api/settings.py`
- Test: `apps/api/tests/test_embedding_config_endpoints.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_embedding_config_endpoints.py`（镜像 test_llm_config_endpoints.py 的结构）:

```python
"""/settings/embedding/* 端点测试。镜像 chat 端点（test_llm_config_endpoints.py）。"""

from unittest.mock import patch
from app.core.security import hash_password
from app.models import User


def _login_user(client, db_session):
    u = User(username="eu", email="eu@example.com", password_hash=hash_password("P1!"), name="E")
    db_session.add(u); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "eu", "password": "P1!"})
    return u


def test_list_embedding_configs_empty(client, db_session):
    _login_user(client, db_session)
    res = client.get("/api/v1/settings/embedding")
    assert res.status_code == 200
    assert res.json() == []


def test_create_embedding_config(client, db_session):
    uid = _login_user(client, db_session)["id"] if False else None  # 用 fixture 风格
    u = _login_user(client, db_session)
    res = client.post("/api/v1/settings/embedding", json={
        "name": "智谱 emb", "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "sk-emb-1234567890", "model": "embedding-3",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "智谱 emb"
    assert data["model"] == "embedding-3"
    assert "api_key_masked" in data
    assert data["api_key_masked"].startswith("sk-")


def test_update_embedding_config(client, db_session):
    u = _login_user(client, db_session)
    create_res = client.post("/api/v1/settings/embedding", json={
        "name": "n", "base_url": "u", "api_key": "sk-1234567890", "model": "m",
    })
    cid = create_res.json()["id"]
    res = client.put(f"/api/v1/settings/embedding/{cid}", json={"model": "new-model"})
    assert res.status_code == 200
    assert res.json()["model"] == "new-model"


def test_delete_embedding_config(client, db_session):
    u = _login_user(client, db_session)
    create_res = client.post("/api/v1/settings/embedding", json={
        "name": "n", "base_url": "u", "api_key": "sk-1234567890", "model": "m",
    })
    cid = create_res.json()["id"]
    res = client.delete(f"/api/v1/settings/embedding/{cid}")
    assert res.status_code == 200


def test_embedding_test_endpoint(client, db_session):
    u = _login_user(client, db_session)
    with patch("app.api.settings.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": None,
                          "embedding": {"ok": True, "latency_ms": 50, "dim": 1024, "error": None},
                          "error": None}
        res = client.post("/api/v1/settings/embedding/test", json={
            "base_url": "https://x.com/v1", "api_key": "sk", "model": "emb",
        })
    assert res.status_code == 200
    assert res.json()["embedding"]["dim"] == 1024


def test_embedding_models_endpoint(client, db_session):
    u = _login_user(client, db_session)
    with patch("app.api.settings.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["emb-1"], "truncated": False, "error": None}
        res = client.post("/api/v1/settings/embedding/models", json={
            "base_url": "https://x.com/v1", "api_key": "sk",
        })
    assert res.status_code == 200
    assert res.json()["models"] == ["emb-1"]


def test_embedding_endpoints_require_auth(client):
    assert client.get("/api/v1/settings/embedding").status_code in (401, 403)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_embedding_config_endpoints.py -v`
Expected: FAIL（404，端点不存在）。

- [ ] **Step 3: 加端点到 settings.py**

Modify `apps/api/app/api/settings.py` — 追加 embedding schemas + 路由（镜像 chat 的，但操作 UserEmbeddingConfig）:

```python
class EmbeddingConfigCreateRequest(BaseModel):
    name: str
    base_url: str
    api_key: str
    model: str = Field(..., min_length=1)


class EmbeddingConfigUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class EmbeddingTestRequest(BaseModel):
    base_url: str
    api_key: str
    model: str = Field(..., min_length=1)


@router.get("/settings/embedding")
def list_my_embedding_configs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return llm_config_service.list_user_embedding_configs(db, user_id=current_user.id)


@router.post("/settings/embedding")
def create_my_embedding_config(payload: EmbeddingConfigCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = llm_config_service.create_user_embedding_config(
        db, user_id=current_user.id, name=payload.name, base_url=payload.base_url,
        api_key=payload.api_key, model=payload.model,
    )
    return llm_config_service.embedding_config_to_dict(cfg)


@router.put("/settings/embedding/{config_id}")
def update_my_embedding_config(config_id: str, payload: EmbeddingConfigUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = llm_config_service.update_user_embedding_config(
        db, user_id=current_user.id, config_id=config_id,
        name=payload.name, base_url=payload.base_url, api_key=payload.api_key, model=payload.model,
    )
    return llm_config_service.embedding_config_to_dict(cfg)


@router.delete("/settings/embedding/{config_id}")
def delete_my_embedding_config(config_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    llm_config_service.delete_user_embedding_config(db, user_id=current_user.id, config_id=config_id)
    return {"message": "已删除"}


@router.post("/settings/embedding/test")
def test_my_embedding_config(payload: EmbeddingTestRequest, current_user: User = Depends(get_current_user)):
    # 测 embedding：调 test_llm_connection 时传 embedding_model，不传 chat 的 model？
    # test_llm_connection 同时测 chat + embedding——embedding 端点只想测 embedding。
    # 解法：调时 model 留空跳过 chat（但 model 是必填 min_length=1）。
    # 改为：直接测 embedding（不调 test_llm_connection，或加个只测 embedding 的路径）。
    # 见 Step 3b 的调整。
    ...
```

- [ ] **Step 3b: 调整——embedding test 只测 embedding（给 test_llm_connection 加 scope 参数）**

`test_llm_connection` 当前 chat 必测、embedding 可选（传 embedding_model 才测）。但 chat test 端点要"只测 chat"、embedding test 端点要"只测 embedding"。给 `test_llm_connection` 加一个显式 `scope` 参数控制测什么。

Modify `apps/api/app/services/llm_config_service.py` 的 `test_llm_connection`（约 line 430-498），把签名和逻辑改成:

```python
def test_llm_connection(
    db: Session | None = None, *,
    base_url: str,
    api_key: str,
    model: str,
    embedding_model: str | None = None,
    scope: str = "all",  # "all"（chat+embedding，需 embedding_model）/ "chat"（只 chat）/ "embedding"（只 embedding）
) -> dict:
    """测试 LLM 连通性。scope 控制测什么。
    - "all"：chat 必测；embedding_model 提供则一并测。
    - "chat"：只测 chat（忽略 embedding_model）。
    - "embedding"：只测 embedding（model 参数当 embedding 模型名用）。
    """
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from app.ai.llm_errors import friendly_llm_error

    # ---- chat（scope=all 或 chat 时测）----
    chat = None
    if scope in ("all", "chat"):
        chat = {"ok": False, "latency_ms": None, "sample": None, "error": None}
        try:
            llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, request_timeout=_TEST_TIMEOUT)
            t0 = time.perf_counter()
            resp = llm.invoke([HumanMessage(content="hi")])
            chat["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            chat["ok"] = True
            chat["sample"] = (resp.content or "")[:50]
        except Exception as e:
            chat["error"] = friendly_llm_error(e)

    # ---- embedding（scope=all 且 embedding_model 非空，或 scope=embedding 时测）----
    embedding = None
    emb_model = embedding_model if scope != "embedding" else model  # embedding scope 下 model 即 emb 模型名
    if scope == "embedding" or (scope == "all" and emb_model):
        embedding = {"ok": False, "latency_ms": None, "dim": None, "error": None}
        try:
            emb = OpenAIEmbeddings(model=emb_model, base_url=base_url, api_key=api_key, request_timeout=_TEST_TIMEOUT)
            t0 = time.perf_counter()
            vec = emb.embed_query("hi")
            embedding["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            embedding["ok"] = True
            embedding["dim"] = len(vec) if vec else None
        except Exception as e:
            embedding["error"] = friendly_llm_error(e)

    # ok：只看实际测了的部分
    tested = [x for x in (chat, embedding) if x is not None]
    ok = all(x["ok"] for x in tested) if tested else False
    first_err = next((x["error"] for x in tested if x["error"]), None)
    return {"ok": ok, "chat": chat, "embedding": embedding, "error": None if ok else first_err}
```

> 旧行为（scope 默认 "all"）保持向后兼容：chat test 端点调时不传 scope（默认 all）但只传 model 不传 embedding_model → 只测 chat（embedding 分支条件 `scope=="all" and emb_model` 不满足）。但为了清晰，chat test 端点显式传 `scope="chat"`。embedding test 端点传 `scope="embedding"`。

然后两个 test 端点的调用:
- chat test（settings.py 的 `test_my_llm`）：`test_llm_connection(base_url=..., api_key=..., model=payload.model, scope="chat")`
- embedding test（Task 9 新增的 `test_my_embedding_config`）：`test_llm_connection(base_url=..., api_key=..., model=payload.model, scope="embedding")`

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_embedding_config_endpoints.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/api/settings.py app/services/llm_config_service.py tests/test_embedding_config_endpoints.py
git commit -m "feat(api): 用户侧 embedding 端点 /settings/embedding/*（镜像 chat）+ test_llm_connection 加 scope"
```

---

## Task 10: admin 全局端点拆两套 + 删 allowed_models

**Files:**
- Modify: `apps/api/app/api/admin/console.py`
- Test: `apps/api/tests/test_admin_split_endpoints.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_admin_split_endpoints.py`:

```python
"""admin 全局 LLM 配置拆 chat/embedding 两套 + 删 allowed_models。"""

from unittest.mock import patch
from app.core.security import hash_password, encrypt_value
from app.models import User, SystemSetting


def _login_admin(client, db_session):
    a = User(username="adm", email="adm@example.com", password_hash=hash_password("A1!"), name="A", role="admin", status="active")
    db_session.add(a); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "adm", "password": "A1!"})
    return a


def test_get_global_returns_chat_and_embedding(client, db_session):
    _login_admin(client, db_session)
    res = client.get("/api/v1/admin/llm-config")
    assert res.status_code == 200
    data = res.json()
    assert "chat_config" in data
    assert "embedding_config" in data
    assert "allowed_models" not in str(data)  # 删除


def test_put_global_chat_and_embedding(client, db_session):
    _login_admin(client, db_session)
    res = client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "chat_config": {"base_url": "https://chat.com", "api_key": "sk-c-1234567890", "model": "cm"},
        "embedding_config": {"base_url": "https://emb.com", "api_key": "sk-e-1234567890", "model": "em"},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["chat_config"]["model"] == "cm"
    assert data["embedding_config"]["model"] == "em"


def test_admin_chat_test_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": {"ok": True, "latency_ms": 10, "sample": "hi", "error": None}, "embedding": None, "error": None}
        res = client.post("/api/v1/admin/llm-config/chat/test", json={"base_url": "u", "api_key": "k", "model": "m"})
    assert res.status_code == 200


def test_admin_embedding_test_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": None, "embedding": {"ok": True, "latency_ms": 5, "dim": 128, "error": None}, "error": None}
        res = client.post("/api/v1/admin/llm-config/embedding/test", json={"base_url": "u", "api_key": "k", "model": "m"})
    assert res.status_code == 200


def test_old_admin_test_endpoint_removed(client, db_session):
    """老的 /admin/llm-config/test 应删除（404）。"""
    _login_admin(client, db_session)
    res = client.post("/api/v1/admin/llm-config/test", json={})
    assert res.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_admin_split_endpoints.py -v`
Expected: FAIL。

- [ ] **Step 3: 改 console.py**

Modify `apps/api/app/api/admin/console.py`:
- 删老 `GlobalLLMSettings`/`GlobalLLMTestRequest` schema（含 allowed_models）
- 新增 schemas:
```python
class GlobalChatConfigBody(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = Field(default=None, min_length=1)

class GlobalEmbeddingConfigBody(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = Field(default=None, min_length=1)

class GlobalLLMSettings(BaseModel):
    enabled: bool
    chat_config: GlobalChatConfigBody | None = None
    embedding_config: GlobalEmbeddingConfigBody | None = None

class GlobalScopeTestRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None

class ListModelsRequest(BaseModel):  # 保留（chat/models、embedding/models 共用）
    base_url: str
    api_key: str
    provider_template_id: str | None = None
```
- 改 `GET /admin/llm-config`：返回 `{llm_global_enabled, chat_config: get_global_chat_settings(db), embedding_config: get_global_embedding_settings(db)}`
- 改 `PUT /admin/llm-config`：分别调 `set_global_chat_settings(enabled, **chat_config)` 和 `set_global_embedding_settings(enabled, **embedding_config)`（只传非 None 的）；审计 detail 记 base_url/model（两套都记），不含 api_key。
- 删老 `POST /admin/llm-config/test` 和 `/admin/llm-config/models`。
- 新增 4 个端点：
  - `POST /admin/llm-config/chat/test`：两模式（传值/已存值），调 `test_llm_connection(scope="chat", ...)`
  - `POST /admin/llm-config/embedding/test`：调 `test_llm_connection(scope="embedding", ...)`
  - `POST /admin/llm-config/chat/models`：调 `list_provider_models`
  - `POST /admin/llm-config/embedding/models`：调 `list_provider_models`
  - 全部 `require_admin`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_admin_split_endpoints.py -v`
Expected: PASS。

- [ ] **Step 5: 全量回归**

Run: `cd apps/api && uv run pytest -q`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/api/admin/console.py tests/test_admin_split_endpoints.py
git commit -m "feat(api): admin 全局 LLM 拆 chat/embedding 两套 + 删 allowed_models + test/models 拆四端点"
```

---

## Task 11: embedding 调用加日志（D7，可选）

**Files:**
- Modify: `apps/api/app/rag/archiver.py`
- Modify: `apps/api/app/rag/retriever.py`
- Modify: `apps/api/app/services/knowledge_service.py`
- Test: `apps/api/tests/test_embedding_logging.py`

> D7 默认做。若评审时决定不做，跳过本任务。

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_embedding_logging.py`:

```python
"""embedding 调用应写 LLMCallLog(action='embed')。"""

from unittest.mock import patch, MagicMock


def test_archiver_logs_embed_call(db_session):
    from app.rag import archiver
    from app.models import LLMCallLog, Project
    from sqlalchemy import select
    import uuid
    fake_cfg = MagicMock()
    fake_cfg.model = "emb-3"; fake_cfg.source = "user"
    with patch("app.rag.archiver.resolve_embedding_config", return_value=fake_cfg), \
         patch("app.rag.archiver.embed_texts", return_value=[[0.1]]):
        p = Project(id=uuid.uuid4(), user_id=uuid.uuid4(), title="t")
        db_session.add(p); db_session.commit()
        archiver.archive_project(db_session, project=p, user_id=p.user_id)
    logs = db_session.scalars(select(LLMCallLog).where(LLMCallLog.action == "embed")).all()
    assert len(logs) >= 1
    assert logs[0].model == "emb-3"
```

- [ ] **Step 2: 跑确认失败**

Run: `cd apps/api && uv run pytest tests/test_embedding_logging.py -v`
Expected: FAIL（没写日志）。

- [ ] **Step 3: 加日志**

在 archiver/retriever/knowledge_service 的 embed 调用后，写 LLMCallLog。抽个共享 helper（放 `app/services/llm_log_helper.py` 或直接复用 `api/ai.py:_log_llm_call`——但那个在 ai.py 里。抽到 service 共享）:

新增 `apps/api/app/services/llm_log_helper.py`:
```python
from sqlalchemy.orm import Session
from app.models import LLMCallLog


def log_embed_call(db: Session, *, user_id, model: str, provider: str,
                   status: str = "success", duration_ms: int | None = None,
                   error: str | None = None, project_id=None) -> None:
    """写一条 embedding 调用日志（仅元数据，D7）。"""
    db.add(LLMCallLog(
        user_id=user_id, project_id=project_id, action="embed",
        model=model, provider=provider, status=status,
        duration_ms=duration_ms, error=error,
    ))
    db.commit()
```

在 archiver 的 `embed_texts` 后调 `log_embed_call(db, user_id=user_id, model=embed_config.model, provider=embed_config.source, project_id=project.id)`。retriever/knowledge_service 同理（retriever 无 project_id 传 None）。

- [ ] **Step 4: 跑测试 + 回归**

Run: `cd apps/api && uv run pytest tests/test_embedding_logging.py -v && uv run pytest -q`
Expected: 通过 + 全绿。

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/services/llm_log_helper.py app/rag/archiver.py app/rag/retriever.py app/services/knowledge_service.py tests/test_embedding_logging.py
git commit -m "feat(llm): embedding 调用补 LLMCallLog(action=embed)（D7）"
```

---

## Task 12: 后端全量回归 + 冒烟

- [ ] **Step 1: 全量测试**

Run: `cd apps/api && uv run pytest -v`
Expected: 全绿。

- [ ] **Step 2: grep 确认无残留**

Run: `cd apps/api && grep -rn "ResolvedLLMConfig\|resolve_llm_config\|allowed_models\|embedding_model" app/ | grep -v "test_llm_connection\|#"`
Expected: 空（或只在 `test_llm_connection` 的 embedding_model 参数和注释里——那是通用的测试函数，保留）。

- [ ] **Step 3: 冒烟启动**

Run: `cd apps/api && uv run uvicorn app.main:app --port 8000 &`，curl 新端点:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/settings/embedding  # 401（未登录）不是 404
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/api/v1/admin/llm-config/chat/test  # 401
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/v1/settings/llm/templates  # 401
```
Expected: 都 401（不是 404）。停服务。

后端完成。进前端。

---

## Task 13-18: 前端（类型/api/queries/llm-source/面板/两页）

> 前端任务结构与上一轮类似。每个任务：改文件 → `pnpm build` → 提交。前端无单测，靠 build + 手动 QA。

### Task 13: types/api.ts + lib/api.ts + lib/queries.ts

- [ ] 改 `types/api.ts`：新 `UserEmbeddingConfig`（与 UserLLMConfig 同构去 provider）；`GlobalLLMSettings` 改成 `{llm_global_enabled, chat_config: {...}, embedding_config: {...}}`（删 allowed_models、删 global_config）；chat 的 `UserLLMConfig`/`UserLLMConfigCreate`/`UserLLMConfigUpdate` 去 embedding_model；新增 embedding 对应的 Create/Update 类型。
- [ ] 改 `lib/api.ts`：新增 `listMyEmbeddingConfigs/createMyEmbeddingConfig/updateMyEmbeddingConfig/deleteMyEmbeddingConfig/testMyEmbeddingConfig/listMyEmbeddingModels`；`getGlobalLLM`/`setGlobalLLM` 改新 shape；test/models admin 拆 chat/embedding；chat 端点的 test/models 不变。
- [ ] 改 `lib/queries.ts`：新增 embedding 的 hooks；global hooks 适配新 shape。
- [ ] `pnpm build`。
- [ ] 提交：`feat(web): embedding 类型/api client/hooks + global 拆 chat/embedding`。

### Task 14: lib/llm-source.ts 双 key

- [ ] 改：`tg_default_llm_source` → `tg_default_chat_source` + `tg_default_embedding_source`；`getDefaultSource/setDefaultSource/clearDefaultSource/isGlobalDefault/setGlobalDefault` 各拆 chat/embedding 版（如 `getChatDefaultSource`/`getEmbeddingDefaultSource` 等）。
- [ ] `pnpm build`。
- [ ] 提交：`feat(web): llm-source 拆 chat/embedding 双 key`。

### Task 15: LLMConfigEditPanel 去 adminMode + allowed_models

- [ ] 改 `components/llm-config/LLMConfigEditPanel.tsx`：删 `adminMode`/`initialAllowedModels` props 和 allowed_models 输入框 + 相关逻辑。
- [ ] `pnpm build`。
- [ ] 提交：`refactor(web): LLMConfigEditPanel 去 adminMode + allowed_models`。

### Task 16: EmbeddingConfigRow 组件

- [ ] 新建 `components/llm-config/EmbeddingConfigRow.tsx`：镜像 LLMConfigRow，数据源是 UserEmbeddingConfig，source 前缀 `custom-emb:`。
- [ ] `pnpm build`。
- [ ] 提交：`feat(web): EmbeddingConfigRow 组件`。

### Task 17: /settings 拆两区

- [ ] 改 `app/(app)/settings/page.tsx`：拆【对话模型配置】区 + 【嵌入模型配置】区，各含默认源 toggle + 配置列表 + 添加按钮 + 内联展开 EditPanel。保留全局授权说明条（chat+emb 共用 grant）和「我的技能」卡片。删旧的单区结构。
- [ ] `pnpm build` + 手动 QA（dev server 看两区渲染）。
- [ ] 提交：`feat(web): /settings 拆对话/嵌入两区`。

### Task 18: /admin/console/llm 拆两区

- [ ] 改 `app/(app)/admin/console/llm/page.tsx`：enabled Switch 共用 + 【全局对话模型】EditPanel + 【全局嵌入模型】EditPanel；顶部「用已存配置测试」拆 chat/embedding 两个按钮；test/models 调新的 chat/embedding 端点。
- [ ] `pnpm build` + 手动 QA。
- [ ] 提交：`feat(web): /admin/console/llm 拆对话/嵌入两区`。

---

## Task 19: 前端全量构建 + 手动 QA

- [ ] `cd apps/web && pnpm build`（全绿）。
- [ ] 启前后端，手动 QA 清单：
  - /settings 两区视觉对称、各自 CRUD/测试/拉模型
  - chat 与 embedding 各自选默认源互不影响
  - **核心**：chat 配智谱 + embedding 配 OpenAI，端到端跑通（chat 对话正常 + 知识库 RAG 检索正常）
  - admin 两套全局配置独立、各自复检
  - allowed_models 已从 admin 面板消失
  - /settings/skills 入口仍在

---

## Task 20: 文档（AGENTS.md）

- [ ] 读 AGENTS.md，更新 LLM 相关说明（source 协议拆 chat_source/embedding_source、custom-chat:/custom-emb: 前缀、两表）。
- [ ] 提交：`docs(agents): 更新 LLM chat/embedding 独立凭据说明`。

---

## 完成标准

- 后端：全量测试绿；`grep` 无残留老的 ResolvedLLMConfig/resolve_llm_config/allowed_models；新端点冒烟 401；chat/embedding 独立性测试通过。
- 前端：`pnpm build` 绿；两页拆两区；跨供应商混搭端到端 QA 通过。
- 所有改动原子提交，message 遵循现有风格。
- 核心 invariant 有测试守护：`test_chat_and_embedding_resolve_independently`、`test_embedding_fallback_no_crosstalk_to_chat`。
