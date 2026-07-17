"""全局 LLM 配置增强测试（Task 2.2 Part B）。

覆盖 allowed_models + embedding_model 的 set/get：
- set 同时带 allowed_models + embedding_model → get 返回两字段
- allowed_models 不提供时保留现有
- embedding_model 不提供时保留现有（补断链 A2：get 分支读但 set 从不写）
- allowed_models 显式空 list → 清空
- 审计 detail 含 allowed_models / embedding_model，不含 api_key 明文
- get 无配置时返回空 allowed_models / None embedding_model
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


# ── service 层 ──

def test_set_global_with_allowed_models_and_embedding(db_session, admin_user_for_svc):
    """set 同时带 allowed_models + embedding_model → get 返回两字段。"""
    llm_config_service.set_global_llm_settings(
        db_session, enabled=True,
        base_url="https://api.example.com", api_key="sk-test-1234567890",
        model="glm-4-flash",
        embedding_model="embedding-3",
        allowed_models=["glm-4-flash", "glm-4-air"],
    )
    res = llm_config_service.get_global_llm_settings(db_session)
    cfg = res["global_config"]
    assert cfg["embedding_model"] == "embedding-3"
    assert cfg["allowed_models"] == ["glm-4-flash", "glm-4-air"]


def test_allowed_models_preserved_when_not_provided(db_session, admin_user_for_svc):
    """allowed_models 不提供时保留现有。"""
    llm_config_service.set_global_llm_settings(
        db_session, enabled=True, api_key="sk-test-1234567890",
        allowed_models=["glm-4-flash"],
    )
    # 再次 set，不传 allowed_models
    llm_config_service.set_global_llm_settings(
        db_session, enabled=True, model="glm-4-air",
    )
    res = llm_config_service.get_global_llm_settings(db_session)
    assert res["global_config"]["allowed_models"] == ["glm-4-flash"]


def test_embedding_model_preserved_when_not_provided(db_session, admin_user_for_svc):
    """embedding_model 不提供时保留现有（补断链 A2）。"""
    llm_config_service.set_global_llm_settings(
        db_session, enabled=True, api_key="sk-test-1234567890",
        embedding_model="embedding-3",
    )
    # 再次 set 只改 model，不传 embedding_model
    llm_config_service.set_global_llm_settings(
        db_session, enabled=True, model="glm-4-air",
    )
    res = llm_config_service.get_global_llm_settings(db_session)
    assert res["global_config"]["embedding_model"] == "embedding-3"


def test_allowed_models_empty_list_clears(db_session, admin_user_for_svc):
    """allowed_models 显式传空 list → 清空。"""
    llm_config_service.set_global_llm_settings(
        db_session, enabled=True, api_key="sk-test-1234567890",
        allowed_models=["glm-4-flash"],
    )
    llm_config_service.set_global_llm_settings(
        db_session, enabled=True, allowed_models=[],
    )
    res = llm_config_service.get_global_llm_settings(db_session)
    assert res["global_config"]["allowed_models"] == []


def test_get_global_no_config_returns_empty(db_session, admin_user_for_svc):
    """无配置时 get 返回 global_config=None。"""
    res = llm_config_service.get_global_llm_settings(db_session)
    assert res["global_config"] is None
    assert res["llm_global_enabled"] is False


def test_embedding_model_flows_into_resolve(db_session, admin_user_for_svc):
    """set 写入的 embedding_model 能被 resolve_llm_config 的 global 分支读到（断链 A2 闭环）。"""
    llm_config_service.set_global_llm_settings(
        db_session, enabled=True, api_key="sk-test-1234567890",
        model="glm-4-flash", embedding_model="embedding-3",
    )
    from app.models import User, UserGlobalLLMGrant
    u = User(username="u1", password_hash="x", name="U", role="user")
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    db_session.add(UserGlobalLLMGrant(user_id=u.id)); db_session.commit()

    from app.services.llm_config_service import resolve_llm_config
    cfg = resolve_llm_config(db_session, user_id=u.id, source="global")
    assert cfg.embedding_model == "embedding-3"
    assert cfg.source == "global"


@pytest.fixture
def admin_user_for_svc(db_session):
    """service 层测试不需要真实 admin（_audit 由 API 层调用），此 fixture 仅占位确保 user 表有行。"""
    return None


# ── API 层（审计 detail + 端点 schema）──

def test_put_global_llm_with_new_fields(client, admin_and_login, db_session):
    """PUT 带 embedding_model + allowed_models → 200，审计 detail 含两字段，不含 api_key。"""
    res = client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "base_url": "https://open.bigmodel.cn",
        "api_key": "sk-super-secret-1234567890",
        "model": "glm-4-flash",
        "embedding_model": "embedding-3",
        "allowed_models": ["glm-4-flash", "glm-4-air"],
    })
    assert res.status_code == 200
    cfg = res.json()["global_config"]
    assert cfg["embedding_model"] == "embedding-3"
    assert cfg["allowed_models"] == ["glm-4-flash", "glm-4-air"]

    # 审计 detail
    log = db_session.scalar(select(AuditLog).where(AuditLog.action == "set_global_llm"))
    detail = log.detail or {}
    assert detail.get("embedding_model") == "embedding-3"
    assert detail.get("allowed_models") == ["glm-4-flash", "glm-4-air"]
    # 红线：不含 api_key 明文
    assert "api_key" not in detail
    assert "api_key_encrypted" not in detail
    assert "sk-super-secret-1234567890" not in str(detail)


def test_get_global_llm_endpoint_returns_new_fields(client, admin_and_login):
    """GET 端点返回 embedding_model + allowed_models 字段。"""
    client.put("/api/v1/admin/llm-config", json={
        "enabled": True,
        "api_key": "sk-test-1234567890",
        "embedding_model": "embedding-3",
        "allowed_models": ["glm-4-flash"],
    })
    res = client.get("/api/v1/admin/llm-config")
    cfg = res.json()["global_config"]
    assert "embedding_model" in cfg
    assert "allowed_models" in cfg
    assert cfg["allowed_models"] == ["glm-4-flash"]
