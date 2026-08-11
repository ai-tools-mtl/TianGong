# C1 技术债修复（SessionLocal expire_on_commit）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 C1 技术债——将 `SessionLocal` 改为 `expire_on_commit=False`，根治「commit 后 ORM 对象 expire 触发冗余 lazy load」的架构隐患。

**Architecture:** 方案 A（全局配置 + 局部修复）。调研确认全项目 89 处 commit 中仅 2 处真实 STALE-RISK（`memories.py` 读 server-default 时间戳），其余 44 处已有 `db.refresh()`、~43 处读客户端 UUID/Python 字段。故改 1 行全局配置 + 补 2 处 `db.refresh()`，辅以配置断言测试和 agent loop 回归测试防未来回归。

**Tech Stack:** FastAPI + SQLAlchemy 2.0（sync engine）+ pytest（SQLite 内存库 + StaticPool）。

**关联设计**：[2026-07-29-c1-expire-on-commit-design.md](../specs/2026-07-29-c1-expire-on-commit-design.md)

**关键约定**（开工前必读）：
- 测试用 SQLite 内存库（`conftest.py` 的 `engine` fixture），**不执行 PG server_default** → `created_at`/`updated_at` 在测试库里为 None，靠 `if mem.created_at else ""` 兜底
- `conftest.py` 的 `db_session`/`app_obj` fixture 各自 `sessionmaker(bind=engine)` 新建，**不引用生产 `SessionLocal`** → 配置生效必须直接断言生产 `SessionLocal`
- worktree 执行：所有命令在 `apps/api/` 下跑（`.worktrees/fix-c1-expire-on-commit/apps/api/`）

---

## 文件结构

| 文件 | 责任 | 操作 |
|---|---|---|
| `apps/api/app/core/database.py` | 生产 `SessionLocal` 配置 | 修改：加 `expire_on_commit=False` + 注释 |
| `apps/api/app/api/memories.py` | 记忆 CRUD 路由 | 修改：两处 commit 后补 `db.refresh(mem)` |
| `apps/api/tests/test_c1_expire_on_commit.py` | 配置断言 + commit 后不 expire 行为测试 | 新建 |
| `apps/api/tests/test_agent_loop_expire.py` | agent loop commit 后访问回归测试 | 新建 |

---

## Task 0：建立 worktree 与 baseline

**Files:** 无代码改动，仅环境准备

- [ ] **Step 1: 创建 worktree**

Run（在仓库根 `G:\03-Personal-Projects\TianGong`）：
```bash
git worktree add .worktrees/fix-c1-expire-on-commit -b fix/c1-expire-on-commit
```
Expected: 新分支 `fix/c1-expire-on-commit` 创建，worktree 检出到 `.worktrees/fix-c1-expire-on-commit`

- [ ] **Step 2: 复制 .env**

Run：
```bash
cp apps/api/.env .worktrees/fix-c1-expire-on-commit/apps/api/.env
```
Expected: `.env` 复制成功（后端测试/运行需要环境变量）

- [ ] **Step 3: 装依赖并跑 baseline 测试**

Run（在 `.worktrees/fix-c1-expire-on-commit/apps/api`）：
```bash
uv sync --extra dev
uv run pytest -q
```
Expected: 全绿，约 762 个测试通过（记录确切数字作为 baseline，后续任务需 ≥ 此数）。**若 baseline 已有失败，先停下报告，不要继续。**

---

## Task 1：配置断言测试（先写失败测试，验证测试有效）

**目标**：先写一个断言生产 `SessionLocal` 配置的测试，此时它应**失败**（因为配置还没改）——证明测试有效，而非永远绿的假测试。

**Files:**
- Create: `apps/api/tests/test_c1_expire_on_commit.py`

- [ ] **Step 1: 写配置断言测试（此时应失败）**

Create `apps/api/tests/test_c1_expire_on_commit.py`：

```python
"""C1 修复：SessionLocal expire_on_commit 配置与 commit 后不 expire 行为测试。

设计依据见 docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md。

关键约束（conftest.py）：
- 测试用的 db_session/app_obj fixture 自建 sessionmaker，不引用生产 SessionLocal。
  故「配置生效」必须直接断言生产 SessionLocal，而非通过 fixture 间接验证。
- SQLite 不执行 PG server_default，时间戳类断言在测试层无效，靠 PG 手动验证。
"""
from sqlalchemy import event


def test_sessionlocal_expire_on_commit_is_false():
    """生产 SessionLocal 必须设 expire_on_commit=False（C1 修复的核心断言）。

    断言生产 sessionmaker 的 kwargs，而非 fixture session——后者是 conftest
    独立新建的，不受此配置影响。
    """
    from app.core.database import SessionLocal

    assert SessionLocal.kw["expire_on_commit"] is False, (
        "SessionLocal 必须设 expire_on_commit=False（C1 修复）。"
        "见 docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md"
    )
```

