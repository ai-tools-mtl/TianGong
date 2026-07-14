# 计划 12：异步解析恢复 + 项目级技能开关 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现两个相互独立的 P0 验收点：(A) 模板上传改真异步执行 + 启动恢复扫描 + 解析任务状态查询接口；(B) AgentSkill 项目级技能开关模型 + skill_service + 编排层接入 + 项目技能配置 API + 前端技能抽屉。

**Architecture:**
- **Feature A（异步解析）**：`run_parse_job` 的 `db: Session` 来自请求作用域，响应返回即关闭，后台任务无法继续使用。新增 `run_parse_job_standalone(job_id, upload_dir)` 包装函数，自开 `SessionLocal()`；upload 端点改用 FastAPI `BackgroundTasks` 调度它并立即返回 202；`on_startup()` 增加幂等的恢复扫描（processing / 老于 10 分钟的 pending 重新入队）；新增 `GET /templates/parse-jobs/{job_id}` 状态查询；前端上传后轮询直到 completed 再刷新列表。
- **Feature B（技能开关）**：新增 `AgentSkill` 表（`project_id` 维度，非 user_id）；`BUILTIN_SKILLS` 系统级定义置于代码常量；`skill_service.list_skills` 做 builtin LEFT JOIN project_rows（缺行=默认启用），**不**在项目创建时预置行；`is_skill_enabled` 用于编排层短路；orchestrator `_retrieve_knowledge` 与 review_service 分别按 `rag_search` / `rubric_review` / `consistency_check` 短路；API 与前端在项目详情页提供技能开关抽屉。

**Tech Stack:** FastAPI（BackgroundTasks）· SQLAlchemy 2.0 · Alembic · Next.js 16 · React 19 · TanStack Query

**关联 spec：** [P0 验收补全迭代设计](../specs/2026-07-14-p0-completion-iteration.md) §6（Feature A）、§7.4（Feature B）

---

## 文件结构

| 文件 | 责任 | 操作 |
|---|---|---|
| `apps/api/app/services/parse_service.py` | 解析服务，新增 `run_parse_job_standalone` 与 `recover_pending_jobs` | 修改 |
| `apps/api/app/api/templates.py` | upload 改 BackgroundTasks + 202；新增 parse-job 状态端点 | 修改 |
| `apps/api/app/main.py` | `on_startup()` 增加恢复扫描调用 | 修改 |
| `apps/api/app/schemas/template.py` | 新增 `ParseJobOut` schema | 修改 |
| `apps/api/app/models/agent_skill.py` | `AgentSkill` ORM（project_id 维度） | 新建 |
| `apps/api/app/models/__init__.py` | 注册 AgentSkill | 修改 |
| `apps/api/alembic/versions/<new>_create_agent_skills.py` | 创建 agent_skills 表 | 新建 |
| `apps/api/app/services/seed_service.py` | 新增 `BUILTIN_SKILLS` 常量 | 修改 |
| `apps/api/app/services/skill_service.py` | list_skills / is_skill_enabled / set_skill | 新建 |
| `apps/api/app/api/skills.py` | GET/PUT 项目技能端点 | 新建 |
| `apps/api/app/api/router.py` | 注册 skills 路由 | 修改 |
| `apps/api/app/schemas/skill.py` | SkillOut / SkillUpdate schema | 新建 |
| `apps/api/app/ai/orchestrator.py` | `_retrieve_knowledge` 按 rag_search 短路 | 修改 |
| `apps/api/app/services/review_service.py` | rubric_review / consistency_check 短路 | 修改 |
| `apps/api/tests/test_templates.py` | 异步 upload + 恢复扫描 + parse-job 状态测试 | 修改 |
| `apps/api/tests/test_skills.py` | skill_service + API 测试 | 新建 |
| `apps/web/src/components/template-manager.tsx` | 上传后轮询 parse-job 状态 | 修改 |
| `apps/web/src/components/skills-dialog.tsx` | 项目技能开关抽屉 | 新建 |
| `apps/web/src/app/(app)/projects/[id]/page.tsx` | 顶栏加 "技能" 按钮 | 修改 |
| `apps/web/src/lib/api.ts` | listSkills / updateSkill / getParseJob | 修改 |
| `apps/web/src/lib/queries.ts` | useSkills / useUpdateSkill | 修改 |
| `apps/web/src/types/api.ts` | AgentSkill / ParseJob 类型 | 修改 |

---

## Task 1：parse_service 新增 standalone 包装与恢复扫描

**Files:**
- Modify: `apps/api/app/services/parse_service.py`
- Test: `apps/api/tests/test_templates.py`

**背景：** 现状 `run_parse_job(db, job_id, upload_dir)` 接收外部 session。BackgroundTasks 在响应返回后才执行，此时请求 session 已关闭。需要新增不依赖外部 session 的包装。

- [ ] **Step 1: 写失败测试 — `run_parse_job_standalone` 自开 session 完成解析**

打开 `apps/api/tests/test_templates.py`，在文件末尾追加。

> **关键测试技巧：** `run_parse_job_standalone` 内部会 `from app.core.database import SessionLocal` 然后 `SessionLocal()`。生产环境指向配置的 DB，但测试库是临时内存 SQLite。所以测试里要 `monkeypatch.setattr(app.core.database, "SessionLocal", TestingSession)`，把 SessionLocal 重定向到绑定测试 engine 的 sessionmaker。注意 standalone 是**函数内 import**，所以必须 patch 模块对象（`app.core.database.SessionLocal`）而非 import 后的引用。

```python
def test_run_parse_job_standalone_opens_own_session(
    client, app_obj, engine, registered_user, db_session, monkeypatch
):
    """run_parse_job_standalone 自开 session 完成解析，不依赖请求 db。"""
    import io
    import uuid
    from docx import Document

    from sqlalchemy.orm import sessionmaker

    # 让 standalone 内部 `from app.core.database import SessionLocal` 拿到的指向测试库
    from app.core import database as db_module
    TestingSession = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestingSession)

    from app.services import parse_service

    # 登录（registered_user fixture 已建用户）
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })

    # 构造最小 docx 文件
    doc = Document()
    doc.add_heading("发明名称", level=1)
    doc.add_paragraph("正文")
    buf = io.BytesIO()
    doc.save(buf)
    file_bytes = buf.getvalue()

    job = parse_service.create_parse_job(
        db_session, user_id=uuid.UUID(registered_user["id"]),
        filename="x.docx", file_bytes=file_bytes, upload_dir="uploads",
    )
    job_id = str(job.id)

    # 调用 standalone：不传 db，函数自己开 session
    parse_service.run_parse_job_standalone(job_id, "uploads")

    # 用全新 session 验证持久化
    from app.models import ParseJob
    fresh_session = TestingSession()
    try:
        fresh = fresh_session.get(ParseJob, job_id)
        assert fresh.status == "completed"
        assert fresh.template_id is not None
    finally:
        fresh_session.close()
```

- [ ] **Step 2: 运行测试，确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py::test_run_parse_job_standalone_opens_own_session -v
```
Expected: FAIL with `AttributeError: module 'app.services.parse_service' has no attribute 'run_parse_job_standalone'`

- [ ] **Step 3: 实现 `run_parse_job_standalone`**

打开 `apps/api/app/services/parse_service.py`，在文件末尾追加：

```python
def run_parse_job_standalone(job_id: str, upload_dir: str) -> None:
    """供 BackgroundTasks 调用：自开 session 执行解析。

    BackgroundTasks 在响应返回后才执行，此时请求作用域的 session 已关闭，
    因此必须自己开一个独立 session（详见设计 P0 #6）。
    """
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        run_parse_job(db, job_id=job_id, upload_dir=upload_dir)
    finally:
        db.close()
```

- [ ] **Step 4: 运行测试，确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py::test_run_parse_job_standalone_opens_own_session -v
```
Expected: PASS

- [ ] **Step 5: 写恢复扫描失败测试 — recover_pending_jobs 重新入队 processing 与过期 pending**

继续在 `apps/api/tests/test_templates.py` 末尾追加：

