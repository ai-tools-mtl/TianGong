"""按 source 解析 LLM 配置测试（阶段 2 Task 2.1）。

覆盖 resolve_llm_config 的 source 分支：
- source="global"：admin 免授权；非 admin 须有有效 grant，否则 ForbiddenError
- source="byok:{id}"：自己的配置 → 该配置；他人配置 → NotFoundError（防探测）
- source="env"：env 兜底
- source=None fallback：admin→global；非 admin→grant→global，否则单条 BYOK，否则 env，否则 None
- 无效 source → ValidationError
"""

import uuid

import pytest

from app.core.config import get_settings
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.security import encrypt_value
from app.models import SystemSetting, User, UserGlobalLLMGrant, UserLLMConfig
from app.services.llm_config_service import resolve_llm_config

GLOBAL_BASE_URL = "https://global.example.com"
GLOBAL_API_KEY = "sk-global-fake-key-999"
GLOBAL_MODEL = "global-model"
GLOBAL_EMBED = "global-embed"


# ── fixtures ──

@pytest.fixture(autouse=True)
def _lock_env_llm(monkeypatch):
    """锁定 env 兜底：默认空，防止 OS 环境变量干扰 source=None 的 env 分支断言。

    需要测 env 分支的用例可再次 monkeypatch 覆盖。
    """
    s = get_settings()
    monkeypatch.setattr(s, "glm_api_key", "")


