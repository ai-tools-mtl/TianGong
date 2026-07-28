"""admin 全局 LLM 配置端点测试。

embedding 已改走固定 bge-m3 微服务，admin 全局配置只剩 chat 一套；
原 chat/embedding 拆分双写用例已收敛为 chat-only。
"""

from unittest.mock import patch
from app.core.security import hash_password
from app.models import User


def _login_admin(client, db_session):
    a = User(username="adm", email="adm@example.com", password_hash=hash_password("A1!"), name="A", role="admin", status="active")
    db_session.add(a); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "adm", "password": "A1!"})
    return a


def test_get_global_returns_chat_only(client, db_session):
    """GET 只返回 chat_config（embedding 走固定服务，不再有全局 embedding 配置）。"""
    _login_admin(client, db_session)
    res = client.get("/api/v1/admin/llm-config")
    assert res.status_code == 200
    data = res.json()
    assert "chat_config" in data
    assert "embedding_config" not in data
    assert "allowed_models" not in str(data)  # 删除


def test_put_global_chat(client, db_session):
    _login_admin(client, db_session)
    res = client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "chat_config": {"base_url": "https://chat.com", "api_key": "sk-c-1234567890", "model": "cm"},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["chat_config"]["model"] == "cm"
    assert "embedding_config" not in data


def test_put_global_enabled_only(client, db_session):
    """只传 enabled（不传 chat_config）也能更新开关。"""
    _login_admin(client, db_session)
    res = client.put("/api/v1/admin/llm-config", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["llm_global_enabled"] is False


def test_admin_chat_test_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": {"ok": True, "latency_ms": 10, "sample": "hi", "error": None}, "embedding": None, "error": None}
        res = client.post("/api/v1/admin/llm-config/chat/test", json={"base_url": "u", "api_key": "k", "model": "m"})
    assert res.status_code == 200


def test_admin_embedding_test_endpoint_removed(client, db_session):
    """embedding 测试端点已删除（embedding 走固定服务，无需配置时测试）→ 404。"""
    _login_admin(client, db_session)
    res = client.post("/api/v1/admin/llm-config/embedding/test", json={"base_url": "u", "api_key": "k", "model": "m"})
    assert res.status_code == 404


def test_old_admin_test_endpoint_removed(client, db_session):
    """老的 /admin/llm-config/test 应删除（404）。"""
    _login_admin(client, db_session)
    res = client.post("/api/v1/admin/llm-config/test", json={})
    assert res.status_code == 404


def test_admin_chat_models_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["cm"], "truncated": False, "error": None}
        res = client.post("/api/v1/admin/llm-config/chat/models", json={"base_url": "u", "api_key": "k"})
    assert res.status_code == 200
    assert res.json()["models"] == ["cm"]


def test_admin_embedding_models_endpoint_removed(client, db_session):
    """embedding 模型列表端点已删除 → 404。"""
    _login_admin(client, db_session)
    res = client.post("/api/v1/admin/llm-config/embedding/models", json={"base_url": "u", "api_key": "k"})
    assert res.status_code == 404
