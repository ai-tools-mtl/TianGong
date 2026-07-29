# C1 技术债修复：SessionLocal `expire_on_commit` 配置

> **状态**：设计阶段（brainstorming 产出，待 writing-plans 转实施计划）
> **日期**：2026-07-29
> **关联**：[2026-07-28-user-memory-design.md](2026-07-28-user-memory-design.md) §12 #8（C1 原始记录）、[GOTCHAS.md](../../GOTCHAS.md)

## 1. 背景与问题陈述

### 1.1 什么是 C1

`apps/api/app/core/database.py:10` 的 `SessionLocal` 未显式设 `expire_on_commit`，SQLAlchemy 默认 `True`：

```python
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
```

后果：每次 `db.commit()` 后，session 内**所有** ORM 对象被标记 expired，下次访问属性时触发 lazy load（重新查库）。

### 1.2 为什么是预防性修复

C1 **当前未触发任何报错**，而是「靠调用顺序侥幸没炸」的架构隐患。在 agent loop 场景下：`save_memory` 工具内部 `db.commit()`（`tools.py:94/98`）后，agent loop 仍持有 `section`/`conv` 等对象引用，后续访问属性即触发 lazy load。修复价值是**防止未来新代码踩雷**。

### 1.3 修复范围声明

- **本 spec 只修 C1**（`expire_on_commit` 配置）。
- **C2 已修复，不重复处理**：`log_embed_call` / `log_firecrawl_call` 已改用 SAVEPOINT（`begin_nested`，见 `app/services/llm_log_helper.py:37`），不再 commit 主事务。`chat`/`generate` 端点的 `_log_llm_call` 仍用主 session，但 finally 块已加 rollback 预清理。

---

## 2. 调研结论（修正了任务预设的三个前提）

启动前先做了全量影响面审计（两个独立子智能体交叉验证），结论**纠正了任务描述里的三个前提假设**，直接决定方案选型。

### 2.1 假设 1：「92 处 commit 需全量回归」→ 实际仅 2 处真实 STALE-RISK

代码库**极其自律**。`apps/api/app/` 下 89 处可执行 commit 的分布：

| 类别 | 数量 | 说明 |
|---|---|---|
| **紧跟 `db.refresh(obj)`** | 44 | 显式重查，**完全免疫** `expire_on_commit` 配置 |
| 读客户端 UUID 主键 / Python 端赋值字段 | ~43 | 主键 `default=uuid.uuid4` commit 前已知；status 等是 Python 赋值，非 server default |
| **真实 STALE-RISK（读 server-default 时间戳）** | **2** | 仅 `app/api/memories.py:56` 和 `:71` |

**`db.refresh()` 调用点共 44 处**，遍布 services 层（`knowledge_service` 5 处、`tag_service` 4 处、`share_service`/`parse_service`/`invite_service` 各 3 处等）。这种 `commit(); refresh(obj)` 模式是代码库的主流约定，证明团队早已意识到 expiry 风险。

### 2.2 假设 2：「async 下 commit 后访问抛 MissingGreenlet」→ 实际永不抛

`database.py:9` 用的是 **sync** `create_engine` + sync `Session`，**不是** `create_async_engine`。agent loop 的 async 流式来自 langgraph 的 `astream_events` + `asyncio.ensure_future` 包装，但 DB 调用本身同步。

lazy load 时 SQLAlchemy 直接发**同步阻塞 SELECT**，不 await、不进 greenlet → **永远不会抛 `MissingGreenlet`**（那是 `AsyncSession` 专属错误）。真实后果：

- **正常情况**：冗余的同步阻塞重查（PK/列已经 load 过一次）→ 性能损耗，非崩溃
- **异常情况**：若 session 处于 aborted 状态（某查询报错导致 PG 事务进入 `current transaction is aborted`），后续 SQL 抛 `InternalError` 直到 rollback —— **这才是 `ai.py` 现有 `_uid/_pid` 预取防御真正防的东西**，与 expire 无关

### 2.3 假设 3：「memories.py 风险在 agent loop 内」→ 实际是独立 API 路由

`memories.py:56/71` 是**独立 HTTP 路由**（`POST /memories`、`PATCH /memories/{id}`），不在 agent loop 路径内。方案 B（独立 session 隔离 agent loop）和方案 C（agent loop 内手动预取）**完全覆盖不到**这两处。

---

## 3. 方案评估

### 方案 A：全局 `expire_on_commit=False`（**推荐**）

**改动**：`database.py:10` 加 `expire_on_commit=False` + 补 `memories.py` 两处 `db.refresh()`。

| 维度 | 评估 |
|---|---|
| 真实风险面 | **2 处**（memories.py 时间戳），远小于任务预设的 92 处 |
| 收益 | 根治所有 expire 隐患；agent loop 的 undefended 访问（`ai.py:239/245/254/255/347/350`）不再触发冗余 lazy load |
| 代价 | memories.py 补 2 行 refresh；全量回归验证 |

