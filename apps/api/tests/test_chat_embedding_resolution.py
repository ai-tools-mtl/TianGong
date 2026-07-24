"""resolve_chat_config / resolve_embedding_config 解析测试（chat/embedding 独立）。"""

import pytest

from app.core.security import encrypt_value
from app.models import SystemSetting, User, UserEmbeddingConfig, UserGlobalLLMGrant, UserLLMConfig
from app.services.llm_config_service import (
    resolve_chat_config, resolve_embedding_config,
    set_global_chat_settings, set_global_embedding_settings,
)


# ── chat resolve ──

def test_chat_resolve_custom(db_session, registered_user):
    import uuid
    cfg = UserLLMConfig(
        user_id=uuid.UUID(registered_user["id"]), name="chat",
        base_url="https://chat.example.com/v1",
        api_key_encrypted=encrypt_value("sk-chat-1234567890"),
        model="glm-4",
    )
    db_session.add(cfg); db_session.commit(); db_session.refresh(cfg)

    resolved = resolve_chat_config(db_session, user_id=uuid.UUID(registered_user["id"]), chat_source=f"custom-chat:{cfg.id}")
    assert resolved is not None
    assert resolved.base_url == "https://chat.example.com/v1"
    assert resolved.model == "glm-4"
    assert resolved.source == "user"


def test_chat_resolve_global_for_admin(db_session):
    admin = User(username="admin", password_hash="x", name="A", role="admin")
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    set_global_chat_settings(db_session, enabled=True, base_url="https://g-chat.com",
                             api_key="sk-g-1234567890", model="g-chat-model")
    resolved = resolve_chat_config(db_session, user_id=admin.id, chat_source="global")
    assert resolved is not None
    assert resolved.model == "g-chat-model"
    assert resolved.source == "admin"


def test_chat_resolve_env_when_nothing_else(db_session, registered_user, monkeypatch):
    import uuid
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "glm_api_key", "sk-env")
    resolved = resolve_chat_config(db_session, user_id=uuid.UUID(registered_user["id"]), chat_source="env")
    assert resolved is not None
    assert resolved.source == "env"


def test_chat_resolve_global_requires_grant_for_non_admin(db_session, registered_user):
    import uuid
    set_global_chat_settings(db_session, enabled=True, api_key="sk-g-1234567890", model="g")
    from app.core.exceptions import ForbiddenError
    with pytest.raises(ForbiddenError):
        resolve_chat_config(db_session, user_id=uuid.UUID(registered_user["id"]), chat_source="global")


def test_chat_resolve_custom_foreign_returns_not_found(db_session, registered_user):
    import uuid
    other = User(username="other", password_hash="x", name="O")
    db_session.add(other); db_session.commit(); db_session.refresh(other)
    cfg = UserLLMConfig(user_id=other.id, name="x", base_url="u", api_key_encrypted="e", model="m")
    db_session.add(cfg); db_session.commit(); db_session.refresh(cfg)
    from app.core.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        resolve_chat_config(db_session, user_id=uuid.UUID(registered_user["id"]), chat_source=f"custom-chat:{cfg.id}")


# ── embedding resolve ──

def test_embedding_resolve_custom(db_session, registered_user):
    import uuid
    cfg = UserEmbeddingConfig(
        user_id=uuid.UUID(registered_user["id"]), name="emb",
        base_url="https://emb.example.com/v1",
        api_key_encrypted=encrypt_value("sk-emb-1234567890"),
        model="text-embedding-3-small",
    )
    db_session.add(cfg); db_session.commit(); db_session.refresh(cfg)

    resolved = resolve_embedding_config(db_session, user_id=uuid.UUID(registered_user["id"]), embedding_source=f"custom-emb:{cfg.id}")
    assert resolved is not None
    assert resolved.base_url == "https://emb.example.com/v1"
    assert resolved.model == "text-embedding-3-small"
    assert resolved.source == "user"