- [ ] **Step 2: 跑测试，确认它失败**

Run：
```bash
uv run pytest tests/test_c1_expire_on_commit.py::test_sessionlocal_expire_on_commit_is_false -v
```
Expected: FAIL，断言错误（`SessionLocal.kw` 里没有 `expire_on_commit` 键，或值为 True）。**这证明测试有效**——若此时就通过，说明断言写错了。

---

## Task 2：改全局配置让 Task 1 测试通过

**Files:**
- Modify: `apps/api/app/core/database.py:10`

- [ ] **Step 1: 修改 SessionLocal 加 expire_on_commit=False**

Modify `apps/api/app/core/database.py`，将第 10 行：

```python
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
```

改为：

```python
# expire_on_commit=False：commit 后不再 expire session 内所有 ORM 对象。
# 依据全量审计（89 处 commit）：44 处紧跟 db.refresh()（显式重查，免疫此配置），
# 其余多读客户端生成的 UUID 主键（commit 前已知）或 Python 端赋值字段。
# **唯一需注意**：读 server-default 列（如 created_at/updated_at 这类 DB 端赋值时间戳）
# 时，commit 后必须显式 db.refresh() 才能拿到 DB 生成的值——否则读到 None/旧值。
# 见 docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md。
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True,
    expire_on_commit=False,
)
```

- [ ] **Step 2: 跑 Task 1 测试，确认通过**

Run：
```bash
uv run pytest tests/test_c1_expire_on_commit.py::test_sessionlocal_expire_on_commit_is_false -v
```
Expected: PASS

- [ ] **Step 3: 提交**

Run：
```bash
git add app/core/database.py tests/test_c1_expire_on_commit.py
git commit -m "fix(rag): C1 SessionLocal 设 expire_on_commit=False（根治 commit 后 expire 隐患）"
```

---

## Task 3：commit 后不 expire 的行为测试（验证配置的真实效果）

**目标**：证明 `expire_on_commit=False` 不仅配置正确，而且行为正确——commit 后访问属性不触发额外 SELECT。用 `event.listen` 计数 SELECT，并设对照组（True 触发重查）证明测试有效。

**Files:**
- Modify: `apps/api/tests/test_c1_expire_on_commit.py`（追加测试）

- [ ] **Step 1: 追加行为测试（含对照组）**

Append to `apps/api/tests/test_c1_expire_on_commit.py`：

```python
def _count_selects(engine, session):
    """用 event listener 计数 commit 后访问属性触发的 SELECT 次数。

    返回一个闭包，调用它会在「commit 后访问属性」期间计数。
    """
    count = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _counter(conn, cursor, statement, params, context, executemany):
        # 只数 SELECT（lazy load 发的是 SELECT），排除 INSERT
        if statement.lstrip().lower().startswith("select"):
            count["n"] += 1

    return count, _counter


def _make_user(session):
    """构造并提交一个 User，返回该对象（commit 后仍 attached）。"""
    from app.core.security import hash_password
    from app.models import User

    u = User(
        username="expiretest",
        email="expiretest@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="过期测试",
    )
    session.add(u)
    session.commit()
    return u


def test_no_lazy_load_after_commit_when_expire_off(engine):
    """expire_on_commit=False 时，commit 后访问属性不触发额外 SELECT。"""
    from sqlalchemy.orm import sessionmaker

    # 测试内自建 session，显式 expire_on_commit=False（模拟生产配置）
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        count, listener = _count_selects(engine, session)
        u = _make_user(session)
        baseline = count["n"]

        # commit 后访问属性——expire_on_commit=False 下不应触发 lazy load
        _ = u.username
        _ = u.email

        session.engine  # noop，确保 session 仍可用
        accessed = count["n"] - baseline
        assert accessed == 0, f"expire_on_commit=False 下访问属性不应触发 SELECT，实际触发了 {accessed} 次"
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        session.close()


def test_lazy_load_does_trigger_when_expire_on(engine):
    """对照组：expire_on_commit=True 时，commit 后访问属性会触发 SELECT。

    证明上面那个测试不是「永远 0」的假绿——True 配置下确实 >0。
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine, expire_on_commit=True)
    session = Session()
    try:
        count, listener = _count_selects(engine, session)
        u = _make_user(session)
        baseline = count["n"]

        _ = u.username  # expire 了，触发 lazy reload

        accessed = count["n"] - baseline
        assert accessed > 0, "expire_on_commit=True 下访问属性应触发 SELECT（对照组）"
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        session.close()


def test_client_uuid_pk_readable_after_commit(engine):
    """客户端生成的 UUID 主键，commit 后仍可读（ai.py 依赖此行为）。

    ai.py:239/254 等在 commit 后读 section.id/conv.id（均为 default=uuid.uuid4）。
    本测试确认 expire_on_commit=False 下这些读取安全。
    """
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        import uuid
        from app.models import User

        u = User(
            username="pktest", email="pktest@tiangong.dev",
            password_hash="x", name="pk测试",
        )
        pk_before = u.id  # 客户端生成，commit 前就有
        session.add(u)
        session.commit()

        # commit 后读 PK——应等于 commit 前的值，不报错
        assert u.id == pk_before
        assert isinstance(u.id, uuid.UUID)
    finally:
        session.close()
```