### 方案 B：agent loop 用独立 session（不推荐）

工具内 commit 用独立 session，主 session 不被污染。

| 维度 | 评估 |
|---|---|
| 真实问题匹配 | **过度设计**——前提（async 抛 MissingGreenlet）被调研推翻 |
| 覆盖面 | 治不到 memories.py 的 2 处（独立 API 路由） |
| 代价 | 引入「工具事务与主请求事务分离」的一致性窗口；save_memory 是真实业务写入，不能像 C2 那样用 SAVEPOINT（需真正持久化） |

### 方案 C：agent loop 内手动预取（不推荐）

commit 前预取所有属性，commit 后只用预取值。

| 维度 | 评估 |
|---|---|
| 覆盖面 | 治不到 memories.py 的 2 处 |
| 健壮性 | 脆弱，靠人工保证每个访问点都预取，容易漏；保留全局 `expire_on_commit=True` = 把炸弹留给未来所有新代码 |

### 决策：方案 A

调研显示方案 A 的真实改动面（1 行配置 + 2 处 refresh）**远小于**任务预设，而 B/C 既过度设计又覆盖不全。

---

## 4. 详细设计

### 4.1 改动 1：全局配置

`apps/api/app/core/database.py:10`：

```python
# 前
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# 后
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True,
    expire_on_commit=False,
)
```

**配套注释**（解释 why + 何时需手动 refresh，防止未来回归）：

```python
# expire_on_commit=False：commit 后不再 expire session 内所有 ORM 对象。
# 依据全量审计（89 处 commit）：44 处紧跟 db.refresh()（显式重查，免疫此配置），
# 其余多读客户端生成的 UUID 主键（commit 前已知）或 Python 端赋值字段。
# **唯一需注意**：读 server-default 列（如 created_at/updated_at 这类 DB 端赋值时间戳）
# 时，commit 后必须显式 db.refresh() 才能拿到 DB 生成的值——否则读到 None/旧值。
# 见 docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md。
```

### 4.2 改动 2 & 3：修复 memories.py 两处 STALE-RISK

`apps/api/app/api/memories.py:56-57`（create_memory）：

```python
db.commit()
db.refresh(mem)   # expire_on_commit=False：需显式刷新拿 server_default 的 created_at/updated_at
return _to_out(mem)
```

`apps/api/app/api/memories.py:71-72`（update_memory）：

```python
db.commit()
db.refresh(mem)   # 同上，updated_at 有 onupdate 也需刷新
return _to_out(mem)
```

**依据**：`UserMemory` 用 `TimestampMixin`（`app/models/base.py`），`created_at`/`updated_at` 均为 `server_default=func.now()`，`updated_at` 另有 `onupdate=func.now()`。这些值由 DB 端赋值，`expire_on_commit=False` 下 commit 后不会自动重查 → 必须显式 `refresh`。这与代码库既有 `commit(); refresh(obj)` 模式（44 处）完全一致，memories.py 只是漏了。

**注**：现有 `memories.py:28-29` 的 `if mem.created_at else ""` 兜底是为 SQLite 测试库写的（SQLite 不执行 PG server_default）。补 refresh 后，PG 生产环境返回真实时间戳；SQLite 测试环境 refresh 后仍为 None，由兜底转空串（行为不变，测试不破）。

### 4.3 明确不改的点（审计确认）

| 位置 | 原因 |
|---|---|
| `ai.py:239/245/254/255/347/350`（agent loop undefended 访问） | 读的都是客户端 UUID / Python 端 status，切 `expire_on_commit=False` 后**反而更安全**（不再触发冗余 lazy load），无需改 |
| `ai.py:275-280/369-374`（`_uid/_pid` 预取防御） | 保留。它防的是 **aborted 事务**（`InternalError`），与 expire 无关，仍有价值 |
| `ai.py:198`（user_msg commit） | 之后读的 `conv.id` 是客户端 UUID，安全 |
| `services/` 层其余 44 处 `commit()+refresh()` | 已有 refresh，免疫配置变更 |

---

## 5. 测试策略

### 5.1 关键约束（来自 conftest.py 调研）

1. **测试 session 独立于生产 SessionLocal**：`tests/conftest.py` 的 `db_session`（:141）和 `app_obj`（:150）各自 `sessionmaker(bind=engine)` 新建，**不引用 `SessionLocal`**。改 `database.py:10` 不影响测试 session 的 expire 行为 → 配置生效需**直接断言生产 `SessionLocal`**。
2. **SQLite 不执行 PG server_default**：`created_at`/`updated_at` 在 SQLite 测试库 INSERT 后为 None。因此 memories.py 的 refresh 修复**无法在测试层验证 PG 时间戳**——这是测试基础设施限制，非修复缺陷（PG 验证见 §5.5 手动验证）。