```python
def test_recover_pending_jobs_reenqueues_processing_and_stale_pending(db_session, monkeypatch):
    """启动恢复扫描：processing 直接重跑，pending 超 10 分钟重跑，新 pending 不动。"""
    from datetime import datetime, timedelta, timezone

    from app.core import database as db_module
    from sqlalchemy.orm import sessionmaker

    # 让 standalone/recover 内部的 SessionLocal 指向测试库
    TestingSession = sessionmaker(bind=db_session.bind)
    monkeypatch.setattr(db_module, "SessionLocal", TestingSession)

    from app.core.security import hash_password
    from app.models import ParseJob, User
    from app.services import parse_service

    # 造一个真实用户（ParseJob.user_id 外键约束）
    u = User(email="rec@example.com", password_hash=hash_password("Pass1234!"), name="R")
    db_session.add(u)
    db_session.commit()

    now = datetime.now(timezone.utc)
    j_processing = ParseJob(user_id=u.id, source_path="uploads/x.docx", status="processing")
    j_stale = ParseJob(user_id=u.id, source_path="uploads/y.docx", status="pending")
    j_stale.created_at = now - timedelta(minutes=20)  # 超时 pending
    j_fresh = ParseJob(user_id=u.id, source_path="uploads/z.docx", status="pending")
    # j_fresh.created_at 用 server 默认 now，未超时
    for j in (j_processing, j_stale, j_fresh):
        db_session.add(j)
    db_session.commit()

    # 用 fake_run 标记被调度的 job_id，避免真去解析不存在的 docx
    reloaded: list[str] = []

    def fake_run(db, job_id, upload_dir):
        reloaded.append(str(job_id))
        j = db.get(ParseJob, job_id)
        if j and j.status != "completed":
            j.status = "processing"
            db.commit()

    monkeypatch.setattr(parse_service, "run_parse_job", fake_run)

    n = parse_service.recover_pending_jobs("uploads")
    assert n == 2  # processing + stale pending 被重入队
    assert str(j_processing.id) in reloaded
    assert str(j_stale.id) in reloaded
    assert str(j_fresh.id) not in reloaded  # 新 pending 不动
```

- [ ] **Step 6: 运行确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py::test_recover_pending_jobs_reenqueues_processing_and_stale_pending -v
```
Expected: FAIL with `AttributeError: module 'app.services.parse_service' has no attribute 'recover_pending_jobs'`

- [ ] **Step 7: 实现 `recover_pending_jobs`**

在 `apps/api/app/services/parse_service.py` 末尾追加：

```python
def recover_pending_jobs(upload_dir: str, stale_minutes: int = 10) -> int:
    """启动恢复扫描：重启后重入队两类孤儿任务。

    1) status="processing" —— 上次崩溃中断（崩溃时正在跑）。
    2) status="pending" 且 created_at 早于 stale_minutes 分钟前 —— 队列卡住。

    run_parse_job 自带幂等：若状态已是 completed 则跳过。
    返回重新入队的任务数。
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_, select

    from app.core.database import SessionLocal
    from app.models import ParseJob

    db = SessionLocal()
    count = 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        stmt = select(ParseJob).where(
            or_(
                ParseJob.status == "processing",
                (ParseJob.status == "pending") & (ParseJob.created_at < cutoff),
            )
        )
        jobs = list(db.scalars(stmt))
        for j in jobs:
            run_parse_job(db, str(j.id), upload_dir)
            count += 1
    finally:
        db.close()
    return count
```

- [ ] **Step 8: 运行确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py::test_recover_pending_jobs_reenqueues_processing_and_stale_pending -v
```
Expected: PASS

- [ ] **Step 9: 提交**

```bash
cd apps/api && git add app/services/parse_service.py tests/test_templates.py && git commit -m "feat(plan12): add run_parse_job_standalone + recover_pending_jobs"
```

---

## Task 2：upload 端点改 BackgroundTasks + 202

**Files:**
- Modify: `apps/api/app/api/templates.py`
- Modify: `apps/api/tests/test_templates.py`

**背景：** 当前 upload 端点在响应前同步 `run_parse_job`，注释 "MVP 同步执行（后续可改 BackgroundTasks）"。改为创建 job → 调度后台 → 立即返回 202 status=processing。

- [ ] **Step 1: 写失败测试 — upload 立即返回 202 且 status=processing**

在 `apps/api/tests/test_templates.py` 末尾追加：

```python
def test_upload_returns_202_processing_and_background_completes(
    client, app_obj, engine, registered_user, monkeypatch
):
    """upload 立即返回 202 + status=processing，BackgroundTasks 在响应后跑完。"""
    import io
    from docx import Document

    from sqlalchemy.orm import sessionmaker

    # BackgroundTask 会调 run_parse_job_standalone → 内部 `from app.core.database import SessionLocal`
    # 必须 patch 它指向测试库，否则 standalone 开的 session 会连到配置的生产 DB（读不到刚写的 job）
    from app.core import database as db_module
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine))

    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })

    doc = Document()
    doc.add_heading("发明名称", level=1)
    doc.add_paragraph("正文")
    buf = io.BytesIO()
    doc.save(buf)

    res = client.post(
        "/api/v1/templates",
        files={"file": ("test.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert res.status_code == 202
    data = res.json()
    assert data["status"] == "processing"
    assert "parse_job_id" in data
```

> **为何失败：** 当前 upload 端点同步调 `run_parse_job`（不通过 standalone），响应返回时 status 已是 "completed"。改造后 upload 只调度 background task，立即返回 "processing"。TestClient 默认在响应返回后才同步执行 background task，所以断言响应体里的 "processing" 是在 task 跑之前抓到的，符合预期。

- [ ] **Step 2: 运行确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py::test_upload_returns_202_processing_and_background_completes -v
```
Expected: FAIL with `assert 'processing' == 'completed'`（旧逻辑同步执行完返回 completed）

- [ ] **Step 3: 修改 upload 端点**

打开 `apps/api/app/api/templates.py`，把 import 部分改为：

```python
from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy.orm import Session
```

把 `upload` 函数（第 29-45 行）整段替换为：

```python
@router.post("", response_model=dict, status_code=202)
async def upload(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传 Word 文件创建模板。返回 202，解析在后台执行；前端轮询 parse-job 状态。"""
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise ValidationError("仅支持 .docx 文件")
    content = await file.read()
    job = parse_service.create_parse_job(
        db, user_id=current_user.id, filename=file.filename,
        file_bytes=content, upload_dir="uploads",
    )
    background_tasks.add_task(parse_service.run_parse_job_standalone, str(job.id), "uploads")
    return {"parse_job_id": str(job.id), "status": "processing"}
```

> **关键点：** `BackgroundTasks` 必须作为类型注解的参数出现（FastAPI 自动注入），不要加 `Depends`。TestClient 会在响应返回后同步等待 background task 完成（标准行为），所以测试断言 "completed-after-background" 可通过查询 parse-job 端点验证（见 Task 4）。

- [ ] **Step 4: 运行确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py::test_upload_returns_202_processing_and_background_completes -v
```
Expected: PASS

- [ ] **Step 5: 跑全量模板测试确保未破坏**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py -v
```
Expected: 全部 PASS（含原有 list/get/delete 测试）

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/api/templates.py tests/test_templates.py && git commit -m "feat(plan12): upload endpoint uses BackgroundTasks, returns 202 processing"
```

---

## Task 3：on_startup 接入恢复扫描

**Files:**
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/tests/test_templates.py`

**背景：** `main.py` 当前 `on_startup()` 只打日志。需要加恢复扫描调用，扫描失败不应阻塞启动（用 try/except 包裹）。

- [ ] **Step 1: 写失败测试 — 启动扫描被调用且不抛错**

在 `apps/api/tests/test_templates.py` 末尾追加：

```python
def test_on_startup_calls_recovery_without_crashing(monkeypatch):
    """on_startup 调用 recover_pending_jobs，即使抛错也不阻塞。"""
    called = {"n": 0}

    def fake_recover(upload_dir, stale_minutes=10):
        called["n"] += 1
        return 0

    from app.services import parse_service
    monkeypatch.setattr(parse_service, "recover_pending_jobs", fake_recover)

    from app.main import on_startup
    on_startup()  # 不应抛异常

    assert called["n"] == 1