def test_embedding_resolve_global_for_admin(db_session):
    admin = User(username="admin2", password_hash="x", name="A", role="admin")
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)
    set_global_embedding_settings(db_session, enabled=True, base_url="https://g-emb.com",
                                  api_key="sk-ge-1234567890", model="g-emb-model")
    resolved = resolve_embedding_config(db_session, user_id=admin.id, embedding_source="global")
    assert resolved is not None
    assert resolved.model == "g-emb-model"
    assert resolved.source == "admin"


# ── 独立性：chat 与 embedding 各自解析，互不影响 ──

def test_chat_and_embedding_resolve_independently(db_session, registered_user):
    """chat 配 base_url A，embedding 配 base_url B → 各自解析到不同的 base_url。"""
    import uuid
    uid = uuid.UUID(registered_user["id"])
    chat_cfg = UserLLMConfig(
        user_id=uid, name="c",
        base_url="https://CHAT.example.com/v1",
        api_key_encrypted=encrypt_value("sk-c-1234567890"), model="chat-model",
    )
    emb_cfg = UserEmbeddingConfig(
        user_id=uid, name="e",
        base_url="https://EMB.example.com/v1",
        api_key_encrypted=encrypt_value("sk-e-1234567890"), model="emb-model",
    )
    db_session.add_all([chat_cfg, emb_cfg]); db_session.commit()
    db_session.refresh(chat_cfg); db_session.refresh(emb_cfg)

    chat = resolve_chat_config(db_session, user_id=uid, chat_source=f"custom-chat:{chat_cfg.id}")
    emb = resolve_embedding_config(db_session, user_id=uid, embedding_source=f"custom-emb:{emb_cfg.id}")
    assert chat.base_url == "https://CHAT.example.com/v1"
    assert emb.base_url == "https://EMB.example.com/v1"
    assert chat.base_url != emb.base_url  # 核心 invariant


# ── fallback 不互通（D4）──

def test_embedding_fallback_no_crosstalk_to_chat(db_session, registered_user, monkeypatch):
    """只配了 chat 配置、没配 embedding → resolve_embedding_config 返回 None，不回退 chat。"""
    import uuid
    from app.core.config import get_settings
    # 确保 env 也不提供 embedding（否则 fallback 会命中 env）
    monkeypatch.setattr(get_settings(), "glm_api_key", "")
    monkeypatch.setattr(get_settings(), "glm_embedding_model", "")

    uid = uuid.UUID(registered_user["id"])
    chat_cfg = UserLLMConfig(
        user_id=uid, name="c",
        base_url="https://chat.example.com/v1",
        api_key_encrypted=encrypt_value("sk-c-1234567890"), model="chat-model",
    )
    db_session.add(chat_cfg); db_session.commit()
    resolved = resolve_embedding_config(db_session, user_id=uid)  # fallback
    assert resolved is None  # 不回退到 chat 凭据


def test_chat_fallback_no_crosstalk_to_embedding(db_session, registered_user, monkeypatch):
    """只配了 embedding 配置、没配 chat → resolve_chat_config 返回 None，不回退 embedding。

    D4 不互通的反向验证（与 test_embedding_fallback_no_crosstalk_to_chat 对称）。
    """
    import uuid
    from app.core.config import get_settings
    # 清空 env 兜底（否则 fallback 会命中 env 的 chat 凭据）
    monkeypatch.setattr(get_settings(), "glm_api_key", "")

    uid = uuid.UUID(registered_user["id"])
    emb_cfg = UserEmbeddingConfig(
        user_id=uid, name="e",
        base_url="https://emb.example.com/v1",
        api_key_encrypted=encrypt_value("sk-e-1234567890"), model="emb-model",
    )
    db_session.add(emb_cfg); db_session.commit()
    resolved = resolve_chat_config(db_session, user_id=uid)  # fallback
    assert resolved is None  # 不回退到 embedding 凭据