### 5.2 第 1 层：配置 + 行为单元测试（新增 `tests/test_c1_expire_on_commit.py`）

| 测试 | 验证目标 | 方法 |
|---|---|---|
| `test_sessionlocal_expire_on_commit_is_false` | 配置生效 | 断言 `SessionLocal.kw["expire_on_commit"] is False`（生产 sessionmaker） |
| `test_orm_object_not_expired_after_commit` | commit 后对象不 expire | 测试内 `sessionmaker(bind=engine, expire_on_commit=False)` 自建 session（模拟生产配置），`add+commit` 一个对象，用 `event.listen(engine, "before_cursor_execute")` 计数：commit 后访问已设属性，断言**无额外 SELECT**。对照组用 `expire_on_commit=True` 验证计数 >0（证明测试有效） |
| `test_client_uuid_pk_readable_after_commit` | 客户端 UUID 主键 commit 后可读 | commit 后读 `obj.id`，断言等于原 UUID（验证 ai.py 依赖此行为安全） |

### 5.3 第 2 层：agent loop 回归测试（新增到 `tests/test_agent_loop_expire.py`）

| 测试 | 验证目标 | 方法 |
|---|---|---|
| `test_save_memory_commit_then_read_section_attr` | save_memory commit 后读 `section.id`/`section.status` 不触发 lazy load / 不抛 InternalError | 构造 section + user → 调 `save_memory` 工具（走 service 层 create_memory + 工具内 commit）→ 访问 `section.id`/`section.status` → 断言无异常、值正确 |

> 这类测试的价值是**防回归**——若未来有人误把配置改回 True，测试暴露「commit 后访问触发 lazy load / aborted session 上抛 InternalError」。

### 5.4 第 3 层：全量回归（SQLite，主证据）

`cd apps/api && uv run pytest`，baseline ~776 测试全绿。这是「切全局配置不破坏现有行为」的主证据。

### 5.5 第 4 层：真实 PG 手动验证（非自动化，记录在 spec）

测试基础设施不支持 PG（SQLite 内存库 + StaticPool），故 PG 验证手动执行、不进 CI：

1. 起 PG：`docker compose up -d postgres` + `cd apps/api && uv run alembic upgrade head`
2. 创建用户 + 登录，打开一个 section 的对话
3. 对话中触发 agent 调 save_memory（如说「记住我喜欢简洁的写作风格」），确认工具返回「已保存」
4. **继续对话**（关键：这是 commit 后访问 ORM 的路径），确认**不报 InternalError**、无阻塞重查
5. 手动 `POST /memories` 创建记忆，确认响应的 `created_at`/`updated_at` **非空**（验证 refresh 修复在 PG 生效）

---

## 6. 验收标准

- [ ] `database.py:10` 的 `SessionLocal` 设 `expire_on_commit=False`，附注释
- [ ] `memories.py:56/71` 两处补 `db.refresh(mem)`
- [ ] 新增测试 `tests/test_c1_expire_on_commit.py`（配置断言 + 行为测试）通过
- [ ] 新增/补充 agent loop 回归测试通过
- [ ] 全量 `uv run pytest`（776+）全绿
- [ ] 真实 PG 手动验证（§5.5）对话 + memories API 无 InternalError、时间戳非空

---

## 7. 已知限制与后续

1. **测试基础设施无法验证 PG server_default**：memories.py 的 refresh 修复在 SQLite 测试库上无可见效果（时间戳本就是 None → 兜底空串）。PG 行为靠 §5.5 手动验证。若未来引入 PG CI（testcontainer），应补 `created_at`/`updated_at` 非空断言。
2. **agent loop 的 aborted 事务风险未根治**：本 spec 只解决 expire；`ai.py` 的 `_uid/_pid` 预取防御针对的是 aborted 事务（某查询报错后 session 进入 `current transaction is aborted`），属另一类问题（事务隔离），不在 C1 范围。若后续要彻底治理，参考 C2 的 SAVEPOINT 思路评估。
3. **编码规范**：建议在 `AGENTS.md` 或 `GOTCHAS.md` 增补一条——「commit 后若需读 server-default 列（时间戳/自增 ID），必须 `db.refresh()`；读客户端 UUID/Python 赋值字段则无需」。防止未来新代码踩坑。

---

## 8. 关键文件清单

| 类型 | 路径 | 操作 |
|---|---|---|
| 配置 | `apps/api/app/core/database.py:10` | 加 `expire_on_commit=False` + 注释 |
| 修复 | `apps/api/app/api/memories.py:56` | commit 后补 `db.refresh(mem)` |
| 修复 | `apps/api/app/api/memories.py:71` | commit 后补 `db.refresh(mem)` |
| 新增测试 | `apps/api/tests/test_c1_expire_on_commit.py` | 配置断言 + 行为测试 |
| 新增测试 | `apps/api/tests/test_agent_loop_expire.py` | agent loop commit 后访问回归 |