```

```python
def test_on_startup_swallows_recovery_error(monkeypatch):
    """恢复扫描抛错时 on_startup 仍正常返回（不阻塞启动）。"""
    def boom(upload_dir, stale_minutes=10):
        raise RuntimeError("db down")

    from app.services import parse_service
    monkeypatch.setattr(parse_service, "recover_pending_jobs", boom)

    from app.main import on_startup
    on_startup()  # 不应抛异常
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
cd apps/api && uv run pytest "tests/test_templates.py::test_on_startup_calls_recovery_without_crashing" "tests/test_templates.py::test_on_startup_swallows_recovery_error" -v
```
Expected: FAIL with `assert 0 == 1`（on_startup 没调 recover）或抛 RuntimeError

- [ ] **Step 3: 修改 `on_startup`**

打开 `apps/api/app/main.py`，把 `on_startup` 整段替换为：

```python
@app.on_event("startup")
def on_startup():
    loguru.logger.info("TianGong API 启动")
    # 恢复扫描：重启后重入队崩溃中断的解析任务（设计 P0 #6）
    try:
        from app.services.parse_service import recover_pending_jobs
        n = recover_pending_jobs("uploads")
        if n:
            loguru.logger.info(f"恢复扫描：重新入队 {n} 个解析任务")
    except Exception as e:
        loguru.logger.exception(f"恢复扫描失败（不阻塞启动）：{e}")
```

- [ ] **Step 4: 运行确认通过**

Run:
```bash
cd apps/api && uv run pytest "tests/test_templates.py::test_on_startup_calls_recovery_without_crashing" "tests/test_templates.py::test_on_startup_swallows_recovery_error" -v
```
Expected: 两个测试 PASS

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/main.py tests/test_templates.py && git commit -m "feat(plan12): wire recover_pending_jobs into on_startup"
```

---

## Task 4：parse-job 状态查询端点

**Files:**
- Modify: `apps/api/app/schemas/template.py`
- Modify: `apps/api/app/api/templates.py`
- Modify: `apps/api/tests/test_templates.py`

**背景：** 前端需要轮询接口判断解析完成。`GET /templates/parse-jobs/{job_id}` 返回 `{status, template_id?, error_message?}`。

- [ ] **Step 1: 写失败测试 — 查询 parse-job 状态**

在 `apps/api/tests/test_templates.py` 末尾追加：

```python
def test_get_parse_job_status_completed(client, app_obj, engine, registered_user, monkeypatch):
    """GET /templates/parse-jobs/{id} 返回 status + template_id。"""
    import io
    from docx import Document

    from sqlalchemy.orm import sessionmaker

    # BackgroundTask 跑 standalone，需 patch SessionLocal 指向测试库
    from app.core import database as db_module
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine))

    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })

    doc = Document()
    doc.add_heading("发明名称", level=1)
    doc.add_paragraph("正文")
    buf = io.BytesIO()
    doc.save(buf)

    upload_res = client.post(
        "/api/v1/templates",
        files={"file": ("t.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    job_id = upload_res.json()["parse_job_id"]

    res = client.get(f"/api/v1/templates/parse-jobs/{job_id}")
    assert res.status_code == 200
    data = res.json()
    # TestClient 在响应返回后同步等待 background task 完成，故通常为 completed
    assert data["status"] == "completed"
    assert data["template_id"] is not None


def test_get_parse_job_not_found(client, registered_user):
    """不存在的 job_id 返回 404。"""
    import uuid
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.get(f"/api/v1/templates/parse-jobs/{uuid.uuid4()}")
    assert res.status_code == 404


def test_get_parse_job_unauthenticated(client):
    """未登录返回 401。"""
    import uuid
    res = client.get(f"/api/v1/templates/parse-jobs/{uuid.uuid4()}")
    assert res.status_code == 401
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py::test_get_parse_job_status_completed tests/test_templates.py::test_get_parse_job_not_found -v
```
Expected: FAIL with `404` 或路由不存在

- [ ] **Step 3: 新增 `ParseJobOut` schema**

打开 `apps/api/app/schemas/template.py`，在文件末尾追加：

```python
class ParseJobOut(BaseModel):
    """解析任务状态查询。"""
    id: str
    status: str
    template_id: str | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: 实现 parse-job 端点**

打开 `apps/api/app/api/templates.py`，在 `upload` 函数之后、`get_one` 之前插入：

```python
@router.get("/parse-jobs/{job_id}", response_model=ParseJobOut)
def get_parse_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询解析任务状态（前端轮询用）。"""
    from app.models import ParseJob
    job = db.get(ParseJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise NotFoundError("解析任务不存在")
    return ParseJobOut(
        id=str(job.id), status=job.status,
        template_id=str(job.template_id) if job.template_id else None,
        error_message=job.error_message,
    )
```

并把 import 行更新为：

```python
from app.core.exceptions import NotFoundError, ValidationError
from app.schemas.template import ParseJobOut, TemplateOut, TemplateSummary
```

> **关键：** 路由 `parse-jobs/{job_id}` 必须放在 `{template_id}` 之前，否则 FastAPI 会把 "parse-jobs" 当作 template_id 匹配。当前代码中 `{template_id}` 用了 `<template_id>` 路径段，"parse-jobs" 会被它吃掉。把 parse-jobs 端点放在 `get_one` 前面即可解决。

- [ ] **Step 5: 运行确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py::test_get_parse_job_status_completed tests/test_templates.py::test_get_parse_job_not_found tests/test_templates.py::test_get_parse_job_unauthenticated -v
```
Expected: 全部 PASS

- [ ] **Step 6: 跑全量模板测试确保路由顺序无误**

Run:
```bash
cd apps/api && uv run pytest tests/test_templates.py -v
```
Expected: 全部 PASS

- [ ] **Step 7: 提交**

```bash
cd apps/api && git add app/api/templates.py app/schemas/template.py tests/test_templates.py && git commit -m "feat(plan12): add GET /templates/parse-jobs/{job_id} status endpoint"
```

---

## Task 5：前端上传后轮询 parse-job 状态

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/components/template-manager.tsx`

**背景：** 现状 `template-manager.tsx` 的 `handleUpload` 直接 `await api.uploadTemplate(file)` 后 toast 成功并 refetch。异步后 upload 立即返回 processing，需要在 toast 后轮询直到 completed/failed 再刷新列表。

- [ ] **Step 1: 在 `api.ts` 添加 `getParseJob` 方法**

打开 `apps/web/src/lib/api.ts`，在 `uploadTemplate` 方法块（约 71-84 行）之后插入：

```typescript
  getParseJob: (jobId: string) =>
    request<{ id: string; status: string; template_id: string | null; error_message: string | null }>(`/templates/parse-jobs/${jobId}`),
```

- [ ] **Step 2: 在 `api.ts` 修改 `uploadTemplate` 返回 parse_job_id**

`uploadTemplate` 当前直接 `return res.json()`。无需改返回值结构，因为它直接透传后端 JSON（含 parse_job_id + status）。保持不变。

- [ ] **Step 3: 修改 `template-manager.tsx` 加轮询**

打开 `apps/web/src/components/template-manager.tsx`，把整个文件替换为：

```tsx
'use client'

import { Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { useTemplates } from '@/lib/queries'
import type { TemplateSummary } from '@/types/api'

const POLL_INTERVAL_MS = 1500
const POLL_MAX_ATTEMPTS = 40 // 60s 上限

async function pollParseJob(jobId: string): Promise<'completed' | 'failed'> {
  for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
    const job = await api.getParseJob(jobId)
    if (job.status === 'completed') return 'completed'
    if (job.status === 'failed') return 'failed'
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
  return 'failed'
}

export function TemplateManager() {
  const { data, isLoading, refetch } = useTemplates()
  const templates: TemplateSummary[] = data ?? []
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const { parse_job_id } = await api.uploadTemplate(file)
      toast.info('模板已上传，正在解析...')
      const result = await pollParseJob(parse_job_id)
      if (result === 'completed') {
        toast.success('模板解析成功')
        refetch()
      } else {
        toast.error('模板解析失败')
      }
    } catch {
      toast.error('上传失败')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <PageShell>
      <PageHeader title="模板管理" description="上传 Word 模板定义交底书章节结构">
        <input
          ref={fileRef}
          type="file"
          accept=".docx"
          onChange={handleUpload}
          className="hidden"
        />
        <Button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="gap-1.5"
        >
          <Upload className="size-3.5" />
          {uploading ? '解析中...' : '上传 Word 模板'}
        </Button>
      </PageHeader>

      <div className="py-6">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">加载中...</p>
        ) : templates.length === 0 ? (
          <div className="rounded-lg border border-dashed p-12 text-center text-sm text-muted-foreground">
            还没有模板，上传一个 Word 模板开始
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {templates.map((t) => (
              <Card key={t.id}>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-[15px]">
                    {t.name}
                    {t.is_system && <Badge variant="secondary">系统</Badge>}
                    {t.is_default && <Badge>默认</Badge>}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-[12px] text-muted-foreground">
                    {t.section_count} 个章节
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
```

- [ ] **Step 4: 类型检查与构建**

Run:
```bash
cd apps/web && npx tsc --noEmit
```
Expected: 无错误

Run:
```bash
cd apps/web && npm run build
```
Expected: 构建成功

- [ ] **Step 5: 提交**

```bash
cd apps/web && git add src/lib/api.ts src/components/template-manager.tsx && git commit -m "feat(plan12): poll parse-job status after upload before refreshing templates"
```

---

## Task 6：AgentSkill 模型 + 注册 + Alembic 迁移

**Files:**
- Create: `apps/api/app/models/agent_skill.py`
- Modify: `apps/api/app/models/__init__.py`
- Create: `apps/api/alembic/versions/<new>_create_agent_skills.py`
- Test: `apps/api/tests/test_skills.py`

**背景：** 新表 `agent_skills`，按 `project_id` 维度（每行=某项目对某技能的覆盖；缺行=使用 builtin 默认）。`config` 存 JSON（如未来 rubric_review 的阈值）。

- [ ] **Step 1: 新建 `apps/api/tests/test_skills.py` 写失败测试 — AgentSkill 字段与注册**

```python
"""AgentSkill 模型与 skill_service 测试。"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db():
    """独立 sqlite 内存库（service 层测试用）。"""
    from app.models import Base
    eng = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    session = S()
    yield session
    session.close()