def _make_user(db, *, role="user", name="U"):
    u = User(username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x", name=name, role=role)
    db.add(u); db.commit(); db.refresh(u)
    return u


def _make_global_config(db):
    """写入全局 SystemSetting（llm_global_config）。"""
    db.add(SystemSetting(
        key="llm_global_config",
        value={
            "base_url": GLOBAL_BASE_URL,
            "api_key_encrypted": encrypt_value(GLOBAL_API_KEY),
            "model": GLOBAL_MODEL,
            "embedding_model": GLOBAL_EMBED,
        },
    ))
    db.commit()


def _make_byok(db, user, *, name="default", base="https://byok.example.com",
               key="sk-byok-123", model="byok-model"):
    cfg = UserLLMConfig(
        user_id=user.id, name=name, provider="custom",
        base_url=base, api_key_encrypted=encrypt_value(key),
        model=model, embedding_model="byok-embed",
    )
    db.add(cfg); db.commit(); db.refresh(cfg)
    return cfg


# ── source="global" ──

def test_global_admin_exempt_from_grant(db_session):
    """admin + source=global → 免授权，返回全局配置。"""
    admin = _make_user(db_session, role="admin")
    _make_global_config(db_session)

    cfg = resolve_llm_config(db_session, user_id=admin.id, source="global")
    assert cfg is not None
    assert cfg.source == "admin"
    assert cfg.base_url == GLOBAL_BASE_URL
    assert cfg.api_key == GLOBAL_API_KEY
    assert cfg.model == GLOBAL_MODEL
    assert cfg.embedding_model == GLOBAL_EMBED


def test_global_requires_grant_for_non_admin(db_session):
    """非 admin + 无 grant + source=global → ForbiddenError。"""
    u = _make_user(db_session)
    _make_global_config(db_session)

    with pytest.raises(ForbiddenError, match="未授权使用全局 Key"):
        resolve_llm_config(db_session, user_id=u.id, source="global")


def test_global_granted_non_admin_returns_global(db_session):
    """非 admin + 有效 grant + source=global → 全局配置。"""
    u = _make_user(db_session)
    _make_global_config(db_session)
    db_session.add(UserGlobalLLMGrant(user_id=u.id)); db_session.commit()

    cfg = resolve_llm_config(db_session, user_id=u.id, source="global")
    assert cfg is not None
    assert cfg.source == "global"
    assert cfg.api_key == GLOBAL_API_KEY


def test_global_revoked_grant_forbidden(db_session):
    """非 admin + grant 已 revoked + source=global → ForbiddenError。"""
    from datetime import datetime, timezone
    u = _make_user(db_session)
    _make_global_config(db_session)
    db_session.add(UserGlobalLLMGrant(
        user_id=u.id, revoked_at=datetime.now(timezone.utc),
    )); db_session.commit()

    with pytest.raises(ForbiddenError):
        resolve_llm_config(db_session, user_id=u.id, source="global")


def test_global_unconfigured_returns_none(db_session):
    """全局 SystemSetting 未配置 + admin + source=global → None（全局未配）。"""
    admin = _make_user(db_session, role="admin")
    cfg = resolve_llm_config(db_session, user_id=admin.id, source="global")
    assert cfg is None


# ── source="byok:{id}" ──

def test_byok_returns_own_config(db_session):
    """source=byok:{自己 id} → 该配置。"""
    u = _make_user(db_session)
    cfg = _make_byok(db_session, u)

    resolved = resolve_llm_config(db_session, user_id=u.id, source=f"byok:{cfg.id}")
    assert resolved is not None
    assert resolved.source == "user"
    assert resolved.api_key == "sk-byok-123"
    assert resolved.model == "byok-model"


def test_byok_other_users_config_not_found(db_session):
    """source=byok:{他人 id} → NotFoundError（防探测，不泄露存在性）。"""
    owner = _make_user(db_session, name="owner")
    attacker = _make_user(db_session, name="attacker")
    cfg = _make_byok(db_session, owner)

    with pytest.raises(NotFoundError):
        resolve_llm_config(db_session, user_id=attacker.id, source=f"byok:{cfg.id}")


def test_byok_nonexistent_id_not_found(db_session):
    """source=byok:{不存在的 id} → NotFoundError。"""
    u = _make_user(db_session)
    with pytest.raises(NotFoundError):
        resolve_llm_config(db_session, user_id=u.id, source=f"byok:{uuid.uuid4()}")


def test_byok_invalid_uuid_not_found(db_session):
    """source=byok:{非 UUID} → NotFoundError（不抛 ValueError）。"""
    u = _make_user(db_session)
    with pytest.raises(NotFoundError):
        resolve_llm_config(db_session, user_id=u.id, source="byok:not-a-uuid")


# ── source="env" ──

def test_env_source_returns_env_config(monkeypatch, db_session):
    """source=env + glm_api_key 非空 → env 配置。"""
    s = get_settings()
    monkeypatch.setattr(s, "glm_api_key", "env-key")
    monkeypatch.setattr(s, "glm_base_url", "https://env.example.com")
    monkeypatch.setattr(s, "glm_model", "env-model")

    u = _make_user(db_session)
    cfg = resolve_llm_config(db_session, user_id=u.id, source="env")
    assert cfg is not None
    assert cfg.source == "env"
    assert cfg.api_key == "env-key"
    assert cfg.base_url == "https://env.example.com"
    assert cfg.model == "env-model"


def test_env_source_returns_none_when_empty(db_session):
    """source=env + glm_api_key 空 → None。"""
    u = _make_user(db_session)
    cfg = resolve_llm_config(db_session, user_id=u.id, source="env")
    assert cfg is None


# ── 无效 source ──

def test_invalid_source_raises_validation(db_session):
    """无效 source → ValidationError。"""
    u = _make_user(db_session)
    with pytest.raises(ValidationError, match="无效的 source"):
        resolve_llm_config(db_session, user_id=u.id, source="unknown")


# ── source=None fallback ──

def test_fallback_admin_uses_global(db_session):
    """source=None + admin → global（免授权）。"""
    admin = _make_user(db_session, role="admin")
    _make_global_config(db_session)

    cfg = resolve_llm_config(db_session, user_id=admin.id, source=None)
    assert cfg is not None
    assert cfg.source == "admin"
    assert cfg.api_key == GLOBAL_API_KEY


def test_fallback_admin_no_global_uses_env(monkeypatch, db_session):
    """source=None + admin + 全局未配 → env 兜底。"""
    s = get_settings()
    monkeypatch.setattr(s, "glm_api_key", "env-key")
    admin = _make_user(db_session, role="admin")

    cfg = resolve_llm_config(db_session, user_id=admin.id, source=None)
    assert cfg is not None
    assert cfg.source == "env"


def test_fallback_non_admin_with_grant_uses_global(db_session):
    """source=None + 非 admin + 有效 grant → global。"""
    u = _make_user(db_session)
    _make_global_config(db_session)
    db_session.add(UserGlobalLLMGrant(user_id=u.id)); db_session.commit()

    cfg = resolve_llm_config(db_session, user_id=u.id, source=None)
    assert cfg is not None
    assert cfg.source == "global"
    assert cfg.api_key == GLOBAL_API_KEY


def test_fallback_non_admin_no_grant_uses_byok(db_session):
    """source=None + 非 admin + 无 grant + 有单条 BYOK → 该 BYOK（过渡兼容）。"""
    u = _make_user(db_session)
    _make_byok(db_session, u, key="sk-fallback-byok")

    cfg = resolve_llm_config(db_session, user_id=u.id, source=None)
    assert cfg is not None
    assert cfg.source == "user"
    assert cfg.api_key == "sk-fallback-byok"


def test_fallback_non_admin_no_grant_no_byok_uses_env(monkeypatch, db_session):
    """source=None + 非 admin + 无 grant + 无 BYOK + env 非空 → env 兜底。"""
    s = get_settings()
    monkeypatch.setattr(s, "glm_api_key", "env-key")
    u = _make_user(db_session)

    cfg = resolve_llm_config(db_session, user_id=u.id, source=None)
    assert cfg is not None
    assert cfg.source == "env"
    assert cfg.api_key == "env-key"


def test_fallback_non_admin_nothing_configured_returns_none(db_session):
    """source=None + 非 admin + 无 grant + 无 BYOK + env 空 → None。"""
    u = _make_user(db_session)
    cfg = resolve_llm_config(db_session, user_id=u.id, source=None)
    assert cfg is None


def test_fallback_default_when_source_omitted(db_session):
    """省略 source 参数（默认 None）等价于 source=None fallback。

    证明 8 个旧调用点 resolve_llm_config(db, user_id=x) 仍可用（最小爆破）。
    """
    u = _make_user(db_session)
    _make_byok(db_session, u, key="sk-default-omitted")

    cfg = resolve_llm_config(db_session, user_id=u.id)  # 不传 source
    assert cfg is not None
    assert cfg.source == "user"
    assert cfg.api_key == "sk-default-omitted"