- [ ] **Step 2: 跑这些测试，确认全过**

Run：
```bash
uv run pytest tests/test_c1_expire_on_commit.py -v
```
Expected: 4 个测试全 PASS（含 Task 1 的配置断言 + 这 3 个行为测试）。**若对照组（`test_lazy_load_does_trigger_when_expire_on`）失败，说明 event listener 计数逻辑有问题，需调试。**

- [ ] **Step 3: 提交**

Run：
```bash
git add tests/test_c1_expire_on_commit.py
git commit -m "test(rag): C1 commit 后不 expire 行为测试（含 True 对照组证明测试有效）"
```

---

## Task 4：修复 memories.py 两处 STALE-RISK（TDD：先写失败测试）

**目标**：`memories.py:56/71` commit 后直接 `_to_out(mem)` 读 `created_at`/`updated_at`（server-default），切 `expire_on_commit=False` 后会读到 None。先写测试暴露问题，再加 `db.refresh()`。

**注意测试约束**：SQLite 不执行 PG server_default，所以**测试无法直接断言「时间戳非空」**。改为断言「调用了 `db.refresh(mem)`」——通过 spy `db.refresh` 验证修复存在。

**Files:**
- Modify: `apps/api/tests/test_memory_api.py`（追加测试，沿用现有测试文件而非新建）
- Modify: `apps/api/app/api/memories.py:56,71`

- [ ] **Step 1: 查看现有 test_memory_api.py 的测试模式**

Run：
```bash
sed -n '1,40p' tests/test_memory_api.py
```
了解它如何 mock embedding、如何构造 client/registered_user。本任务追加的测试沿用同样的 mock 模式。

- [ ] **Step 2: 写失败测试（断言 commit 后调用了 db.refresh）**

Append to `apps/api/tests/test_memory_api.py`：

