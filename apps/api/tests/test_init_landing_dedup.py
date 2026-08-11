# apps/api/tests/test_init_landing_dedup.py
"""P0-1：init generate 双击重复落地的去重逻辑测试。

生产用 PG 部分唯一索引（uq_conversations_init_one_unlanded）+ FOR UPDATE 行锁
保证并发安全。SQLite 测试库两者都不支持（FOR UPDATE 静默忽略、部分唯一索引
不建），故此处聚焦测「逻辑路径」：

1. astream_init_generate 在 conversation.project_id 已非空时（并发竞态中锁内
   二次检查命中）抛 ConflictError，且不再调 create_project。
2. assistant.py generate 端点的 AppError 分支把 ConflictError 转成
   {code: "conflict"} SSE error 事件，而非走 llm_error 通用提示。

部分唯一索引 + FOR UPDATE 的真实并发正确性靠 PG 集成验证（迁移幂等性 + 脏数据
清理在 PG 环境单独跑，此处不覆盖）。
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
