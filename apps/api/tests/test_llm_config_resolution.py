"""LLM 配置解析断链修复验证（地基测试）。

目标：证明 ResolvedLLMConfig 真正传入 get_llm/get_embedder，而非读 env。
"""

from unittest.mock import patch

from app.services import llm_config_service
from app.services.llm_config_service import ResolvedLLMConfig


def test_resolved_config_has_embedding_model_field():
    """ResolvedLLMConfig 必须带 embedding_model 字段（当前缺失，断链 A2）。"""
    cfg = ResolvedLLMConfig(
        base_url="https://x.example.com",
        api_key="sk-test",
        model="glm-4",
        embedding_model="embedding-3",
        source="user",
    )
    assert cfg.embedding_model == "embedding-3"


def test_get_llm_uses_resolved_config_not_env():
    """get_llm 接收解析配置，不再读 settings.glm_*。"""
    from app.ai.llm_client import get_llm

    cfg = ResolvedLLMConfig(
        base_url="https://byok.example.com",
        api_key="sk-byok-xxx",
        model="byok-model",
        embedding_model="byok-embed",
        source="user",
    )
    with patch("app.ai.llm_client.ChatOpenAI") as mock:
        get_llm(llm_config=cfg)
        _, kwargs = mock.call_args
        # 必须用 cfg 的值，不是 settings
        assert kwargs["base_url"] == "https://byok.example.com"
        assert kwargs["api_key"] == "sk-byok-xxx"
        assert kwargs["model"] == "byok-model"


def test_get_embedder_uses_resolved_config():
    """get_embedder 接收解析配置。"""
    from app.rag.embedding import get_embedder

    cfg = ResolvedLLMConfig(
        base_url="https://byok.example.com",
        api_key="sk-byok-xxx",
        model="byok-model",
        embedding_model="byok-embed",
        source="user",
    )
    with patch("app.rag.embedding.OpenAIEmbeddings") as mock:
        get_embedder(embed_config=cfg)
        _, kwargs = mock.call_args
        assert kwargs["base_url"] == "https://byok.example.com"
        assert kwargs["api_key"] == "sk-byok-xxx"
        assert kwargs["model"] == "byok-embed"


def test_resolve_llm_config_falls_back_to_env(monkeypatch, db_session):
    """无 BYOK + 无全局配置 + env 有 glm_api_key → 返回 env 兜底配置（阶段 0 Task 0.6）。"""
    import uuid

    from app.core.config import get_settings
    from app.services.llm_config_service import resolve_llm_config

    s = get_settings()
    monkeypatch.setattr(s, "glm_api_key", "env-fake-key")
    monkeypatch.setattr(s, "glm_base_url", "https://env.example.com")
    monkeypatch.setattr(s, "glm_model", "env-model")
    monkeypatch.setattr(s, "glm_embedding_model", "env-embed")

    # resolve 只按 user_id 查 UserLLMConfig；查不到就继续走全局→env 兜底。
    cfg = resolve_llm_config(db_session, user_id=uuid.uuid4())
    assert cfg is not None
    assert cfg.source == "env"
    assert cfg.api_key == "env-fake-key"
    assert cfg.base_url == "https://env.example.com"
    assert cfg.model == "env-model"
    assert cfg.embedding_model == "env-embed"


def test_resolve_llm_config_returns_none_when_no_env_key(monkeypatch, db_session):
    """无 BYOK + 无全局 + env glm_api_key 为空 → 仍返回 None（调用方报 no_llm_config）。"""
    import uuid

    from app.core.config import get_settings
    from app.services.llm_config_service import resolve_llm_config

    s = get_settings()
    monkeypatch.setattr(s, "glm_api_key", "")  # 显式置空，与测试 .env 默认一致

    cfg = resolve_llm_config(db_session, user_id=uuid.uuid4())
    assert cfg is None


# ── 1214 修复闸 2：global 配置 model 为空时降级为 None ──
# 根因：admin 只填 key 没填 model 就保存 → model 存成空串 →
# _build_global_config 只校验 api_key，返回 model="" 的配置 → 后续触发 1214。
# 修复：model 空时视同未配置返回 None，让 resolve 降级到 BYOK/env。

def test_build_global_config_returns_none_when_model_empty(db_session):
    """全局配置 model 为空串 → _build_global_config 返回 None（视同未配置）。"""
    from app.services.llm_config_service import _build_global_config

    # 建一个有 key 但 model 为空的全局配置（模拟 admin 漏填 model）
    llm_config_service.set_global_llm_settings(
        db_session, enabled=True,
        base_url="https://api.example.com", api_key="sk-test-1234567890",
        model="",  # ← 空 model（set 允许存空，见 set_global_llm_settings）
    )
    cfg = _build_global_config(db_session, source="admin")
    assert cfg is None


def test_build_global_config_returns_config_when_model_present(db_session):
    """全局配置 model 有值 → 正常返回配置（回归：model 非空不被误拦）。"""
    from app.services.llm_config_service import _build_global_config

    llm_config_service.set_global_llm_settings(
        db_session, enabled=True,
        base_url="https://api.example.com", api_key="sk-test-1234567890",
        model="glm-4-flash",
    )
    cfg = _build_global_config(db_session, source="admin")
    assert cfg is not None
    assert cfg.model == "glm-4-flash"
