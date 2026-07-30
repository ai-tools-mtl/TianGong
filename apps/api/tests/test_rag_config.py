"""G3 rerank 配置 resolve 测试（镜像 embedding 配置模式）。

rerank 已迁到 env（rerank_enabled/rerank_base_url/rerank_model/rerank_api_key），
与 embedding 对称。不再测 SystemSetting roundtrip（该路径已删）。

测试要点：
- resolve_rerank_config 读 env，永不为 None。
- RERANK_ENABLED=false 时返回 disabled 配置（fail-open 跳过 rerank）。
- env 覆盖生效（patch settings 属性后读到新值）。

实现要点（避免污染全测试套件）：
- 不用 get_settings.cache_clear()——它是全局副作用，会让 conftest 的
  _clear_cookie_domain fixture（依赖稳定 settings 实例做 monkeypatch）失效，
  致后续鉴权/cookie 测试 401。
- 改用 monkeypatch.setattr 直接 patch settings 实例的 rerank_* 属性，
  与 conftest _clear_cookie_domain 同款安全模式（function-scoped 自动还原，不动 lru_cache）。
"""
import pytest

from app.core.config import get_settings
from app.services.rag_config_service import resolve_rerank_config


def _patch_rerank(monkeypatch, **kwargs):
    """直接 patch 全局 settings 单例的 rerank_* 属性（function-scoped 自动还原）。"""
    settings = get_settings()
    for k, v in kwargs.items():
        monkeypatch.setattr(settings, k, v)


def test_rerank_config_reads_env_enabled(monkeypatch):
    """resolve 从 settings 读到 enabled=True 与连接信息。"""
    _patch_rerank(
        monkeypatch,
        rerank_enabled=True,
        rerank_base_url="http://rerank.test:7998",
        rerank_model="BAAI/bge-reranker-v2-m3",
        rerank_api_key="sk-env-secret",
    )
    cfg = resolve_rerank_config(db=None, user_id=None)
    assert cfg is not None
    assert cfg.enabled is True
    assert cfg.base_url == "http://rerank.test:7998"
    assert cfg.model == "BAAI/bge-reranker-v2-m3"
    assert cfg.api_key == "sk-env-secret"


def test_rerank_config_disabled_when_env_false(monkeypatch):
    """rerank_enabled=False 时返回 disabled 配置（fail-open 降级开关）。"""
    _patch_rerank(
        monkeypatch,
        rerank_enabled=False,
        rerank_base_url="http://rerank.test:7998",
    )
    cfg = resolve_rerank_config(db=None, user_id=None)
    assert cfg.enabled is False
    # 连接信息仍可读（开关与连接信息解耦，开关只控制是否触发 rerank）
    assert cfg.base_url == "http://rerank.test:7998"


def test_rerank_config_signature_compat(db_session):
    """保留 db / user_id 参数仅为兼容调用方签名，内部忽略。

    retriever.py 调用 resolve_rerank_config(db, user_id=user_id)，
    传任何值都不影响结果（读 settings，不看 db）。
    """
    cfg_a = resolve_rerank_config(db=None, user_id=None)
    cfg_b = resolve_rerank_config(db=db_session, user_id="any-user-id")
    assert cfg_a.enabled == cfg_b.enabled
    assert cfg_a.base_url == cfg_b.base_url
    assert cfg_a.model == cfg_b.model
