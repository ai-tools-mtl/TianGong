"""LLM 配置新端点测试：templates / models / 改造后的 test。"""

from unittest.mock import patch

from app.core.security import hash_password
from app.models import User


def _login_user(client, db_session):
    u = User(username="u1", email="u1@example.com",
             password_hash=hash_password("Pass1234!"), name="U1")
    db_session.add(u); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "u1", "password": "Pass1234!"})
    return u


# ── GET /settings/llm/templates ──

def test_templates_endpoint_returns_list(client, db_session):
    _login_user(client, db_session)
    res = client.get("/api/v1/settings/llm/templates")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 6
    ids = [t["id"] for t in data]
    assert "zhipu" in ids and "custom" in ids and "ollama" in ids
    # 字段齐全
    zhipu = next(t for t in data if t["id"] == "zhipu")
    for k in ("id", "name", "base_url", "default_model", "default_embedding_model",
              "models_endpoint", "docs_url", "note"):
        assert k in zhipu


def test_templates_requires_auth(client):
    res = client.get("/api/v1/settings/llm/templates")
    assert res.status_code in (401, 403)


# ── POST /settings/llm/models ──

def test_models_endpoint_returns_models(client, db_session):
    _login_user(client, db_session)
    with patch("app.api.settings.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["m1", "m2"], "truncated": False, "error": None}
        res = client.post("/api/v1/settings/llm/models", json={
            "base_url": "https://x.com/v1", "api_key": "sk-test", "provider_template_id": None,
        })
    assert res.status_code == 200
    assert res.json()["models"] == ["m1", "m2"]


def test_models_endpoint_requires_auth(client):
    res = client.post("/api/v1/settings/llm/models", json={
        "base_url": "https://x.com/v1", "api_key": "k",
    })
    assert res.status_code in (401, 403)


# ── POST /settings/llm/test（改造后返回 TestConnectionResult）──

def test_test_endpoint_new_shape(client, db_session):
    _login_user(client, db_session)
    with patch("app.api.settings.llm_config_service.test_llm_connection") as m:
        m.return_value = {
            "ok": True,
            "chat": {"ok": True, "latency_ms": 50, "sample": "hi", "error": None},
            "embedding": {"ok": True, "latency_ms": 40, "dim": 128, "error": None},
            "error": None,
        }
        res = client.post("/api/v1/settings/llm/test", json={
            "base_url": "https://x.com/v1", "api_key": "sk-test",
            "model": "m1",
        })
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["chat"]["ok"] is True
    assert body["embedding"]["dim"] == 128


# ── admin 端点（拆分版：/admin/llm-config/chat/test、/embedding/test、chat/models、embedding/models）──

def _login_admin(client, db_session):
    a = User(username="admin", email="admin@example.com",
             password_hash=hash_password("Admin1234!"), name="A", role="admin", status="active")
    db_session.add(a); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234!"})
    return a


def test_admin_chat_test_with_provided_values(client, db_session):
    """admin 用传入值测 chat（保存前预检）。"""
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": {"ok": True, "latency_ms": 10, "sample": "hi", "error": None},
                          "embedding": None, "error": None}
        res = client.post("/api/v1/admin/llm-config/chat/test", json={
            "base_url": "https://x.com/v1", "api_key": "sk-new", "model": "m1",
        })
    assert res.status_code == 200
    assert res.json()["ok"] is True
    m.assert_called_once()
    _, kwargs = m.call_args
    assert kwargs["api_key"] == "sk-new"  # 用传入值
    assert kwargs["scope"] == "chat"


def test_admin_chat_test_with_stored_values(client, db_session):
    """admin chat 不传值 → 用 SystemSetting 已存的 chat config（解密后）测（保存后复检）。"""
    _login_admin(client, db_session)
    from app.core.security import encrypt_value
    from app.models import SystemSetting
    db_session.add(SystemSetting(key="llm_global_chat_config", value={
        "base_url": "https://stored.com/v1",
        "api_key_encrypted": encrypt_value("sk-stored-1234567890"),
        "model": "stored-model",
    }))
    db_session.commit()

    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": {"ok": True, "latency_ms": 5, "sample": "x", "error": None},
                          "embedding": None, "error": None}
        res = client.post("/api/v1/admin/llm-config/chat/test", json={})  # 空 body
    assert res.status_code == 200
    _, kwargs = m.call_args
    assert kwargs["base_url"] == "https://stored.com/v1"
    assert kwargs["api_key"] == "sk-stored-1234567890"  # 解密后
    assert kwargs["model"] == "stored-model"


def test_admin_embedding_test_with_stored_values(client, db_session):
    """admin embedding 不传值 → 用 SystemSetting 已存的 embedding config（解密后）测。"""
    _login_admin(client, db_session)
    from app.core.security import encrypt_value
    from app.models import SystemSetting
    db_session.add(SystemSetting(key="llm_global_embedding_config", value={
        "base_url": "https://emb.com/v1",
        "api_key_encrypted": encrypt_value("sk-emb-1234567890"),
        "model": "embedding-3",
    }))
    db_session.commit()

    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": None,
                          "embedding": {"ok": True, "latency_ms": 5, "dim": 128, "error": None},
                          "error": None}
        res = client.post("/api/v1/admin/llm-config/embedding/test", json={})
    assert res.status_code == 200
    _, kwargs = m.call_args
    assert kwargs["base_url"] == "https://emb.com/v1"
    assert kwargs["api_key"] == "sk-emb-1234567890"
    assert kwargs["model"] == "embedding-3"
    assert kwargs["scope"] == "embedding"


def test_admin_chat_test_stored_incomplete_returns_error(client, db_session):
    """已存全局 chat 配置不完整（缺 model/api_key）→ 返回友好错误。"""
    _login_admin(client, db_session)
    from app.models import SystemSetting
    db_session.add(SystemSetting(key="llm_global_chat_config", value={"base_url": "https://x.com"}))
    db_session.commit()
    res = client.post("/api/v1/admin/llm-config/chat/test", json={})
    assert res.status_code == 200
    assert res.json()["ok"] is False
    assert "未设置" in res.json()["error"] or "不完整" in res.json()["error"]


def test_admin_chat_test_requires_admin(client, db_session):
    """非 admin → 403。"""
    _login_user(client, db_session)  # 普通用户
    res = client.post("/api/v1/admin/llm-config/chat/test", json={})
    assert res.status_code == 403


def test_admin_chat_models_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["m1"], "truncated": False, "error": None}
        res = client.post("/api/v1/admin/llm-config/chat/models", json={
            "base_url": "https://x.com/v1", "api_key": "sk",
        })
    assert res.status_code == 200
    assert res.json()["models"] == ["m1"]


def test_admin_embedding_models_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["e1"], "truncated": False, "error": None}
        res = client.post("/api/v1/admin/llm-config/embedding/models", json={
            "base_url": "https://x.com/v1", "api_key": "sk",
        })
    assert res.status_code == 200
    assert res.json()["models"] == ["e1"]
