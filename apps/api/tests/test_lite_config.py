"""轻量任务模型配置测试（独立第三套配置，承接会话标题/章节摘要）。

镜像 test_global_llm_config.py 的覆盖范围，但轻量配置的关键差异：
- SystemSetting key = "llm_lite_config"（LITE_CONFIG_KEY）
- 无 enabled 开关（未配即回退 chat）
- get_lite_settings 额外返回 configured 标志
- resolve_lite_config：已配且完整 → source="lite"；未配/不完整 → 回退 resolve_chat_config
- 端点 PUT body 为 {"lite_config": {...}}（无 enabled）

覆盖：service get/set + resolve（含回退）+ admin 端点 GET/PUT/test/models + 403 + 审计。
"""

import pytest
from unittest.mock import patch
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import encrypt_value, hash_password
from app.models import AuditLog, SystemSetting, User
from app.services import llm_config_service
from app.services.llm_config_service import (
    LITE_CONFIG_KEY,
    resolve_lite_config,
)


@pytest.fixture(autouse=True)
def _no_env_llm_fallback(monkeypatch):
    """默认锁死 env 兜底（glm_api_key=""），使「无配置」断言稳定。

    防止开发者本地 export GLM_API_KEY 导致 resolve 回退到 env 而非 None。
    """
    monkeypatch.setattr(get_settings(), "glm_api_key", "")


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


def _login_user(client, db_session):
    """普通用户登录（用于 403 校验）。"""
    u = User(
        username="plainuser",
        email="plain@example.com",
        password_hash=hash_password("Pass1234!"),
        name="普通",
        role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "username": "plainuser", "password": "Pass1234!",
    })
    return u


# ── service：get_lite_settings / set_lite_settings ──

def test_get_lite_settings_empty(db_session):
    """未配 → configured=False，掩码与 model 为空。"""
    s = llm_config_service.get_lite_settings(db_session)
    assert s["configured"] is False
    assert s["api_key_masked"] == ""
    assert s["model"] == ""
    assert s["base_url"] == ""


