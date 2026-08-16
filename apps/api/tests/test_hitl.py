# apps/api/tests/test_hitl.py
"""HITL 工具确认配置测试：service 默认/覆盖/build_interrupt_on + admin 端点 + build_agent 装配。"""
import pytest

from app.core.security import hash_password
from app.models import AuditLog, SystemSetting, User
from app.services.hitl_config_service import (
    build_interrupt_on,
    get_hitl_config,
    set_hitl_config,
)


@pytest.fixture
def admin_and_login(client, db_session):
    admin = User(
        username="admin",
        email="admin@example.com", password_hash=hash_password("Admin1234!"),
        name="管理员", role="admin", status="active",
    )
    db_session.add(admin)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "Admin1234!",
    })
    return admin


# ── service 层 ────────────────────────────────────────────────────────────────


def test_default_config_without_setting(db_session):
    """无 SystemSetting 时返回默认：enabled + generate_figure。"""
    assert get_hitl_config(db_session) == {"enabled": True, "tools": ["generate_figure"]}


def test_set_and_get_roundtrip(db_session):
    set_hitl_config(db_session, enabled=False, tools=["mcp_fetch", "rag_search"])
    assert get_hitl_config(db_session) == {"enabled": False, "tools": ["mcp_fetch", "rag_search"]}
    # 空白工具名被过滤
    set_hitl_config(db_session, enabled=True, tools=["  a  ", "", "b"])
    assert get_hitl_config(db_session)["tools"] == ["a", "b"]


def test_dirty_setting_falls_back_to_default(db_session):
    db_session.add(SystemSetting(key="agent_hitl_config", value={"tools": "not-a-list"}))
    db_session.commit()
    assert get_hitl_config(db_session) == {"enabled": True, "tools": ["generate_figure"]}


def test_build_interrupt_on_variants(db_session):
    sentinel = object()  # 任意非 None checkpointer
    # 默认配置 → generate_figure 条目，approve/reject
    intr = build_interrupt_on(db_session, checkpointer=sentinel)
    assert intr is not None
    assert intr["generate_figure"]["allowed_decisions"] == ["approve", "reject"]
    assert "附图" in intr["generate_figure"]["description"]
    # checkpointer=None（fail-open）→ 不拦（断点无法持久化）
    assert build_interrupt_on(db_session, checkpointer=None) is None
    # 停用 → 不拦
    set_hitl_config(db_session, enabled=False, tools=["generate_figure"])
    assert build_interrupt_on(db_session, checkpointer=sentinel) is None
    # 启用但清单空 → 不拦
    set_hitl_config(db_session, enabled=True, tools=[])
    assert build_interrupt_on(db_session, checkpointer=sentinel) is None


# ── admin 端点 ────────────────────────────────────────────────────────────────


def test_get_default_config(client, admin_and_login):
    res = client.get("/api/v1/admin/console/hitl")
    assert res.status_code == 200
    assert res.json() == {"enabled": True, "tools": ["generate_figure"]}


def test_put_config_and_audit(client, admin_and_login, db_session):
    res = client.put("/api/v1/admin/console/hitl", json={
        "enabled": True, "tools": ["generate_figure", "mcp_fetch"],
    })
    assert res.status_code == 200
    assert res.json()["tools"] == ["generate_figure", "mcp_fetch"]

    db_session.expire_all()
    audit = db_session.query(AuditLog).filter_by(action="set_hitl_config").one()
    assert audit.detail["tools"] == ["generate_figure", "mcp_fetch"]

    # 再 GET 读回
    assert client.get("/api/v1/admin/console/hitl").json()["enabled"] is True


def test_non_admin_403(client, registered_user, db_session):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert client.get("/api/v1/admin/console/hitl").status_code == 403
    assert client.put("/api/v1/admin/console/hitl", json={
        "enabled": False, "tools": [],
    }).status_code == 403


# ── build_agent 装配透传 ──────────────────────────────────────────────────────


def _patch_assembly(monkeypatch, captured: dict):
    """按 test_agent_factory 模式 mock 装配三件套（get_llm/create_deep_agent/storage）。"""
    import uuid

    from app.ai import agent as agent_mod
    from app.core import storage as storage_mod
    from app.services.llm_config_service import ResolvedChatConfig
    from tests.test_agent_factory import _mock_llm

    class _Sentinel:
        def ainvoke(self, *a, **kw):
            return None

        def astream_events(self, *a, **kw):
            return None

    def _fake_create(model=None, tools=None, *, system_prompt=None, skills=None,
                     backend=None, store=None, middleware=None, checkpointer=None, **kw):
        captured.update(
            interrupt_on=kw.get("interrupt_on"), checkpointer=checkpointer,
        )
        return _Sentinel()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)

    class _FakeStorage:
        def _resolve(self, a):
            return a

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    return {"config": config, "user_id": uuid.uuid4()}


def test_build_agent_passes_interrupt_on(db_session, monkeypatch):
    """checkpointer 存在 + 默认配置 → create_deep_agent 收到 interrupt_on（generate_figure）。"""
    import asyncio

    from app.ai import agent as agent_mod

    captured: dict = {}
    env = _patch_assembly(monkeypatch, captured)
    asyncio.run(agent_mod.build_agent(
        db_session, llm_config=env["config"], user_id=env["user_id"],
        checkpointer=object(),
    ))
    assert captured["interrupt_on"] is not None
    assert "generate_figure" in captured["interrupt_on"]


def test_build_agent_no_interrupt_on_without_checkpointer(db_session, monkeypatch):
    """checkpointer=None → interrupt_on=None（HITL 断点无法持久化，宁可不拦）。"""
    import asyncio

    from app.ai import agent as agent_mod

    captured: dict = {}
    env = _patch_assembly(monkeypatch, captured)
    asyncio.run(agent_mod.build_agent(
        db_session, llm_config=env["config"], user_id=env["user_id"],
    ))
    assert captured["interrupt_on"] is None


def test_build_agent_respects_disabled_config(db_session, monkeypatch):
    """admin 停用 HITL → interrupt_on=None（即便有 checkpointer）。"""
    import asyncio

    from app.ai import agent as agent_mod

    set_hitl_config(db_session, enabled=False, tools=["generate_figure"])
    captured: dict = {}
    env = _patch_assembly(monkeypatch, captured)
    asyncio.run(agent_mod.build_agent(
        db_session, llm_config=env["config"], user_id=env["user_id"],
        checkpointer=object(),
    ))
    assert captured["interrupt_on"] is None