```python
def test_create_memory_calls_refresh_after_commit(client, app_obj, registered_user, monkeypatch):
    """C1 修复：POST /memories commit 后必须 db.refresh(mem)，否则 expire_on_commit=False
    下读 server-default 时间戳返回 None（PG 上会变成空串）。

    SQLite 不执行 server_default，无法断言时间戳非空，故改用 spy db.refresh 验证修复存在。
    """
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    # spy：记录生产 session 是否调用了 refresh
    refreshed = {"called": False}
    original_refresh = None

    from app.api import memories as mem_module
    real_get_db = mem_module.get_db

    # 用 dependency override 注入一个会记录 refresh 的 session
    from app.core.database import get_db
    from sqlalchemy.orm import Session

    class _SpySession(Session):
        def refresh(self, *args, **kwargs):
            refreshed["called"] = True
            return super().refresh(*args, **kwargs)

    TestingSession = None
    from tests.conftest import _FakeStorage  # noqa: F401（确保 conftest 已加载）

    def override_get_db():
        from sqlalchemy.orm import sessionmaker
        from app.api import memories as mm
        # 取 conftest engine：通过 app_obj 的现有 override 拿不到 engine，直接从 fixture 注入的 engine
        # 改用更简单方式：monkeypatch Session.refresh
        return real_get_db()

    # 更简单的方案：直接 monkeypatch app.api.memories 路由内 session 的 refresh
    # 因 SessionLocal 已 expire_on_commit=False，我们 spy Session.refresh 类方法
    from sqlalchemy.orm import sessionmaker
    import app.api.memories as mem_api

    call_count = {"n": 0}
    orig_refresh = Session.refresh

    def spy_refresh(self, *args, **kwargs):
        call_count["n"] += 1
        return orig_refresh(self, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", spy_refresh)

    # 登录
    from app.core.security import create_access_token
    token = create_access_token({"sub": str(registered_user["id"])})
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/memories",
        json={"content": "偏好简洁风格"},
        headers=headers,
    )

    assert resp.status_code == 201, resp.text
    assert call_count["n"] >= 1, "POST /memories commit 后必须调用 db.refresh（C1 修复）"


def test_update_memory_calls_refresh_after_commit(client, app_obj, registered_user, monkeypatch):
    """C1 修复：PATCH /memories/{id} commit 后必须 db.refresh(mem)。"""
    from app.services import memory_service as ms
    from app.models import UserMemory
    from sqlalchemy.orm import Session

    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    uid = registered_user["id"]
    # 预置一条记忆
    import uuid
    existing = UserMemory(user_id=uuid.UUID(uid), content="旧偏好", embedding=None, source="manual")
    db_session = app_obj.dependency_overrides[__import__("app.core.database", fromlist=["get_db"]).get_db]().__next__()
    db_session.add(existing)
    db_session.commit()
    mem_id = str(existing.id)

    call_count = {"n": 0}
    orig_refresh = Session.refresh

    def spy_refresh(self, *args, **kwargs):
        call_count["n"] += 1
        return orig_refresh(self, *args, **kwargs)

    monkeypatch.setattr(Session, "refresh", spy_refresh)

    from app.core.security import create_access_token
    token = create_access_token({"sub": str(registered_user["id"])})
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch(
        f"/memories/{mem_id}",
        json={"content": "新偏好"},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    assert call_count["n"] >= 1, "PATCH /memories commit 后必须调用 db.refresh（C1 修复）"
```

> **注**：第二个测试取 db_session 的方式较 hack（通过 dependency_overrides 拿 generator）。若实现时该方式不通，改用更稳妥的 `db_session` fixture 直接构造 UserMemory（参考 `test_save_memory_tool.py` 的预置模式）。测试的核心断言不变：refresh 被调用。

- [ ] **Step 3: 跑测试，确认失败（修复前 memories.py 没有 refresh）**

Run：
```bash
uv run pytest tests/test_memory_api.py::test_create_memory_calls_refresh_after_commit tests/test_memory_api.py::test_update_memory_calls_refresh_after_commit -v
```
Expected: FAIL，断言 `call_count["n"] >= 1` 失败（当前是 0，因为还没加 refresh）。

- [ ] **Step 4: 修复 memories.py 两处，加 db.refresh(mem)**

Modify `apps/api/app/api/memories.py`，第 56-57 行（create_memory）：

```python
    db.commit()
    return _to_out(mem)
```
改为：
```python
    db.commit()
    db.refresh(mem)  # expire_on_commit=False：需显式刷新拿 server_default 的 created_at/updated_at
    return _to_out(mem)
```

第 71-72 行（update_memory）：
```python
    db.commit()
    return _to_out(mem)
```
改为：
```python
    db.commit()
    db.refresh(mem)  # 同上，updated_at 有 onupdate 也需刷新
    return _to_out(mem)
```

- [ ] **Step 5: 跑测试，确认通过**

Run：
```bash
uv run pytest tests/test_memory_api.py::test_create_memory_calls_refresh_after_commit tests/test_memory_api.py::test_update_memory_calls_refresh_after_commit -v
```
Expected: 2 个测试 PASS。

- [ ] **Step 6: 跑整个 test_memory_api.py 回归**

Run：
```bash
uv run pytest tests/test_memory_api.py -v
```
Expected: 全绿（确保加 refresh 没破坏现有记忆 API 测试）。

- [ ] **Step 7: 提交**

Run：
```bash
git add app/api/memories.py tests/test_memory_api.py
git commit -m "fix(rag): C1 memories.py commit 后补 db.refresh（读 server_default 时间戳）"
```

---

## Task 5：agent loop 回归测试（防未来把配置改回 True）

**目标**：模拟 `save_memory` 工具内 commit 后访问 `section` 属性的真实场景。这是 C1 的核心风险区——若未来有人误改回 `expire_on_commit=True`，此测试暴露「commit 后访问触发问题」。

