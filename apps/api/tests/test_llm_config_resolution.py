"""LLM 配置解析断链修复验证（地基测试）。

目标：证明 ResolvedLLMConfig 真正传入 get_llm/get_embedder，而非读 env。
"""

from unittest.mock import patch

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
