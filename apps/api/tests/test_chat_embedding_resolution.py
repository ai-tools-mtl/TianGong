"""resolve_chat_config 解析测试 + embedding 固定配置测试。

embedding 解析已简化为固定 bge-m3 微服务（resolve_embedding_config 直接返回 env 配置），
不再有多源解析（global/custom/env），故原 embedding 多源用例已删，只保留一个固定配置断言。
"""

import pytest

from app.core.security import encrypt_value
from app.models import SystemSetting, User, UserGlobalLLMGrant, UserLLMConfig
from app.services.llm_config_service import (
    resolve_chat_config,
    resolve_embedding_config,
    ResolvedEmbeddingConfig,
    set_global_chat_settings,
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


# ── embedding resolve（固定配置，无多源）──

def test_embedding_resolve_returns_fixed_config():
    """embedding 统一走固定 bge-m3 微服务：resolve 永远返回 env 配置，不依赖 DB，永不为 None。"""
    resolved = resolve_embedding_config()
    assert isinstance(resolved, ResolvedEmbeddingConfig)
    assert resolved.source == "service"
    assert resolved.model  # 非空
    assert resolved.base_url  # 非空