def test_agent_skill_model_basic_fields(db):
    """AgentSkill 表存在且字段齐全。"""
    from app.core.security import hash_password
    from app.models import AgentSkill, Project, User

    u = User(email="s@b.com", password_hash=hash_password("Pass1234!"), name="S")
    db.add(u)
    db.commit()
    p = Project(user_id=u.id, title="项目")
    db.add(p)
    db.commit()

    skill = AgentSkill(
        project_id=p.id,
        skill_key="rag_search",
        enabled=False,
        config={"k": 5},
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)

    assert skill.id is not None
    assert skill.project_id == p.id
    assert skill.skill_key == "rag_search"
    assert skill.enabled is False
    assert skill.config == {"k": 5}
    assert skill.created_at is not None


def test_agent_skill_importable_from_models():
    """AgentSkill 在 app.models 命名空间里。"""
    from app.models import AgentSkill
    assert AgentSkill.__tablename__ == "agent_skills"
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py -v
```
Expected: FAIL with `ImportError: cannot import name 'AgentSkill'`

- [ ] **Step 3: 新建 `AgentSkill` 模型**

创建 `apps/api/app/models/agent_skill.py`：

```python
import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class AgentSkill(Base, IdMixin, TimestampMixin):
    """项目级技能开关。每行 = 某项目对某 builtin 技能的覆盖；缺行 = 用默认。"""
    __tablename__ = "agent_skills"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    skill_key: Mapped[str] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
```

- [ ] **Step 4: 注册 AgentSkill 到 `app.models`**

打开 `apps/api/app/models/__init__.py`，完整替换为：

```python
from app.models.base import Base, JSONType
from app.models.agent_skill import AgentSkill
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.message import Message
from app.models.parse_job import ParseJob
from app.models.project import Project
from app.models.review_record import ReviewRecord
from app.models.review_rubric import ReviewRubric
from app.models.section import Section
from app.models.section_version import SectionVersion
from app.models.system_setting import SystemSetting
from app.models.template import Template
from app.models.user import User
from app.models.user_llm_config import UserLLMConfig

__all__ = [
    "Base", "JSONType",
    "User", "Project", "SystemSetting",
    "Template", "ParseJob", "Section", "SectionVersion", "Message",
    "KnowledgeChunk", "ReviewRubric", "ReviewRecord", "UserLLMConfig",
    "AgentSkill",
]
```

- [ ] **Step 5: 运行确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py -v
```
Expected: 两个测试 PASS（测试 fixture 用 `Base.metadata.create_all` 自动建 agent_skills 表）

- [ ] **Step 6: 生成 Alembic 迁移**

Run:
```bash
cd apps/api && uv run alembic revision --autogenerate -m "create agent skills"
```
Expected: 在 `alembic/versions/` 生成新文件 `<revision>_create_agent_skills.py`

打开生成的文件，确认 `down_revision` 指向当前 head（用 `alembic heads` 查看；执行 plan9 后可能是 plan9 的 revision，未执行则是 `a20f16f0da4e`），且 `upgrade()` 含（`config` 列类型应自动识别为 `postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite')`，与 review_records 表的 JSONType 列一致）：

```python
def upgrade() -> None:
    op.create_table('agent_skills',
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('skill_key', sa.String(length=50), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_skills_project_id'), 'agent_skills', ['project_id'], unique=False)
```

> **检查清单：** (1) `down_revision` 指向当前 head；(2) `config` 列是 JSONB(JSON sqlite 变体) 而非纯 sa.JSON；(3) `project_id` 外键 ondelete='CASCADE'；(4) `ix_agent_skills_project_id` 索引存在。如自生成内容与上面不一致，手工改对。SQLite 测试不经 Alembic（用 `Base.metadata.create_all`），但生产 PG 需要正确。

- [ ] **Step 7: 验证迁移可应用**

Run:
```bash
cd apps/api && uv run alembic upgrade head
```
Expected: 成功（如果当前 DB 已是最新 head，会无操作或仅应用新迁移）

Run:
```bash
cd apps/api && uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: 降级再升级都成功

- [ ] **Step 8: 提交**

```bash
cd apps/api && git add app/models/agent_skill.py app/models/__init__.py alembic/versions/ tests/test_skills.py && git commit -m "feat(plan12): add AgentSkill model + migration"
```

---

## Task 7：BUILTIN_SKILLS 常量 + skill_service

**Files:**
- Modify: `apps/api/app/services/seed_service.py`
- Create: `apps/api/app/services/skill_service.py`
- Modify: `apps/api/tests/test_skills.py`

**背景：** 设计 7.4 的 5 个 builtin skills 作为代码常量（不在 DB）。`skill_service` 做 builtin LEFT JOIN 项目行：缺行 = builtin 默认值。

- [ ] **Step 1: 写失败测试 — skill_service 三函数**

在 `apps/api/tests/test_skills.py` 末尾追加：

```python
def _make_project(db):
    from app.core.security import hash_password
    from app.models import Project, User
    u = User(email="s2@b.com", password_hash=hash_password("Pass1234!"), name="S2")
    db.add(u)
    db.commit()
    p = Project(user_id=u.id, title="P")
    db.add(p)
    db.commit()
    return p


def test_list_skills_merges_builtin_with_overrides(db):
    """list_skills 返回 5 个 builtin，缺行 = default_enabled。"""
    from app.services import skill_service

    p = _make_project(db)
    skills = skill_service.list_skills(db, project_id=p.id)

    assert len(skills) == 5
    keys = {s["skill_key"] for s in skills}
    assert keys == {"rag_search", "rubric_review", "consistency_check", "quality_report", "prior_art_hint"}
    # 默认全部启用
    assert all(s["enabled"] is True for s in skills)
    # name/description 来自 builtin
    rag = next(s for s in skills if s["skill_key"] == "rag_search")
    assert rag["name"] == "知识库检索"
    assert rag["is_builtin"] is True


def test_list_skills_applies_project_override(db):
    """项目里禁用某技能，list_skills 反映禁用状态。"""
    from app.models import AgentSkill
    from app.services import skill_service

    p = _make_project(db)
    db.add(AgentSkill(project_id=p.id, skill_key="rag_search", enabled=False))
    db.commit()

    skills = skill_service.list_skills(db, project_id=p.id)
    rag = next(s for s in skills if s["skill_key"] == "rag_search")
    assert rag["enabled"] is False
    assert rag["is_overridden"] is True


