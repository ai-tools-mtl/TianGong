"""/settings/embedding/* 端点测试。镜像 chat 端点。"""

from unittest.mock import patch
from app.core.security import hash_password
from app.models import User


def _login_user(client, db_session):
    u = User(username="eu", email="eu@example.com", password_hash=hash_password("P1!"), name="E")
    db_session.add(u); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "eu", "password": "P1!"})
    return u


def test_list_embedding_configs_empty(client, db_session):
    _login_user(client, db_session)
    res = client.get("/api/v1/settings/embedding")
    assert res.status_code == 200
    assert res.json() == []


def test_create_embedding_config(client, db_session):
    _login_user(client, db_session)
    res = client.post("/api/v1/settings/embedding", json={
        "name": "智谱 emb", "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "sk-emb-1234567890", "model": "embedding-3",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "智谱 emb"
    assert data["model"] == "embedding-3"
    assert data["api_key_masked"].startswith("sk-")


def test_update_embedding_config(client, db_session):
    _login_user(client, db_session)
    cid = client.post("/api/v1/settings/embedding", json={
        "name": "n", "base_url": "u", "api_key": "sk-1234567890", "model": "m",
    }).json()["id"]
    res = client.put(f"/api/v1/settings/embedding/{cid}", json={"model": "new-model"})
    assert res.status_code == 200
    assert res.json()["model"] == "new-model"


def test_delete_embedding_config(client, db_session):
    _login_user(client, db_session)
    cid = client.post("/api/v1/settings/embedding", json={
        "name": "n", "base_url": "u", "api_key": "sk-1234567890", "model": "m",
    }).json()["id"]
    res = client.delete(f"/api/v1/settings/embedding/{cid}")
    assert res.status_code == 200


def test_embedding_test_endpoint(client, db_session):
    _login_user(client, db_session)
    with patch("app.api.settings.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": None,
                          "embedding": {"ok": True, "latency_ms": 50, "dim": 1024, "error": None},
                          "error": None}
        res = client.post("/api/v1/settings/embedding/test", json={
            "base_url": "https://x.com/v1", "api_key": "sk", "model": "emb",
        })
    assert res.status_code == 200
    assert res.json()["embedding"]["dim"] == 1024


def test_embedding_models_endpoint(client, db_session):
    _login_user(client, db_session)
    with patch("app.api.settings.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["emb-1"], "truncated": False, "error": None}
        res = client.post("/api/v1/settings/embedding/models", json={
            "base_url": "https://x.com/v1", "api_key": "sk",
        })
    assert res.status_code == 200
    assert res.json()["models"] == ["emb-1"]


def test_embedding_endpoints_require_auth(client):
    assert client.get("/api/v1/settings/embedding").status_code in (401, 403)