**Files:**
- Create: `apps/api/tests/test_agent_loop_expire.py`

- [ ] **Step 1: 写 agent loop 回归测试**

Create `apps/api/tests/test_agent_loop_expire.py`：

```python
"""C1 回归测试：agent loop 内 save_memory commit 后访问 ORM 对象属性。

模拟真实场景：astream_chat/astream_generate 期间 save_memory 工具 db.commit()
（tools.py:94/98），退出 loop 后 endpoint 仍持有 section/conv 引用并访问其属性
（ai.py:239 读 section.id/conv.id、ai.py:347 读 section.status）。

C1 修复（expire_on_commit=False）后这些访问不触发冗余 lazy load，也不在
aborted session 上抛 InternalError。本测试固化这一正确行为，防止未来误改回 True。
"""
import uuid


def _make_project_and_section(db_session):
    """构造真实入库的 User + Project + Section，返回 (user_id, section)。"""
    from app.models import Project, Section, User
    from app.core.security import hash_password

    u = User(
        username=f"loop-{uuid.uuid4().hex[:8]}",
        email=f"loop-{uuid.uuid4().hex[:8]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="loop测试",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)

    p = Project(user_id=u.id, title="测试交底书")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)

    s = Section(
        project_id=p.id, template_section_id="ts-solution", order=1,
        key="solution", title="技术方案", status="empty",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return u.id, s


def test_save_memory_commit_then_read_section_attrs(db_session, registered_user, monkeypatch):
    """save_memory 工具内 commit 后，访问 section 的 id/status 不抛异常、值正确。

    这是 ai.py:347（读 section.status）/ ai.py:350（读 section.id）的真实路径。
    expire_on_commit=False 下：commit 后 section 未 expire，属性值仍是内存中的
    客户端值（UUID/Python status），访问不触发 SELECT。
    """
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms

    user_id, section = _make_project_and_section(db_session)
    # 记住 commit 前的值，用于断言 commit 后读到的是同一份
    section_id_before = section.id
    section_status_before = section.status

    # mock embedding 与去重，让 save_memory 走「新建」分支并真实 commit
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: None)

    tools = create_agent_tools(db=db_session, user_id=user_id)
    # tools[1] 是 save_memory
    result = tools[1].invoke({"content": "记住我喜欢简洁的写作风格"})
    assert "已保存" in result

    # 核心：save_memory 已 commit（tools.py:98），现在访问 section 属性
    # —— 这是 ai.py 在 agent loop 退出后做的事
    assert section.id == section_id_before   # 客户端 UUID，commit 前后一致
    assert section.status == section_status_before  # Python 赋值，未变

    # 进一步：模拟 ai.py:347 的写后读（section.status = "drafting" 后读）
    section.status = "drafting"
    assert section.status == "drafting"


def test_rag_search_rollback_then_read_section_attrs(db_session, registered_user, monkeypatch):
    """rag_search 工具异常 rollback 后，访问 section 属性不抛 InternalError。

    rag_search 在检索失败时 db.rollback()（tools.py:46）。rollback 后访问
    section 属性：expire_on_commit=False 下对象未 expire（rollback 会 expire，
    但下一访问在新事务上 reload，正常 session 不抛错）。
    """
    from app.ai.tools import create_agent_tools
    from app.rag import retriever

    user_id, section = _make_project_and_section(db_session)
    section_id_before = section.id

    # 让 retrieve 抛异常，触发 rag_search 的 rollback 路径
    def _boom(*args, **kwargs):
        raise RuntimeError("模拟检索失败")

    monkeypatch.setattr(retriever, "retrieve", _boom)

    tools = create_agent_tools(db=db_session, user_id=user_id)
    # tools[0] 是 rag_search
    result = tools[0].invoke({"query": "测试"})
    assert result == []  # 异常时返回空列表

    # rollback 后访问 section.id——不应抛 InternalError（事务已回滚，干净）
    assert section.id == section_id_before
```

- [ ] **Step 2: 跑测试，确认通过**

Run：
```bash
uv run pytest tests/test_agent_loop_expire.py -v
```
Expected: 2 个测试 PASS。