def test_is_skill_enabled_missing_row_returns_default(db):
    """缺行 = default_enabled（rag_search 默认 True）。"""
    from app.services import skill_service

    p = _make_project(db)
    assert skill_service.is_skill_enabled(db, project_id=p.id, skill_key="rag_search") is True


def test_is_skill_enabled_respects_override(db):
    """覆盖禁用后 is_skill_enabled 返回 False。"""
    from app.models import AgentSkill
    from app.services import skill_service

    p = _make_project(db)
    db.add(AgentSkill(project_id=p.id, skill_key="rag_search", enabled=False))
    db.commit()
    assert skill_service.is_skill_enabled(db, project_id=p.id, skill_key="rag_search") is False


def test_set_skill_creates_or_updates_row(db):
    """set_skill 幂等：首次创建行，再次更新。"""
    from app.models import AgentSkill
    from app.services import skill_service

    p = _make_project(db)

    # 首次：创建覆盖行
    skill_service.set_skill(db, project_id=p.id, skill_key="rag_search", enabled=False, config={"k": 3})
    rows = db.query(AgentSkill).filter_by(project_id=p.id, skill_key="rag_search").all()
    assert len(rows) == 1
    assert rows[0].enabled is False
    assert rows[0].config == {"k": 3}

    # 再次：更新同一行
    skill_service.set_skill(db, project_id=p.id, skill_key="rag_search", enabled=True, config={"k": 5})
    rows = db.query(AgentSkill).filter_by(project_id=p.id, skill_key="rag_search").all()
    assert len(rows) == 1
    assert rows[0].enabled is True
    assert rows[0].config == {"k": 5}


