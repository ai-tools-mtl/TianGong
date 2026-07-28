"""全局 LLM 配置测试（chat set/get + enabled 开关接入 resolution）。

全局配置只剩 chat 一套（embedding 改走固定 bge-m3 微服务）：
- set_global_chat_settings / get_global_chat_settings（llm_global_chat_config）

enabled 开关（llm_global_enabled）现在仅控制 chat：set_global_chat_settings 写它，
resolve_chat_config 的全局分支读它。本文件用 chat 链路验证 enabled 开关接入。

API 层 GET/PUT /admin/llm-config 返回 {llm_global_enabled, chat_config}，
admin 端点细节由 test_admin_split_endpoints.py 覆盖。
"""

import pytest

from app.core.security import hash_password
from app.models import AuditLog, User
from app.services import llm_config_service
from sqlalchemy import select


@pytest.fixture
def admin_and_login(client, db_session):
    admin = User(
        username="admin",
        email="admin@example.com",
        password_hash=hash_password("Admin1234!"),
        name="管理员",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(admin)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "Admin1234!",
    })
    return admin


# ── I1：llm_global_enabled 开关接入 resolution（用 chat 链路验证）──
# enabled（llm_global_enabled）是 chat+embedding 共用开关。这里用 set_global_chat_settings
# 写入 + resolve_chat_config 解析验证：关闭后即使配了全局 chat 也返回 None。

def test_global_disabled_returns_none_even_when_configured(db_session):
    """I1：admin 关闭 enabled=False → source=global 返回 None（即使配了 global chat config）。

    resolve_chat_config 的全局分支先看 enabled 开关，显式 False 则不可用。
    """
    from app.models import UserGlobalLLMGrant
    from app.services.llm_config_service import resolve_chat_config
    # 配全局 chat + 开启
    llm_config_service.set_global_chat_settings(
        db_session, enabled=True, api_key="sk-global-1234567890",
        model="glm-4-flash",
    )
    # 关闭（set_global_chat_settings 也写 llm_global_enabled 共用开关）
    llm_config_service.set_global_chat_settings(db_session, enabled=False)

    # 非 admin 即使有 grant，global 也应返回 None
    u = User(username="u-dis", password_hash="x", name="U", role="user")
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    db_session.add(UserGlobalLLMGrant(user_id=u.id)); db_session.commit()

    cfg = resolve_chat_config(db_session, user_id=u.id, chat_source="global")
    assert cfg is None, "admin 关闭全局后 source=global 应返回 None（I1）"


def test_global_disabled_returns_none_for_admin(db_session):
    """I1：admin 关闭后，admin 自己 source=global 也返回 None（admin 关了就是关了）。"""
    from app.services.llm_config_service import resolve_chat_config
    llm_config_service.set_global_chat_settings(
        db_session, enabled=True, api_key="sk-global-1234567890", model="glm-4-flash",
    )
    llm_config_service.set_global_chat_settings(db_session, enabled=False)

    admin = User(username="admin-dis", password_hash="x", name="A", role="admin")
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)

    cfg = resolve_chat_config(db_session, user_id=admin.id, chat_source="global")
    assert cfg is None


def test_global_enabled_record_absent_treated_as_open(db_session):
    """I1：enabled 记录不存在时视为开启（兼容旧部署未设开关）。

    只配 llm_global_chat_config，不配 llm_global_enabled → chat resolve 仍可用。
    """
    from app.models import SystemSetting
    from app.core.security import encrypt_value
    from app.services.llm_config_service import resolve_chat_config

    # 只写 global chat config，不写 enabled 开关
    db_session.add(SystemSetting(
        key="llm_global_chat_config",
        value={
            "base_url": "https://g.example.com",
            "api_key_encrypted": encrypt_value("sk-old-deploy-1234567890"),
            "model": "glm-4",
        },
    ))
    db_session.commit()

    admin = User(username="admin-old", password_hash="x", name="A", role="admin")
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)

    cfg = resolve_chat_config(db_session, user_id=admin.id, chat_source="global")
    assert cfg is not None, "enabled 记录不存在应视为开启（兼容）"
    assert cfg.source == "admin"


def test_global_enabled_true_then_global_usable(db_session):
    """I1 正向：enabled=True（显式开）→ chat global 可用。"""
    from app.services.llm_config_service import resolve_chat_config
    llm_config_service.set_global_chat_settings(
        db_session, enabled=True, api_key="sk-global-1234567890", model="glm-4-flash",
    )
    admin = User(username="admin-on", password_hash="x", name="A", role="admin")
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)

    cfg = resolve_chat_config(db_session, user_id=admin.id, chat_source="global")
    assert cfg is not None
    assert cfg.source == "admin"


# ── API 层（/admin/llm-config：只 chat_config，无 embedding_config / allowed_models）──

def test_put_global_llm_chat(client, admin_and_login, db_session):
    """PUT 带 chat_config → 200，审计 detail 含 chat model，不含 api_key。"""
    res = client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "chat_config": {
            "base_url": "https://open.bigmodel.cn",
            "api_key": "sk-super-secret-1234567890",
            "model": "glm-4-flash",
        },
    })
    assert res.status_code == 200
    data = res.json()
    assert data["chat_config"]["model"] == "glm-4-flash"
    assert "embedding_config" not in data
    assert "allowed_models" not in str(data)

    # 审计 detail
    log = db_session.scalar(select(AuditLog).where(AuditLog.action == "set_global_llm"))
    detail = log.detail or {}
    assert detail.get("chat_model") == "glm-4-flash"
    assert "embedding_model" not in detail  # embedding 字段已从审计移除
    # 红线：不含 api_key 明文
    assert "api_key" not in detail
    assert "api_key_encrypted" not in detail
    assert "sk-super-secret-1234567890" not in str(detail)


def test_get_global_llm_endpoint_returns_chat_only(client, admin_and_login):
    """GET 端点返回 chat_config，无 embedding_config / allowed_models。"""
    client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "chat_config": {"api_key": "sk-chat-1234567890", "model": "glm-4-flash"},
    })
    res = client.get("/api/v1/admin/llm-config")
    data = res.json()
    assert "chat_config" in data
    assert "embedding_config" not in data
    assert data["chat_config"]["model"] == "glm-4-flash"
    assert "allowed_models" not in str(data)