def test_set_and_get_lite_settings_roundtrip(db_session):
    """写入后回读：configured=True，model/base_url 往返，api_key 仅掩码。"""
    llm_config_service.set_lite_settings(
        db_session,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="sk-lite-1234567890",
        model="glm-4.7-flash",
    )
    s = llm_config_service.get_lite_settings(db_session)
    assert s["configured"] is True
    assert s["model"] == "glm-4.7-flash"
    assert s["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    # 掩码：不泄露明文，但能看出首尾
    assert s["api_key_masked"].startswith("sk-")
    assert s["api_key_masked"].endswith("7890")
    assert "sk-lite-1234567890" not in s["api_key_masked"]


def test_set_lite_settings_blank_api_key_keeps_old(db_session):
    """api_key 留空 → 保留旧密钥（与 set_global_chat_settings 语义一致）。"""
    llm_config_service.set_lite_settings(
        db_session, api_key="sk-old-1234567890", model="m1", base_url="u1",
    )
    llm_config_service.set_lite_settings(
        db_session, model="m2", base_url="u2",  # 不传 api_key
    )
    # 直接读密文校验未被覆盖
    cfg = db_session.scalar(select(SystemSetting).where(SystemSetting.key == LITE_CONFIG_KEY))
    assert cfg.value["model"] == "m2"
    assert cfg.value["base_url"] == "u2"
    assert decrypt_eq(cfg.value["api_key_encrypted"], "sk-old-1234567890")


def decrypt_eq(enc, plain):
    from app.core.security import decrypt_value
    return decrypt_value(enc) == plain


def test_set_lite_settings_partial_update_only_model(db_session):
    """仅传 model → 只更新 model，其余保留。"""
    llm_config_service.set_lite_settings(
        db_session, api_key="sk-k-1234567890", model="old", base_url="bu",
    )
    llm_config_service.set_lite_settings(db_session, model="glm-4.7-flash")
    s = llm_config_service.get_lite_settings(db_session)
    assert s["model"] == "glm-4.7-flash"
    assert s["base_url"] == "bu"  # 未变


# ── service：resolve_lite_config ──

def test_resolve_lite_config_uses_lite_when_configured(db_session):
    """已配且完整 → 返回轻量配置，source="lite"，key 解密正确。"""
    llm_config_service.set_lite_settings(
        db_session,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="sk-lite-1234567890",
        model="glm-4.7-flash",
    )
    cfg = resolve_lite_config(
        db_session, user_id="00000000-0000-0000-0000-000000000001",
    )
    assert cfg is not None
    assert cfg.source == "lite"
    assert cfg.model == "glm-4.7-flash"
    assert cfg.api_key == "sk-lite-1234567890"
    assert cfg.base_url == "https://open.bigmodel.cn/api/paas/v4"


def test_resolve_lite_config_falls_back_to_chat(db_session):
    """未配 lite → 回退 resolve_chat_config（此处 admin + global chat 已配）。"""
    # 配一份全局 chat（admin）
    llm_config_service.set_global_chat_settings(
        db_session, enabled=True,
        base_url="https://chat.example.com",
        api_key="sk-chat-1234567890",
        model="chat-strong",
    )
    admin = User(username="a", password_hash="x", name="A", role="admin", status="active")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    cfg = resolve_lite_config(db_session, user_id=admin.id)
    assert cfg is not None
    # 回退到 chat（admin 走 global chat）
    assert cfg.source in ("admin", "global")
    assert cfg.model == "chat-strong"


def test_resolve_lite_config_returns_none_when_nothing(db_session):
    """无 lite、无 chat、无 env（已 monkeypatch 锁死）→ None。"""
    u = User(username="n", password_hash="x", name="N", role="user", status="active")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    cfg = resolve_lite_config(db_session, user_id=u.id)
    assert cfg is None


def test_resolve_lite_config_incomplete_lite_falls_back(db_session):
    """lite 配了但不完整（缺 model）→ 视为未配，回退 chat。"""
    db_session.add(SystemSetting(
        key=LITE_CONFIG_KEY,
        value={"base_url": "https://x.com", "api_key_encrypted": encrypt_value("k1234567890")},
        # 无 model
    ))
    db_session.commit()
    u = User(username="m", password_hash="x", name="M", role="user", status="active")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    # 无 chat 无 env → 回退链最终 None
    cfg = resolve_lite_config(db_session, user_id=u.id)
    assert cfg is None


# ── 端点：GET / PUT / test / models ──

def test_get_lite_endpoint_empty(client, admin_and_login):
    res = client.get("/api/v1/admin/lite-config")
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False
    assert body["model"] == ""


def test_put_lite_endpoint_writes_and_audits(client, admin_and_login, db_session):
    res = client.put("/api/v1/admin/lite-config", json={
        "lite_config": {
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "sk-super-secret-1234567890",
            "model": "glm-4.7-flash",
        },
    })
    assert res.status_code == 200
    assert res.json()["model"] == "glm-4.7-flash"
    assert res.json()["configured"] is True
    # 审计
    log = db_session.scalar(select(AuditLog).where(AuditLog.action == "set_lite_config"))
    detail = log.detail or {}
    assert detail.get("lite_model") == "glm-4.7-flash"
    assert detail.get("lite_base_url") == "https://open.bigmodel.cn/api/paas/v4"
    # 红线：审计不含 api_key 明文 / 密文
    assert "api_key" not in detail
    assert "sk-super-secret-1234567890" not in str(detail)


def test_put_lite_blank_api_key_keeps_existing(client, admin_and_login):
    """PUT 不传 api_key → 保留已存密钥（回读掩码稳定）。"""
    client.put("/api/v1/admin/lite-config", json={
        "lite_config": {"base_url": "u1", "api_key": "sk-keep-1234567890", "model": "m1"},
    })
    masked_after_first = client.get("/api/v1/admin/lite-config").json()["api_key_masked"]
    # 第二次不传 api_key，只改 model
    client.put("/api/v1/admin/lite-config", json={
        "lite_config": {"base_url": "u2", "model": "m2"},
    })
    body = client.get("/api/v1/admin/lite-config").json()
    assert body["model"] == "m2"
    assert body["base_url"] == "u2"
    assert body["api_key_masked"] == masked_after_first  # 密钥未变


def test_lite_test_endpoint_uses_provided_values(client, admin_and_login):
    """传值模式 → 用传入值调 test_llm_connection。"""
    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": {"ok": True}, "embedding": None, "error": None}
        res = client.post("/api/v1/admin/lite-config/test", json={
            "base_url": "https://x.com", "api_key": "sk-k-1234567890", "model": "glm-4.7-flash",
        })
    assert res.status_code == 200
    _, kwargs = m.call_args
    assert kwargs["model"] == "glm-4.7-flash"
    assert kwargs["api_key"] == "sk-k-1234567890"


def test_lite_test_endpoint_uses_stored_values(client, admin_and_login, db_session):
    """空 body → 用已存 llm_lite_config 解密复检。"""
    db_session.add(SystemSetting(
        key=LITE_CONFIG_KEY,
        value={
            "base_url": "https://stored.com/v4",
            "api_key_encrypted": encrypt_value("sk-stored-1234567890"),
            "model": "stored-model",
        },
    ))
    db_session.commit()
    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": {"ok": True}, "embedding": None, "error": None}
        res = client.post("/api/v1/admin/lite-config/test", json={})
    assert res.status_code == 200
    _, kwargs = m.call_args
    assert kwargs["api_key"] == "sk-stored-1234567890"  # 解密后的
    assert kwargs["model"] == "stored-model"


def test_lite_test_endpoint_incomplete_friendly_error(client, admin_and_login, db_session):
    """已存配置不完整（缺 model）→ 友好错误。"""
    db_session.add(SystemSetting(
        key=LITE_CONFIG_KEY,
        value={"base_url": "https://x.com"},  # 无 api_key/model
    ))
    db_session.commit()
    res = client.post("/api/v1/admin/lite-config/test", json={})
    assert res.json()["ok"] is False
    assert "未设置" in res.json()["error"] or "不完整" in res.json()["error"]


def test_lite_models_endpoint(client, admin_and_login):
    with patch("app.api.admin.console.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["glm-4.7-flash"], "truncated": False, "error": None}
        res = client.post("/api/v1/admin/lite-config/models", json={
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "sk-k-1234567890",
            "provider_template_id": "zhipu",
        })
    assert res.status_code == 200
    assert "glm-4.7-flash" in res.json()["models"]


# ── 403：非 admin 不可访问 ──

def test_get_lite_requires_admin(client, db_session):
    _login_user(client, db_session)
    assert client.get("/api/v1/admin/lite-config").status_code == 403


def test_put_lite_requires_admin(client, db_session):
    _login_user(client, db_session)
    res = client.put("/api/v1/admin/lite-config", json={
        "lite_config": {"base_url": "u", "api_key": "k", "model": "m"},
    })
    assert res.status_code == 403


def test_lite_test_requires_admin(client, db_session):
    _login_user(client, db_session)
    assert client.post("/api/v1/admin/lite-config/test", json={}).status_code == 403
