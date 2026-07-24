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
            "model": "m1", "embedding_model": "emb",
        })
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["chat"]["ok"] is True
    assert body["embedding"]["dim"] == 128
