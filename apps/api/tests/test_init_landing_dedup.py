# apps/api/tests/test_init_landing_dedup.py
"""P0-1：init generate 双击重复落地的去重逻辑测试。

防线（z1a2b3c4d5e6 起）：init_orchestrator 对 conversation 行 FOR UPDATE 后，
create_project(commit=False) 并入同一事务，行锁持有到「project_id 标记已落地」
commit 完成——并发请求串行化，第二个拿锁后见 project_id 非空即拒绝。
历史上的部分唯一索引 uq_conversations_init_one_unlanded 已删：它按 user_id
限制「未落地 init 会话最多 1 条」，与多会话设计冲突（用户已有未落地会话时
点「+ 新对话」直接 500，2026-08-19 线上报障）。

SQLite 测试库不支持 FOR UPDATE（静默忽略），故此处聚焦测「逻辑路径」：

1. astream_init_generate 在 conversation.project_id 已非空时（并发竞态中锁内
   二次检查命中）抛 ConflictError，且不再调 create_project。
2. assistant.py generate 端点的 AppError 分支把 ConflictError 转成
   {code: "conflict"} SSE error 事件，而非走 llm_error 通用提示。
3. 正常落地走单事务：create_project 收到 commit=False，project 建成与
   project_id 标记同 commit 落库。
4. 多会话并存合法：同一 user 可有多条未落地 init 会话（索引删除的回归锚点）。

FOR UPDATE 的真实并发串行化靠 PG 集成验证，此处不覆盖。
"""
import asyncio
import uuid as _uuid

import pytest

from app.core.exceptions import ConflictError


_SENTINEL_PROJECT = _uuid.UUID("11111111-1111-1111-1111-111111111111")


def _make_init_conv(db_session, user_obj, *, project_id=None):
    """构造一个 init 会话（kind=init, user_id 填好）。project_id 传 UUID 或 None。"""
    from app.models import Conversation, KIND_INIT

    conv = Conversation(
        kind=KIND_INIT, user_id=user_obj.id, title="测试会话", project_id=project_id,
    )
    db_session.add(conv)
    db_session.commit()
    return conv


def _fake_llm_config():
    """最小可用的 ResolvedChatConfig mock（resolve_chat_config 的替代返回值）。"""
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.model = "glm-4.7"
    cfg.base_url = "http://x"
    cfg.api_key = "x"
    cfg.source = "global"
    return cfg


def test_init_generate_raises_conflict_when_already_landed(db_session, registered_user, monkeypatch):
    """astream_init_generate 在会话已落地时抛 ConflictError，不调 create_project。

    模拟并发竞态：请求 A 已完成落地（project_id 已填），请求 B 进入
    astream_init_generate 时锁内二次检查命中 → ConflictError。
    SQLite 无 FOR UPDATE，但二次检查逻辑在 is_postgres=True 分支内不依赖锁本身。
    """
    from app.ai import init_orchestrator as mod
    from app.core import database as db_mod
    from app.models import User
    from app.services import project_service

    user_obj = db_session.get(User, _uuid.UUID(registered_user["id"]))
    conv = _make_init_conv(db_session, user_obj, project_id=_SENTINEL_PROJECT)

    # 让二次检查分支生效（SQLite 默认 is_postgres=False 会跳过 FOR UPDATE 块）
    monkeypatch.setattr(db_mod, "is_postgres", lambda db=None: True)

    called = {"create_project": False}

    def _fail_create(*a, **k):
        called["create_project"] = True
        raise AssertionError("create_project 不应在已落地时被调用")

    monkeypatch.setattr(project_service, "create_project", _fail_create)

    async def _run():
        async for _ in mod.astream_init_generate(
            db_session, conv, [], user_obj, llm_config=_fake_llm_config(),
        ):
            pass

    with pytest.raises(ConflictError, match="正在落地"):
        asyncio.run(_run())

    assert not called["create_project"], "create_project 不应被调用"


