"""自定义配置 CRUD API 测试（Task 2.3 Part A）。

覆盖 /api/v1/settings/llm 系列端点的多配置 CRUD 语义：
- GET 空 → []
- POST 新增 → 200，返回含 id；GET → 列表含它
- POST 多条 → GET 列表多个（多配置）
- PUT 改自己的 → 字段更新；api_key 留空（None）则不变（掩码同前）
- PUT 改他人的 → 404（防探测，不泄露存在性）
- PUT 不存在的 id → 404
- DELETE 自己的 → 200；再 GET 不含
- DELETE 他人的 → 404
- GET/POST/PUT/DELETE 未登录 → 401（鉴权）

测试端点 POST /settings/llm/test 保留（不落库）。
"""

import uuid

import pytest

from app.core.security import encrypt_value, hash_password
from app.models import User, UserLLMConfig
from app.services import admin_service
from sqlalchemy import select


# ── fixtures ──

@pytest.fixture
def logged_in_user(client, registered_user):
    """登录普通用户，返回 user dict。"""
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    return registered_user


def _login(client, username, password):
    client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _make_other_user(db_session, *, username="other", name="Other"):
    """另一个普通用户（用于越权测试）。"""
    u = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("Pass1234!"),
        name=name,
        role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture
def admin_user(db_session):
    """普通管理员（role=admin, is_superuser=False），用于授权操作。"""
    u = User(
        username="admin",
        email="admin@example.com",
        password_hash="x",
        name="管理员",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(u)
    db_session.commit()
    return u


def _make_config(db_session, user, *, name="公司Key", key="sk-other-secret-123",
                 base="https://other.example.com", model="other-model"):
    cfg = UserLLMConfig(
        user_id=user.id, name=name, provider="custom",
        base_url=base, api_key_encrypted=encrypt_value(key),
        model=model, embedding_model="other-embed",
    )
    db_session.add(cfg)
    db_session.commit()
    db_session.refresh(cfg)
    return cfg


# ── GET ──

def test_get_empty_returns_list(client, logged_in_user):
    """无配置时 GET → []（多配置语义，不再是 None）。"""
    res = client.get("/api/v1/settings/llm")
    assert res.status_code == 200
    assert res.json() == []


def test_get_requires_auth(client):
    """未登录 GET → 401。"""
    res = client.get("/api/v1/settings/llm")
    assert res.status_code == 401


# ── POST 新增 ──

def test_post_creates_config_returns_id(client, logged_in_user, db_session):
    """POST 新增 → 200，返回含 id + 掩码 key。"""
    res = client.post("/api/v1/settings/llm", json={
        "name": "公司Key",
        "base_url": "https://api.example.com",
        "api_key": "sk-super-secret-1234567890",
        "model": "glm-4-flash",
        "embedding_model": "embedding-3",
    })
    assert res.status_code == 200
    body = res.json()
    assert "id" in body
    assert body["name"] == "公司Key"
    assert body["model"] == "glm-4-flash"
    assert body["embedding_model"] == "embedding-3"
    # 红线：返回掩码 key，绝不返回明文
    assert body["api_key_masked"].endswith("7890")
    assert "sk-super-secret-1234567890" not in str(body)

    # GET 列表含它
    res = client.get("/api/v1/settings/llm")
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["id"] == body["id"]
    assert rows[0]["name"] == "公司Key"


def test_post_multiple_configs(client, logged_in_user):
    """POST 多条 → GET 列表多个（多配置核心证明）。"""
    client.post("/api/v1/settings/llm", json={
        "name": "公司Key", "base_url": "https://a.example.com",
        "api_key": "sk-aaa-111122223333", "model": "model-a",
    })
    client.post("/api/v1/settings/llm", json={
        "name": "个人Key", "base_url": "https://b.example.com",
        "api_key": "sk-bbb-444455556666", "model": "model-b",
    })
    res = client.get("/api/v1/settings/llm")
    rows = res.json()
    assert len(rows) == 2
    names = {r["name"] for r in rows}
    assert names == {"公司Key", "个人Key"}


def test_post_requires_auth(client):
    """未登录 POST → 401。"""
    res = client.post("/api/v1/settings/llm", json={
        "name": "x", "base_url": "https://x.example.com",
        "api_key": "sk-x", "model": "m",
    })
    assert res.status_code == 401


# ── PUT 修改 ──

def test_put_updates_own_fields(client, logged_in_user, db_session):
    """PUT 改自己的 → 字段更新。"""
    user = db_session.scalar(select(User).where(User.email == logged_in_user["email"]))
    cfg = _make_config(db_session, user, name="旧名", model="old-model", key="sk-orig-1234567890")

    res = client.put(f"/api/v1/settings/llm/{cfg.id}", json={
        "name": "新名",
        "model": "new-model",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "新名"
    assert body["model"] == "new-model"
    # 未提供的字段保留
    assert body["base_url"] == "https://other.example.com"


def test_put_api_key_none_keeps_mask(client, logged_in_user, db_session):
    """PUT 不传 api_key → key 不变（掩码同前）。"""
    user = db_session.scalar(select(User).where(User.email == logged_in_user["email"]))
    cfg = _make_config(db_session, user, key="sk-keep-secret-9999")

    res = client.put(f"/api/v1/settings/llm/{cfg.id}", json={
        "model": "changed-model",
    })
    assert res.status_code == 200
    # 掩码应保持原 key 的掩码
    assert res.json()["api_key_masked"] == "sk-****9999"


def test_put_updates_api_key_when_provided(client, logged_in_user, db_session):
    """PUT 传新 api_key → key 更新（掩码变化）。"""
    user = db_session.scalar(select(User).where(User.email == logged_in_user["email"]))
    cfg = _make_config(db_session, user, key="sk-old-1234567890")

    res = client.put(f"/api/v1/settings/llm/{cfg.id}", json={
        "api_key": "sk-brand-new-555566667777",
    })
    assert res.status_code == 200
    masked = res.json()["api_key_masked"]
    assert masked.endswith("7777")  # 新 key 的尾巴
    assert "sk-old-1234567890" not in masked


def test_put_other_users_config_returns_404(client, logged_in_user, db_session):
    """PUT 改他人的配置 → 404（防探测，不泄露存在性）。"""
    other = _make_other_user(db_session)
    other_cfg = _make_config(db_session, other, key="sk-others-9999")

    res = client.put(f"/api/v1/settings/llm/{other_cfg.id}", json={
        "name": "篡改",
    })
    assert res.status_code == 404
    # 确认他人配置未被改
    db_session.expire_all()
    cfg = db_session.get(UserLLMConfig, other_cfg.id)
    assert cfg.name != "篡改"


def test_put_nonexistent_id_returns_404(client, logged_in_user):
    """PUT 不存在的 id → 404。"""
    res = client.put(f"/api/v1/settings/llm/{uuid.uuid4()}", json={"name": "x"})
    assert res.status_code == 404


def test_put_invalid_uuid_returns_404(client, logged_in_user):
    """PUT 非 UUID → 404（不抛 500）。"""
    res = client.put("/api/v1/settings/llm/not-a-uuid", json={"name": "x"})
    assert res.status_code == 404


def test_put_requires_auth(client):
    """未登录 PUT → 401。"""
    res = client.put(f"/api/v1/settings/llm/{uuid.uuid4()}", json={"name": "x"})
    assert res.status_code == 401


# ── DELETE ──

def test_delete_own_config(client, logged_in_user, db_session):
    """DELETE 自己的 → 200；再 GET 不含。"""
    user = db_session.scalar(select(User).where(User.email == logged_in_user["email"]))
    cfg = _make_config(db_session, user)

    res = client.delete(f"/api/v1/settings/llm/{cfg.id}")
    assert res.status_code == 200
    assert res.json()["message"] == "已删除"

    # GET 列表不再含
    res = client.get("/api/v1/settings/llm")
    assert all(r["id"] != str(cfg.id) for r in res.json())


def test_delete_other_users_config_returns_404(client, logged_in_user, db_session):
    """DELETE 他人的 → 404（防探测）。"""
    other = _make_other_user(db_session)
    other_cfg = _make_config(db_session, other)

    res = client.delete(f"/api/v1/settings/llm/{other_cfg.id}")
    assert res.status_code == 404
    # 他人配置仍在
    db_session.expire_all()
    assert db_session.get(UserLLMConfig, other_cfg.id) is not None


def test_delete_nonexistent_id_returns_404(client, logged_in_user):
    """DELETE 不存在的 id → 404。"""
    res = client.delete(f"/api/v1/settings/llm/{uuid.uuid4()}")
    assert res.status_code == 404


def test_delete_requires_auth(client):
    """未登录 DELETE → 401。"""
    res = client.delete(f"/api/v1/settings/llm/{uuid.uuid4()}")
    assert res.status_code == 401


# ── 隔离：不同用户配置互不可见 ──

def test_configs_isolated_between_users(client, logged_in_user, db_session):
    """A 的配置在 B 的 GET 列表里不可见（行级隔离）。"""
    user = db_session.scalar(select(User).where(User.email == logged_in_user["email"]))
    # A 建一条
    client.post("/api/v1/settings/llm", json={
        "name": "A的Key", "base_url": "https://a.example.com",
        "api_key": "sk-aaa-111122223333", "model": "a-model",
    })
    # B 也建一条
    other = _make_other_user(db_session)
    _make_config(db_session, other, name="B的Key")

    # A 看到的只有自己那条
    res = client.get("/api/v1/settings/llm")
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "A的Key"


# ── POST /settings/llm/test 保留 ──

def test_test_endpoint_still_works(client, logged_in_user, monkeypatch):
    """POST /settings/llm/test 端点保留（不落库，测试连通）。

    mock ChatOpenAI（端点内运行时 import）避免真实网络。
    """
    from unittest.mock import MagicMock, patch

    mock_inst = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = "pong"
    mock_inst.invoke = lambda msgs: mock_resp

    # 端点内 `from langchain_openai import ChatOpenAI` 在调用时执行，patch 源模块
    with patch("langchain_openai.ChatOpenAI", return_value=mock_inst):
        res = client.post("/api/v1/settings/llm/test", json={
            "base_url": "https://api.example.com",
            "api_key": "sk-test-123",
            "model": "test-model",
        })
    assert res.status_code == 200
    # ok 字段存在（mock 走成功路径或异常路径，两者都 200）
    assert "ok" in res.json()


def test_test_endpoint_requires_auth(client):
    """未登录 test → 401。"""
    res = client.post("/api/v1/settings/llm/test", json={
        "base_url": "https://api.example.com",
        "api_key": "sk-test-123", "model": "m",
    })
    assert res.status_code == 401


# ── GET /settings/my-grant（Task 4.0 Part A：普通用户查自己授权）──

def test_my_grant_no_record_returns_inactive(client, logged_in_user):
    """无授权记录 → {is_active: False}（选源器据此隐藏「全局 Key」选项）。"""
    res = client.get("/api/v1/settings/my-grant")
    assert res.status_code == 200
    body = res.json()
    assert body["is_active"] is False
    # 无记录时不返回 granted_at（避免误导）
    assert body.get("granted_at") is None


def test_my_grant_active_after_grant(client, logged_in_user, db_session, admin_user):
    """被 admin 授权后 → {is_active: True, granted_at: ...}。"""
    user = db_session.scalar(select(User).where(User.email == logged_in_user["email"]))
    admin_service.grant_global_llm_access(db_session, actor=admin_user, user_id=user.id)

    res = client.get("/api/v1/settings/my-grant")
    assert res.status_code == 200
    body = res.json()
    assert body["is_active"] is True
    assert body["granted_at"] is not None
    assert body["revoked_at"] is None


def test_my_grant_inactive_after_revoke(client, logged_in_user, db_session, admin_user):
    """授权后被撤销 → {is_active: False, revoked_at: ...}（保留 granted_at 留痕）。"""
    user = db_session.scalar(select(User).where(User.email == logged_in_user["email"]))
    admin_service.grant_global_llm_access(db_session, actor=admin_user, user_id=user.id)
    admin_service.revoke_global_llm_access(db_session, actor=admin_user, user_id=user.id)

    res = client.get("/api/v1/settings/my-grant")
    assert res.status_code == 200
    body = res.json()
    assert body["is_active"] is False
    assert body["revoked_at"] is not None


def test_my_grant_requires_auth(client):
    """未登录 → 401。"""
    res = client.get("/api/v1/settings/my-grant")
    assert res.status_code == 401


def test_my_grant_does_not_leak_other_users(client, logged_in_user, db_session, admin_user):
    """A 查 my-grant 不应看到 B 的授权（行级隔离：按 current_user.id 查）。"""
    # B 被授权
    other = _make_other_user(db_session)
    admin_service.grant_global_llm_access(db_session, actor=admin_user, user_id=other.id)

    # A（logged_in_user）查自己的 → 应为 inactive（A 没被授权）
    res = client.get("/api/v1/settings/my-grant")
    assert res.status_code == 200
    assert res.json()["is_active"] is False
