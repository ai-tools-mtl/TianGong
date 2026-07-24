"""admin 全局 LLM 配置拆 chat/embedding 两套 + 删 allowed_models。"""

from unittest.mock import patch
from app.core.security import hash_password
from app.models import User


def _login_admin(client, db_session):
    a = User(username="adm", email="adm@example.com", password_hash=hash_password("A1!"), name="A", role="admin", status="active")
    db_session.add(a); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "adm", "password": "A1!"})
    return a


def test_get_global_returns_chat_and_embedding(client, db_session):
    _login_admin(client, db_session)
    res = client.get("/api/v1/admin/llm-config")
    assert res.status_code == 200
    data = res.json()
    assert "chat_config" in data
    assert "embedding_config" in data
    assert "allowed_models" not in str(data)  # 删除


def test_put_global_chat_and_embedding(client, db_session):
    _login_admin(client, db_session)
    res = client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "chat_config": {"base_url": "https://chat.com", "api_key": "sk-c-1234567890", "model": "cm"},
        "embedding_config": {"base_url": "https://emb.com", "api_key": "sk-e-1234567890", "model": "em"},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["chat_config"]["model"] == "cm"
    assert data["embedding_config"]["model"] == "em"


def test_put_global_chat_only(client, db_session):
    """只传 chat_config，embedding_config 保留原状（各自独立更新）。"""
    _login_admin(client, db_session)
    # 先存两套
    client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "chat_config": {"base_url": "https://chat.com", "api_key": "sk-c-1234567890", "model": "cm"},
        "embedding_config": {"base_url": "https://emb.com", "api_key": "sk-e-1234567890", "model": "em"},
    })
    # 只改 chat
    res = client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "chat_config": {"model": "new-chat"},
    })
    assert res.status_code == 200
    data = res.json()
    assert data["chat_config"]["model"] == "new-chat"
    assert data["embedding_config"]["model"] == "em"  # 保留


def test_admin_chat_test_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": {"ok": True, "latency_ms": 10, "sample": "hi", "error": None}, "embedding": None, "error": None}
        res = client.post("/api/v1/admin/llm-config/chat/test", json={"base_url": "u", "api_key": "k", "model": "m"})
    assert res.status_code == 200


def test_admin_embedding_test_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": None, "embedding": {"ok": True, "latency_ms": 5, "dim": 128, "error": None}, "error": None}
        res = client.post("/api/v1/admin/llm-config/embedding/test", json={"base_url": "u", "api_key": "k", "model": "m"})
    assert res.status_code == 200


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


def test_admin_embedding_models_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["em"], "truncated": False, "error": None}
        res = client.post("/api/v1/admin/llm-config/embedding/models", json={"base_url": "u", "api_key": "k"})
    assert res.status_code == 200
    assert res.json()["models"] == ["em"]
