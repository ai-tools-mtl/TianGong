"""LLM 配置解析断链修复验证（地基测试）。

目标：证明解析出的配置对象真正传入 get_llm/get_embedder，而非读 env。
解析层拆分为 chat（ResolvedChatConfig）与 embedding（ResolvedEmbeddingConfig）
两条独立链路；各自的 source 分支覆盖见 test_chat_embedding_resolution.py。
"""

from unittest.mock import patch

from app.services.llm_config_service import ResolvedChatConfig, ResolvedEmbeddingConfig


def test_get_llm_uses_resolved_config_not_env():
    """get_llm 接收解析后的 chat 配置，不再读 settings.glm_*。"""
    from app.ai.llm_client import get_llm

    cfg = ResolvedChatConfig(
        base_url="https://custom.example.com",
        api_key="sk-custom-xxx",
        model="custom-model",
        source="user",
    )
    with patch("app.ai.llm_client.ReasoningChatOpenAI") as mock:
        get_llm(cfg)
        _, kwargs = mock.call_args
        # 必须用 cfg 的值，不是 settings
        assert kwargs["base_url"] == "https://custom.example.com"
        assert kwargs["api_key"] == "sk-custom-xxx"
        assert kwargs["model"] == "custom-model"


def test_get_embedder_uses_resolved_config():
    """get_embedder 接收解析后的 embedding 配置（ResolvedEmbeddingConfig）。"""
    from app.rag.embedding import get_embedder

    cfg = ResolvedEmbeddingConfig(
        base_url="https://custom.example.com",
        api_key="sk-custom-xxx",
        model="custom-embed",
        source="user",
    )
    with patch("app.rag.embedding.OpenAIEmbeddings") as mock:
        get_embedder(cfg)
        _, kwargs = mock.call_args
        assert kwargs["base_url"] == "https://custom.example.com"
        assert kwargs["api_key"] == "sk-custom-xxx"
        assert kwargs["model"] == "custom-embed"