def test_set_skill_unknown_key_raises(db):
    """未知 skill_key 抛 ValidationError。"""
    import pytest
    from app.core.exceptions import ValidationError
    from app.services import skill_service

    p = _make_project(db)
    with pytest.raises(ValidationError):
        skill_service.set_skill(db, project_id=p.id, skill_key="not_a_real_skill", enabled=False)
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py -v -k "list_skills or is_skill_enabled or set_skill"
```
Expected: FAIL with `ImportError: No module named 'app.services.skill_service'`

- [ ] **Step 3: 在 `seed_service.py` 添加 `BUILTIN_SKILLS`**

打开 `apps/api/app/services/seed_service.py`，在 `DEFAULT_STRUCTURE` 常量定义之前（文件顶部 import 之后，约第 5 行处）插入：

```python
# 系统内置 Agent 技能定义（设计 7.4）。name/description/is_builtin 仅存在代码中。
BUILTIN_SKILLS = [
    {
        "skill_key": "rag_search",
        "name": "知识库检索",
        "description": "撰写/审查时检索用户知识库",
        "default_enabled": True,
    },
    {
        "skill_key": "rubric_review",
        "name": "Rubric 审查",
        "description": "按 Rubric 逐维度评分",
        "default_enabled": True,
    },
    {
        "skill_key": "consistency_check",
        "name": "自一致性校验",
        "description": "关键评分多次取均值",
        "default_enabled": True,
    },
    {
        "skill_key": "quality_report",
        "name": "质量报告",
        "description": "生成结构化审查报告",
        "default_enabled": True,
    },
    {
        "skill_key": "prior_art_hint",
        "name": "现有技术提示",
        "description": "撰写背景技术时提示检索方向（占位，检索在 P1）",
        "default_enabled": True,
    },
]
```

- [ ] **Step 4: 新建 `apps/api/app/services/skill_service.py`**

```python
"""技能开关服务（设计 7.4）：builtin 定义 + 项目覆盖。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models import AgentSkill
from app.services.seed_service import BUILTIN_SKILLS

# 索引化便于查询
_BUILTIN_BY_KEY = {s["skill_key"]: s for s in BUILTIN_SKILLS}


def list_skills(db: Session, *, project_id) -> list[dict]:
    """返回项目下所有技能：builtin LEFT JOIN 项目覆盖行。

    缺行 = 用 builtin 默认值（enabled=default_enabled, is_overridden=False）。
    """
    pid = project_id
    overrides = {
        row.skill_key: row
        for row in db.scalars(
            select(AgentSkill).where(AgentSkill.project_id == pid)
        )
    }
    result = []
    for builtin in BUILTIN_SKILLS:
        key = builtin["skill_key"]
        row = overrides.get(key)
        if row is not None:
            enabled = row.enabled
            config = row.config
            is_overridden = True
        else:
            enabled = builtin["default_enabled"]
            config = None
            is_overridden = False
        result.append({
            "skill_key": key,
            "name": builtin["name"],
            "description": builtin["description"],
            "enabled": enabled,
            "config": config,
            "is_builtin": True,
            "is_overridden": is_overridden,
        })
    return result


def is_skill_enabled(db: Session, *, project_id, skill_key: str) -> bool:
    """单个技能是否启用。未知 key 视为默认 True（不阻断主流程）。"""
    if skill_key not in _BUILTIN_BY_KEY:
        return True
    row = db.scalar(
        select(AgentSkill).where(
            AgentSkill.project_id == project_id,
            AgentSkill.skill_key == skill_key,
        )
    )
    if row is None:
        return _BUILTIN_BY_KEY[skill_key]["default_enabled"]
    return row.enabled


def set_skill(
    db: Session, *, project_id, skill_key: str, enabled: bool, config: dict | None = None,
) -> AgentSkill:
    """设置项目级技能开关（幂等：存在则更新，不存在则创建）。"""
    if skill_key not in _BUILTIN_BY_KEY:
        raise ValidationError(f"未知技能：{skill_key}")
    row = db.scalar(
        select(AgentSkill).where(
            AgentSkill.project_id == project_id,
            AgentSkill.skill_key == skill_key,
        )
    )
    if row is None:
        row = AgentSkill(
            project_id=project_id, skill_key=skill_key,
            enabled=enabled, config=config,
        )
        db.add(row)
    else:
        row.enabled = enabled
        row.config = config
    db.commit()
    db.refresh(row)
    return row
```

- [ ] **Step 5: 运行确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py -v
```
Expected: 全部 8 个测试 PASS

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/services/seed_service.py app/services/skill_service.py tests/test_skills.py && git commit -m "feat(plan12): add BUILTIN_SKILLS constant + skill_service"
```

---

## Task 8：orchestrator 按 rag_search 短路

**Files:**
- Modify: `apps/api/app/ai/orchestrator.py`
- Modify: `apps/api/tests/test_skills.py`

**背景：** 设计 7.4 "禁用的技能不参与编排"。`_retrieve_knowledge` 在调 `retrieve()` 前先查 `is_skill_enabled(project_id, "rag_search")`，禁用则直接返回 None。

- [ ] **Step 1: 写失败测试 — rag_search 禁用时不检索**

在 `apps/api/tests/test_skills.py` 末尾追加：

```python
def test_retrieve_knowledge_skipped_when_rag_search_disabled(db):
    """rag_search 禁用时，orchestrator._retrieve_knowledge 直接返回 None，不调 retrieve。"""
    from app.models import AgentSkill, Section
    from app.services import skill_service

    p = _make_project(db)
    # 禁用 rag_search
    db.add(AgentSkill(project_id=p.id, skill_key="rag_search", enabled=False))
    db.commit()
    section = Section(
        project_id=p.id, template_section_id="t1", order=1, key="name",
        title="发明名称", status="empty",
    )
    db.add(section)
    db.commit()

    retrieve_called = {"n": 0}

    import app.rag.retriever as retriever_mod
    original_retrieve = retriever_mod.retrieve

    def fake_retrieve(*args, **kwargs):
        retrieve_called["n"] += 1
        return []

    retriever_mod.retrieve = fake_retrieve
    try:
        from app.ai.orchestrator import _retrieve_knowledge
        result = _retrieve_knowledge(db, section, "查询")
        assert result is None
        assert retrieve_called["n"] == 0
    finally:
        retriever_mod.retrieve = original_retrieve


def test_retrieve_knowledge_runs_when_rag_search_enabled(db):
    """rag_search 启用时，_retrieve_knowledge 进入原检索逻辑。"""
    from app.models import Section

    p = _make_project(db)
    section = Section(
        project_id=p.id, template_section_id="t1", order=1, key="name",
        title="发明名称", status="empty",
    )
    db.add(section)
    db.commit()

    retrieve_called = {"n": 0}

    import app.rag.retriever as retriever_mod
    original_retrieve = retriever_mod.retrieve

    def fake_retrieve(*args, **kwargs):
        retrieve_called["n"] += 1
        return []

    retriever_mod.retrieve = fake_retrieve
    try:
        from app.ai.orchestrator import _retrieve_knowledge
        _retrieve_knowledge(db, section, "查询")
        # retrieve 被调用了（或异常降级路径，但至少进了检索分支）
        assert retrieve_called["n"] == 1
    finally:
        retriever_mod.retrieve = original_retrieve
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py::test_retrieve_knowledge_skipped_when_rag_search_disabled -v
```
Expected: FAIL with `assert 1 == 0`（当前 _retrieve_knowledge 无条件检索）

- [ ] **Step 3: 修改 `_retrieve_knowledge`**

打开 `apps/api/app/ai/orchestrator.py`，把 `_retrieve_knowledge` 函数（约 41-62 行）整段替换为：

```python
def _retrieve_knowledge(db, section: Section, query: str) -> list[dict] | None:
    """检索用户知识库（RAG）。禁用技能短路；异常降级为空。"""
    try:
        from sqlalchemy import select

        from app.models import Project
        from app.rag.retriever import retrieve
        from app.services.skill_service import is_skill_enabled

        project = db.scalar(select(Project).where(Project.id == section.project_id))
        if project is None:
            return None
        # 设计 7.4：rag_search 禁用则不检索
        if not is_skill_enabled(db, project_id=project.id, skill_key="rag_search"):
            return None
        results = retrieve(db, user_id=project.user_id, query=query)
        return [
            {
                "content": r.content,
                "section_key": r.source_section_key,
                "project_title": r.project_title,
            }
            for r in results
        ]
    except Exception:
        return None
```

- [ ] **Step 4: 运行确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py::test_retrieve_knowledge_skipped_when_rag_search_disabled tests/test_skills.py::test_retrieve_knowledge_runs_when_rag_search_enabled -v
```
Expected: 两个测试 PASS

- [ ] **Step 5: 跑原有 RAG/context 测试确保未破坏**

Run:
```bash
cd apps/api && uv run pytest tests/test_rag.py tests/test_context.py -v
```
Expected: 全部 PASS（这些测试不依赖 rag_search 开关，因为缺行=默认启用）

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/ai/orchestrator.py tests/test_skills.py && git commit -m "feat(plan12): short-circuit RAG when rag_search disabled"
```

---

## Task 9：review_service 按 rubric_review / consistency_check 短路

**Files:**
- Modify: `apps/api/app/services/review_service.py`
- Modify: `apps/api/tests/test_skills.py`

**背景：** 设计 7.4 "禁用的技能不参与编排"。`run_review`：
- `rubric_review` 禁用 → 整个评分循环跳过（维度评分不跑，但仍 persist 一条空记录或返回错误）。设计选择：rubric_review 禁用则抛 ValidationError("已禁用 Rubric 审查")，让用户主动改回来。
- `consistency_check` 禁用 → `CONSISTENCY_RUNS = 1`（只跑一次）。

- [ ] **Step 1: 写失败测试 — rubric_review 禁用时 run_review 抛错**

在 `apps/api/tests/test_skills.py` 末尾追加：

```python
def test_run_review_raises_when_rubric_review_disabled(db):
    """rubric_review 禁用时 run_review 拒绝执行。"""
    import pytest
    from app.core.exceptions import ValidationError
    from app.models import AgentSkill, Section

    p = _make_project(db)
    db.add(AgentSkill(project_id=p.id, skill_key="rubric_review", enabled=False))
    db.commit()
    # 加一个章节（review 需要）
    s = Section(project_id=p.id, template_section_id="t1", order=1, key="name",
                title="发明名称", status="empty")
    db.add(s)
    db.commit()

    from app.services import review_service
    with pytest.raises(ValidationError):
        review_service.run_review(db, user_id=p.user_id, project_id=str(p.id))


def test_run_review_uses_one_run_when_consistency_check_disabled(db, monkeypatch):
    """consistency_check 禁用时 _score_dimension 只调一次（CONSISTENCY_RUNS=1）。"""
    from app.models import Section

    p = _make_project(db)
    # 禁用 consistency_check
    from app.models import AgentSkill
    db.add(AgentSkill(project_id=p.id, skill_key="consistency_check", enabled=False))
    db.commit()
    # 加章节
    s = Section(project_id=p.id, template_section_id="t1", order=1, key="name",
                title="发明名称", status="confirmed")
    s.content = {"text": "some content"}
    db.add(s)
    db.commit()

    # mock _score_dimension 计数
    calls = {"n": 0}
    original = None

    import app.services.review_service as rs
    def counting_score(criterion, sections):
        calls["n"] += 1
        return (80, "ev", "sug")

    monkeypatch.setattr(rs, "_score_dimension", counting_score)
    # mock get_effective_rubric 返回 1 个 criterion，避免依赖种子
    def fake_rubric(d, user_id):
        class FakeRubric:
            criteria = [{"key": "k", "name": "N", "weight": 1.0}]
        return FakeRubric()
    monkeypatch.setattr(rs, "get_effective_rubric", fake_rubric)

    rs.run_review(db, user_id=p.user_id, project_id=str(p.id))

    # 1 维度 × 1 run（consistency_check 禁用）= 1 次
    assert calls["n"] == 1
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py::test_run_review_raises_when_rubric_review_disabled tests/test_skills.py::test_run_review_uses_one_run_when_consistency_check_disabled -v
```
Expected: FAIL（第一个：run_review 不抛错；第二个：calls=2 而非 1）

- [ ] **Step 3: 修改 `run_review`**

打开 `apps/api/app/services/review_service.py`，在文件顶部 import 之后（约第 19 行）追加常量逻辑前，先更新 import：

```python
from app.services.skill_service import is_skill_enabled
```

把 `CONSISTENCY_RUNS = 2` 那行替换为：

```python
CONSISTENCY_RUNS = 2  # 自一致性：每维度评分次数（consistency_check 启用）
```

然后把 `run_review` 函数体在 `# ① load` 之前插入技能检查，并在循环里动态用 `runs`：

完整替换 `run_review` 函数为：

```python
def run_review(db: Session, *, user_id, project_id: str) -> ReviewRecord:
    """执行完整审查。"""
    try:
        pid = uuid_mod.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")

    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    # 设计 7.4：rubric_review 禁用则拒绝审查
    if not is_skill_enabled(db, project_id=pid, skill_key="rubric_review"):
        raise ValidationError("已禁用 Rubric 审查技能")
    # consistency_check 禁用则每维度只跑一次
    runs = CONSISTENCY_RUNS if is_skill_enabled(
        db, project_id=pid, skill_key="consistency_check"
    ) else 1

    # ① load
    rubric = get_effective_rubric(db, user_id=user_id)
    sections = _get_section_texts(db, pid)
    last_review = _get_last_review(db, pid)

    # ② score（Rubric 驱动 + 自一致性）
    dimension_scores = []
    for criterion in rubric.criteria:
        scores = []
        last_evidence = ""
        last_suggestion = ""
        for _ in range(runs):
            score, evidence, suggestion = _score_dimension(criterion, sections)
            scores.append(score)
            last_evidence = evidence
            last_suggestion = suggestion
        avg_score = sum(scores) / len(scores)
        dimension_scores.append({
            "key": criterion["key"],
            "name": criterion["name"],
            "weight": criterion["weight"],
            "score": round(avg_score),
            "run_scores": scores,
            "evidence": last_evidence,
            "suggestion": last_suggestion,
        })

    # ③ aggregate
    total = sum(d["score"] * d["weight"] for d in dimension_scores)
    resolved, remaining = _compare_issues(dimension_scores, last_review)

    # ④ persist
    record = ReviewRecord(
        project_id=pid,
        user_id=user_id,
        rubric_snapshot=rubric.criteria,
        round=(last_review.round + 1) if last_review else 1,
        total_score=round(total),
        previous_score=last_review.total_score if last_review else None,
        dimension_scores=dimension_scores,
        resolved_issues=resolved,
        remaining_issues=remaining,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
```

并更新顶部 import（加上 ValidationError）：

```python
from app.core.exceptions import NotFoundError, ValidationError
```

- [ ] **Step 4: 运行确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py::test_run_review_raises_when_rubric_review_disabled tests/test_skills.py::test_run_review_uses_one_run_when_consistency_check_disabled -v
```
Expected: 两个测试 PASS

- [ ] **Step 5: 跑原有 review 测试确保未破坏**

Run:
```bash
cd apps/api && uv run pytest tests/test_rag.py -v -k review; cd apps/api && uv run pytest tests/ -v -k review
```
Expected: 已有 review 测试全部 PASS（技能默认启用，行为不变）

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/services/review_service.py tests/test_skills.py && git commit -m "feat(plan12): short-circuit review based on rubric_review/consistency_check skills"
```

---

## Task 10：项目技能 API（GET / PUT）

**Files:**
- Create: `apps/api/app/schemas/skill.py`
- Create: `apps/api/app/api/skills.py`
- Modify: `apps/api/app/api/router.py`
- Modify: `apps/api/tests/test_skills.py`

**背景：** 两个端点，都走 `get_current_user` + 资源级所有权校验（用 `project_service.get_project`，非本人项目 → 404）。

- [ ] **Step 1: 写失败测试 — API 端点**

在 `apps/api/tests/test_skills.py` 末尾追加 API 测试（用 client + registered_user fixture）：

```python
def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })


def test_api_list_skills_returns_builtin_defaults(client, registered_user):
    """GET /projects/{id}/skills 返回 5 个 builtin 全启用。"""
    _login(client, registered_user)
    res = client.post("/api/v1/projects", json={"title": "P"})
    project_id = res.json()["id"]

    res = client.get(f"/api/v1/projects/{project_id}/skills")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 5
    assert all(s["enabled"] is True for s in data)
    assert all(s["is_builtin"] is True for s in data)


def test_api_update_skill_persists_override(client, registered_user):
    """PUT /projects/{id}/skills/{key} 持久化覆盖。"""
    _login(client, registered_user)
    project_id = client.post("/api/v1/projects", json={"title": "P"}).json()["id"]

    res = client.put(
        f"/api/v1/projects/{project_id}/skills/rag_search",
        json={"enabled": False, "config": {"k": 3}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["skill_key"] == "rag_search"
    assert body["enabled"] is False
    assert body["config"] == {"k": 3}

    # 再查 GET 确认持久化
    res = client.get(f"/api/v1/projects/{project_id}/skills")
    rag = next(s for s in res.json() if s["skill_key"] == "rag_search")
    assert rag["enabled"] is False
    assert rag["is_overridden"] is True


def test_api_update_unknown_skill_returns_422(client, registered_user):
    """未知 skill_key 返回 422。"""
    _login(client, registered_user)
    project_id = client.post("/api/v1/projects", json={"title": "P"}).json()["id"]
    res = client.put(
        f"/api/v1/projects/{project_id}/skills/nonexistent",
        json={"enabled": False},
    )
    assert res.status_code == 422


def test_api_list_skills_other_users_project_returns_404(client, registered_user, db_session):
    """非本人项目返回 404。"""
    from app.core.security import hash_password
    from app.models import User
    from app.services import project_service as ps

    other = User(email="other@b.com", password_hash=hash_password("Pass1234!"), name="O")
    db_session.add(other)
    db_session.commit()
    other_project = ps.create_project(db_session, user=other, title="别人的")

    _login(client, registered_user)
    res = client.get(f"/api/v1/projects/{other_project.id}/skills")
    assert res.status_code == 404


def test_api_skills_unauthenticated_returns_401(client, registered_user):
    """未登录返回 401。"""
    _login(client, registered_user)
    project_id = client.post("/api/v1/projects", json={"title": "P"}).json()["id"]
    # 清 cookie 模拟未登录
    client.cookies.clear()
    res = client.get(f"/api/v1/projects/{project_id}/skills")
    assert res.status_code == 401
```

- [ ] **Step 2: 运行确认失败**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py -v -k "api_"
```
Expected: FAIL with 404（路由不存在）

- [ ] **Step 3: 新建 `apps/api/app/schemas/skill.py`**

```python
from pydantic import BaseModel


class SkillOut(BaseModel):
    """技能定义 + 项目覆盖状态。"""
    skill_key: str
    name: str
    description: str
    enabled: bool
    config: dict | None = None
    is_builtin: bool
    is_overridden: bool


class SkillUpdate(BaseModel):
    enabled: bool
    config: dict | None = None
```

- [ ] **Step 4: 新建 `apps/api/app/api/skills.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.skill import SkillOut, SkillUpdate
from app.services import project_service, skill_service

router = APIRouter(tags=["skills"])


@router.get("/projects/{project_id}/skills", response_model=list[SkillOut])
def list_skills(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出项目所有技能（builtin + 覆盖）。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    rows = skill_service.list_skills(db, project_id=project.id)
    return [SkillOut(**r) for r in rows]


@router.put("/projects/{project_id}/skills/{skill_key}", response_model=SkillOut)
def update_skill(
    project_id: str,
    skill_key: str,
    payload: SkillUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新项目技能开关。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    skill_service.set_skill(
        db, project_id=project.id, skill_key=skill_key,
        enabled=payload.enabled, config=payload.config,
    )
    # 用 list_skills 取合并后的视图（含 builtin name/description）
    row = next(
        r for r in skill_service.list_skills(db, project_id=project.id)
        if r["skill_key"] == skill_key
    )
    return SkillOut(**row)
```

- [ ] **Step 5: 注册路由**

打开 `apps/api/app/api/router.py`，完整替换为：

```python
from fastapi import APIRouter

from app.api import (
    admin, ai, auth, export, health, knowledge, projects, review, sections, skills, templates, versions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(templates.router)
api_router.include_router(sections.router)
api_router.include_router(ai.router)
api_router.include_router(versions.router)
api_router.include_router(export.router)
api_router.include_router(knowledge.router)
api_router.include_router(review.router)
api_router.include_router(admin.router)
api_router.include_router(skills.router)
api_router.include_router(health.router)
```

- [ ] **Step 6: 运行确认通过**

Run:
```bash
cd apps/api && uv run pytest tests/test_skills.py -v -k "api_"
```
Expected: 全部 5 个 API 测试 PASS

- [ ] **Step 7: 提交**

```bash
cd apps/api && git add app/schemas/skill.py app/api/skills.py app/api/router.py tests/test_skills.py && git commit -m "feat(plan12): add GET/PUT /projects/{id}/skills endpoints"
```

---

## Task 11：前端 — 技能类型 + API + queries + 技能抽屉

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`
- Create: `apps/web/src/components/skills-dialog.tsx`
- Modify: `apps/web/src/app/(app)/projects/[id]/page.tsx`

**背景：** 项目详情页顶栏加 "技能" 按钮 → 打开 Dialog，列出 5 个 builtin 技能 + 开关。无现成 Switch 组件，用 Button 做切换（点一下 enabled/disabled 切换）。

- [ ] **Step 1: 添加类型**

打开 `apps/web/src/types/api.ts`，在文件末尾追加：

```typescript
// ── 技能开关 ──

export interface AgentSkill {
  skill_key: string
  name: string
  description: string
  enabled: boolean
  config: Record<string, unknown> | null
  is_builtin: boolean
  is_overridden: boolean
}

// ── 解析任务 ──

export interface ParseJob {
  id: string
  status: string
  template_id: string | null
  error_message: string | null
}
```

- [ ] **Step 2: 添加 API 方法**

打开 `apps/web/src/lib/api.ts`，在 `setDefaultTemplate` 之后（约 89-90 行附近）追加：

```typescript
  // ── 技能开关 ──
  listSkills: (projectId: string) =>
    request<import('@/types/api').AgentSkill[]>(`/projects/${projectId}/skills`),

  updateSkill: (projectId: string, skillKey: string, data: { enabled: boolean; config?: object | null }) =>
    request<import('@/types/api').AgentSkill>(`/projects/${projectId}/skills/${skillKey}`, {
      method: 'PUT', body: JSON.stringify(data),
    }),
```

- [ ] **Step 3: 添加 queries hook**

打开 `apps/web/src/lib/queries.ts`，在 `queryKeys` 对象里追加：

```typescript
  skills: (id: string) => ['skills', id] as const,
```

在文件末尾追加：

```typescript
// ── 技能 ──
export function useSkills(projectId: string) {
  return useQuery<import('@/types/api').AgentSkill[]>({
    queryKey: queryKeys.skills(projectId),
    queryFn: () => api.listSkills(projectId),
    enabled: !!projectId,
  })
}

export function useUpdateSkill(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ skillKey, enabled, config }: { skillKey: string; enabled: boolean; config?: object | null }) =>
      api.updateSkill(projectId, skillKey, { enabled, config }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills(projectId) }),
  })
}
```

- [ ] **Step 4: 新建技能抽屉组件**

创建 `apps/web/src/components/skills-dialog.tsx`：

```tsx
'use client'

import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useSkills, useUpdateSkill } from '@/lib/queries'
import type { AgentSkill } from '@/types/api'

interface SkillsDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SkillsDialog({ projectId, open, onOpenChange }: SkillsDialogProps) {
  const { data, isLoading } = useSkills(projectId)
  const updateSkill = useUpdateSkill(projectId)
  const skills: AgentSkill[] = data ?? []

  function handleToggle(skill: AgentSkill) {
    updateSkill.mutate(
      { skillKey: skill.skill_key, enabled: !skill.enabled },
      {
        onSuccess: () => toast.success(`${skill.enabled ? '已禁用' : '已启用'} ${skill.name}`),
        onError: () => toast.error('更新失败'),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>项目技能</DialogTitle>
          <DialogDescription>
            为本项目配置 Agent 技能组合。不同专利可启用不同技能。
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            加载中...
          </div>
        ) : (
          <div className="space-y-2">
            {skills.map((s) => (
              <div
                key={s.skill_key}
                className="flex items-center justify-between rounded-lg border p-3"
              >
                <div className="min-w-0 flex-1 pr-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{s.name}</span>
                    {s.is_overridden && (
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        已覆盖
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {s.description}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant={s.enabled ? 'default' : 'outline'}
                  onClick={() => handleToggle(s)}
                  disabled={updateSkill.isPending}
                  className="h-7 shrink-0 px-3 text-xs"
                >
                  {s.enabled ? '已启用' : '已禁用'}
                </Button>
              </div>
            ))}
            {skills.length === 0 && (
              <p className="py-4 text-center text-sm text-muted-foreground">
                暂无可用技能
              </p>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 5: 在项目详情页顶栏添加 "技能" 按钮**

打开 `apps/web/src/app/(app)/projects/[id]/page.tsx`，按下列改动：

1) 顶部 import 段（约第 3 行）替换为：

```tsx
import { CheckCircle2, Eye, History, PanelLeft, PanelRight, Search, Sparkles } from 'lucide-react'
```

2) 在 import 列表里（约第 11 行 `VersionDrawer` 之后）加：

```tsx
import { SkillsDialog } from '@/components/skills-dialog'
```

3) 在组件内 `const [versionOpen, setVersionOpen] = useState(false)` 之后（约第 27 行）加：

```tsx
  const [skillsOpen, setSkillsOpen] = useState(false)
```

4) 在顶栏按钮组里，"审查" 按钮（`<a href={`/projects/${projectId}/review`}>...</a>` 包裹的 Button）的闭合 `</Button>` 之后、`导出 Word` Button 之前插入：

```tsx
              <Button
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5"
                onClick={() => setSkillsOpen(true)}
              >
                <Sparkles className="size-3.5" />
                技能
              </Button>
```

即插入后按钮顺序为：预览 → 审查 → **技能** → 导出 Word → 版本 → 确认完成。

5) 在 `{current && (<VersionDrawer .../>)}` 块之后（约第 218 行附近）追加：

```tsx
      <SkillsDialog
        projectId={projectId}
        open={skillsOpen}
        onOpenChange={setSkillsOpen}
      />
```

- [ ] **Step 6: 类型检查与构建**

Run:
```bash
cd apps/web && npx tsc --noEmit
```
Expected: 无错误

Run:
```bash
cd apps/web && npm run build
```
Expected: 构建成功

- [ ] **Step 7: 提交**

```bash
cd apps/web && git add src/types/api.ts src/lib/api.ts src/lib/queries.ts src/components/skills-dialog.tsx "src/app/(app)/projects/[id]/page.tsx" && git commit -m "feat(plan12): add project skills dialog with toggle UI"
```

---

## Task 12：全量验证

**Files:** — （只跑测试 + 构建）

- [ ] **Step 1: 后端全量测试**

Run:
```bash
cd apps/api && uv run pytest -v
```
Expected: 全部 PASS（含新增的 `test_templates.py` 异步/恢复/状态测试、`test_skills.py` 全套；原有测试无回归）

> 若某测试 FAIL，回到对应 Task 修复，不要跳过。

- [ ] **Step 2: 后端 lint / 类型检查（如配置）**

Run:
```bash
cd apps/api && uv run ruff check app/ 2>&1 | head -20
```
Expected: 无 error（warning 可忽略）。如 ruff 未配置则跳过本步。

- [ ] **Step 3: 前端类型检查 + 构建**

Run:
```bash
cd apps/web && npx tsc --noEmit && npm run build
```
Expected: 类型无错误，构建成功

- [ ] **Step 4: Alembic 迁移可双向应用**

Run:
```bash
cd apps/api && uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: 降级与升级都成功

- [ ] **Step 5: 手动冒烟（可选）— 启动后端验证启动日志含恢复扫描**

Run（另开终端）:
```bash
cd apps/api && uv run uvicorn app.main:app --reload
```
Expected: 启动日志中可见 `TianGong API 启动`；如 DB 中有孤儿任务可见 `恢复扫描：重新入队 N 个解析任务`，否则无该行（正常）。

- [ ] **Step 6: 最终提交（如有未提交改动）**

```bash
cd "G:\03-Personal-Projects\TianGong" && git status
```
Expected: clean working tree（前面每个 Task 已提交）

如发现遗漏改动：
```bash
git add -A && git commit -m "feat(plan12): final verification fixes"
```

---

## 自检清单（实施完成后人工对照）

- **Feature A（异步解析）**
  - [ ] upload 端点立即返回 202 + `{parse_job_id, status: "processing"}`
  - [ ] `run_parse_job_standalone` 自开 SessionLocal（不依赖请求 db）
  - [ ] `on_startup()` 调 `recover_pending_jobs` 且扫描异常不阻塞启动
  - [ ] 恢复扫描覆盖 processing + 老 pending（>10min）两类
  - [ ] `GET /templates/parse-jobs/{job_id}` 返回 status + template_id + error_message
  - [ ] 前端上传后轮询直到 completed 再刷新模板列表
  - [ ] run_parse_job 幂等（completed 状态跳过）

- **Feature B（技能开关）**
  - [ ] AgentSkill 表存在，`project_id` 维度（非 user_id）
  - [ ] BUILTIN_SKILLS 5 个常量在代码里（不在 DB）
  - [ ] skill_service.list_skills 做 builtin LEFT JOIN（缺行=默认）
  - [ ] 项目创建时不预置技能行
  - [ ] orchestrator `_retrieve_knowledge` 按 rag_search 短路
  - [ ] review_service 按 rubric_review（拒绝）/ consistency_check（runs=1）短路
  - [ ] GET /projects/{id}/skills + PUT /projects/{id}/skills/{key}
  - [ ] 端点走 get_current_user + 所有权校验
  - [ ] 前端项目详情页顶栏有 "技能" 按钮，点击弹 Dialog
  - [ ] Dialog 列出 5 个技能 + 可切换 enabled

---

**实施备注：**

1. **Task 顺序**：Feature A（Task 1-5）与 Feature B（Task 6-11）相互独立，可任意穿插；Task 12 必须最后跑。
2. **Alembic head**：当前文档记录 head 为 `a20f16f0da4e`，但若 plan9 已实施则会更新。Task 6 Step 6 用 `alembic revision --autogenerate` 自动检测当前 head，无需手工指定。
3. **测试 DB 隔离**：`test_skills.py` 的 `db` fixture 用 `Base.metadata.create_all` 自动建 `agent_skills` 表；`test_templates.py` 沿用 `conftest.py` 的 `engine` fixture（排除 knowledge_chunks），agent_skills 会自动包含。
4. **BackgroundTasks 测试**：FastAPI TestClient 在响应返回后会同步执行完所有 background tasks，因此断言 "completed-after-background" 可在同一个 testclient 调用链里通过状态查询端点验证。