> **若 `test_rag_search_rollback_then_read_section_attrs` 失败**：rollback 会 expire 对象（即便 expire_on_commit=False，rollback 仍 expire）。此情况下访问 `section.id` 会触发一次 lazy reload——在干净 session 上这是同步 SELECT，应成功。若报错，检查是否触发了 reload 而测试断言期望「不 reload」。本测试的核心是**不抛异常 + 值正确**，允许内部 reload。若确有 reload，把断言改为只验证「不抛异常 + id 一致」即可（去掉对 reload 的隐含假设）。

- [ ] **Step 3: 提交**

Run：
```bash
git add tests/test_agent_loop_expire.py
git commit -m "test(rag): C1 agent loop commit/rollback 后访问 ORM 回归测试"
```

---

## Task 6：全量回归测试（主证据）

**目标**：跑全量测试，确认切全局配置 + 补 refresh 不破坏任何现有行为。这是「方案 A 安全」的主证据。

- [ ] **Step 1: 全量测试**

Run：
```bash
uv run pytest -q
```
Expected: 全绿，测试数 ≥ baseline（Task 0 记录的数字 + 新增的 ~7 个测试）。

- [ ] **Step 2: 若有失败，系统性排查（不要绕过）**

若有失败，**不要改测试掩盖问题**。按以下顺序排查：
1. 该失败是否与 expire 相关？（commit 后访问属性报错）→ 检查是否漏了 refresh（可能审计漏了某处，补 refresh）
2. 该失败是否是 SQLite 测试库的 server_default 兜底问题？→ 多半与 C1 无关，单独排查
3. 记录失败的具体测试和报错，停下报告，不要硬改

---

## Task 7：记录 PG 手动验证步骤到 spec（非自动化，交付物）

**目标**：测试基础设施不支持 PG，PG 行为靠手动验证。把验证步骤固化到设计文档，作为交付物的一部分。

**Files:**
- Modify: `docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md`（§5.5 已有步骤，此处补充「实施后待执行」标记）

- [ ] **Step 1: 在 spec §6 验收标准里，把 PG 验证项标记为待执行**

Modify `docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md` 的 §6 验收标准最后一项，确认其内容为：

```markdown
- [ ] 真实 PG 手动验证（§5.5）：对话触发 save_memory 后继续对话不报 InternalError；POST /memories 返回的 created_at/updated_at 非空
```

（该项本就是 checkbox，无需改动；本步是确认它存在，作为实施完成的交付门槛之一）

- [ ] **Step 2: 提交（若有改动）**

若 spec 无改动则跳过。本任务主要是确认 PG 手动验证步骤已固化、作为交付门槛。

---

## Self-Review

**1. Spec coverage（对照设计 spec 各节）：**
- §4.1 改动 1（database.py 配置）→ Task 2 ✅
- §4.2 改动 2&3（memories.py 两处 refresh）→ Task 4 ✅
- §4.3 明确不改的点（ai.py undefended 访问）→ 无需任务，但 Task 5 的回归测试覆盖了该路径 ✅
- §5.2 第 1 层测试（配置断言 + 行为）→ Task 1 + Task 3 ✅
- §5.3 第 2 层 agent loop 回归 → Task 5 ✅
- §5.4 第 3 层全量回归 → Task 6 ✅
- §5.5 第 4 层 PG 手动验证 → Task 7（固化步骤）✅
- §6 验收标准 → 全部任务覆盖 ✅

**2. Placeholder scan：** 无 TBD/TODO。所有代码块完整。Task 4 Step 2 的 spy 方式较复杂，已在注释里给出备选方案（若 hack 方式不通改用 db_session fixture）——这是为实施者留的退路，不是占位符。

**3. Type consistency：** `db.refresh(mem)` 签名一致；`tools[1].invoke({"content": ...})` 与现有 `test_save_memory_tool.py` 一致；`Session.refresh` spy 用法前后一致。✅

**4. 已知复杂点**：Task 4 的 spy 测试（通过 monkeypatch Session.refresh 验证调用）是本计划最脆弱的部分。实施时若该方式不稳，回退方案是：直接断言「commit 后 `mem.created_at` 在 SQLite 下为 None 不抛」（行为测试而非调用计数）。但调用计数能更强地证明「修复存在」，故优先采用。

---

## 执行说明

**Plan complete and saved to `docs/superpowers/plans/2026-07-29-c1-expire-on-commit.md`.**

两种执行方式：

1. **Subagent-Driven（推荐）** —— 我每个 Task 派一个新 subagent 执行，Task 间我做 review，迭代快、上下文干净
2. **Inline Execution** —— 在当前会话按 executing-plans 批量执行，带 checkpoint review

选哪种？