def test_generate_endpoint_translates_apperror_to_sse(client, registered_user, db_session, monkeypatch):
    """generate 端点的 AppError 分支：ConflictError → SSE {code:'conflict'}。

    mock astream_init_generate 抛 ConflictError（模拟并发竞态下 DB 约束触发），
    断言 SSE error 事件的 code 是 conflict，而非 llm_error。
    """
    from app.api import assistant as asm
    from app.models import Conversation, KIND_INIT, User
    from app.services import llm_config_service
    from sqlalchemy import select

    user_obj = db_session.scalar(select(User).where(User.email == registered_user["email"]))
    conv = Conversation(kind=KIND_INIT, user_id=user_obj.id, title="测试会话")
    db_session.add(conv)
    db_session.commit()

    async def _boom(*a, **k):
        raise ConflictError("该会话正在落地中，请勿重复点击")
        yield  # noqa: unreachable — 标记为 async generator

    monkeypatch.setattr(asm, "astream_init_generate", _boom)
    monkeypatch.setattr(llm_config_service, "resolve_chat_config", lambda *a, **k: _fake_llm_config())

    # 走真正的登录端点（与 test_assistant.py 的 _login 模式一致）
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })

    resp = client.post(f"/api/v1/assistant/conversations/{conv.id}/generate", json={})

    assert '"code": "conflict"' in resp.text, (
        f"期望 conflict code，实际响应: {resp.text[:300]}"
    )


def test_init_generate_lands_in_single_transaction(db_session, registered_user, monkeypatch):
    """正常落地：create_project 收到 commit=False，project 与落地标记同事务提交。

    z1a2b3c4d5e6 删除部分唯一索引后，行锁是防双落地的唯一防线——
    锁能持到标记完成的前提是 create_project 不自管 commit（中途 commit
    释放行锁，并发窗口复现双落地）。本测试锚定该事务形状。
    """
    from app.ai import init_orchestrator as mod
    from app.core import database as db_mod
    from app.models import User
    from app.services import project_service
    from app.services.seed_service import ensure_default_template
    from sqlalchemy import select

    ensure_default_template(db_session)
    user_obj = db_session.get(User, _uuid.UUID(registered_user["id"]))
    conv = _make_init_conv(db_session, user_obj)

    # 走 PG 分支（FOR UPDATE 查询在 SQLite 静默忽略，锁内二次检查路径生效）
    monkeypatch.setattr(db_mod, "is_postgres", lambda db=None: True)

    real_create = project_service.create_project
    seen_kwargs = {}

    def _spy_create(db, **kwargs):
        seen_kwargs.update(kwargs)
        return real_create(db, **kwargs)

    # orchestrator 函数内 import，须 patch 源模块（与上方 dedup 测试同模式）
    monkeypatch.setattr(project_service, "create_project", _spy_create)

    async def _fake_msgs(*a, **k):
        return []

    async def _fake_stream(*a, **k):
        yield "# 初稿"

    monkeypatch.setattr(mod, "_build_section_generate_messages", _fake_msgs)
    monkeypatch.setattr(mod, "astream_llm", _fake_stream)

    async def _run():
        events = []
        async for kind, data in mod.astream_init_generate(
            db_session, conv, [], user_obj, llm_config=_fake_llm_config(),
        ):
            events.append((kind, data))
        return events

    events = asyncio.run(_run())

    assert seen_kwargs.get("commit") is False, (
        f"落地路径必须传 commit=False（自管 commit 会中途释放行锁），实际: {seen_kwargs}"
    )
    kinds = [k for k, _ in events]
    assert "project_created" in kinds and kinds[-1] == "all_done"

    from app.models import Project
    project = db_session.scalars(select(Project).where(Project.user_id == user_obj.id)).one()
    db_session.refresh(conv)
    assert conv.project_id == project.id, "落地标记与建项目应同事务落库"


def test_multiple_unlanded_init_conversations_allowed(client, registered_user):
    """同一 user 的多条未落地 init 会话并存合法（ChatGPT 式多会话）。

    回归锚点：uq_conversations_init_one_unlanded 索引曾把此场景判非法，
    「+ 新对话」直接 500。SQLite 测试库从不建 PG 专属索引（该测试当时也是
    绿的），故此处固化端点语义：连建两条未落地会话均 201，为 PG 集成环境
    提供对照基线。
    """
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })

    r1 = client.post("/api/v1/assistant/conversations", json={"title": "想法A"})
    r2 = client.post("/api/v1/assistant/conversations", json={"title": "想法B"})
    assert r1.status_code == 201 and r2.status_code == 201, (
        f"多会话并存必须合法，实际: {r1.status_code} / {r2.status_code}"
    )

    titles = {c["title"] for c in client.get("/api/v1/assistant/conversations").json()}
    assert titles == {"想法A", "想法B"}
