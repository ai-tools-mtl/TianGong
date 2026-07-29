"""G3 rerank 配置 resolve 测试（镜像 embedding 配置模式）。"""
import pytest
from app.services.rag_config_service import (
    get_global_rerank_settings, set_global_rerank_settings, resolve_rerank_config
)


def test_rerank_config_defaults_disabled(db_session):
    """无配置时 resolve 返回 enabled=False（默认关）。"""
    cfg = resolve_rerank_config(db_session, user_id=None)
    assert cfg is not None
    assert cfg.enabled is False


def test_rerank_config_global_roundtrip(db_session):
    """set 后 get 能读到，enabled 开关生效，api_key 加密存储。"""
    set_global_rerank_settings(
        db_session, enabled=True, base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="sk-test-secret", model="rerank",
    )
    settings = get_global_rerank_settings(db_session)
    assert settings["enabled"] is True
    assert settings["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert settings["api_key_encrypted"] != "sk-test-secret"  # 加密，不是明文


def test_rerank_config_resolve_uses_global(db_session):
    """resolve 从 global 配置构建 RerankConfig，api_key 解密。"""
    set_global_rerank_settings(
        db_session, enabled=True, base_url="http://x", api_key="sk-y", model="m"
    )
    cfg = resolve_rerank_config(db_session, user_id=None)
    assert cfg.enabled is True
    assert cfg.base_url == "http://x"
    assert cfg.api_key == "sk-y"  # 解密后是明文
    assert cfg.model == "m"


def test_rerank_config_set_overwrites(db_session):
    """二次 set 覆盖旧值（upsert，不是 insert）。"""
    set_global_rerank_settings(db_session, enabled=False, base_url="http://a", api_key="k1", model="m1")
    set_global_rerank_settings(db_session, enabled=True, base_url="http://b", api_key="k2", model="m2")
    settings = get_global_rerank_settings(db_session)
    assert settings["enabled"] is True
    assert settings["base_url"] == "http://b"
    assert settings["model"] == "m2"
