"""Embedding 封装。用 LangChain OpenAIEmbeddings（OpenAI 兼容协议）。"""

from langchain_openai import OpenAIEmbeddings

from app.services.llm_config_service import ResolvedEmbeddingConfig


def get_embedder(embed_config: ResolvedEmbeddingConfig) -> OpenAIEmbeddings:
    """构造 embedder。用解析后的 embedding 配置（统一走固定 bge-m3 微服务）。

    embed_config 由 resolve_embedding_config 产出（直接读 env，永不为 None，model 非空）。

    check_embedding_ctx_length=False: 关闭 langchain/openai SDK 的客户端 tokenization。
    默认 True 时 SDK 会用 tiktoken 把文本预切成 token IDs 再发送，但 Infinity 微服务
    只接受原始文本字符串（不接受 token IDs），必须关闭。

    api_key 占位：Infinity 本地服务不校验 key，但 openai SDK 强制要求非空，
    故空值时填占位符（不泄露真实凭据，也不影响本地服务）。
    """
    if not embed_config.model:
        raise ValueError("embedding 配置缺少 model")
    return OpenAIEmbeddings(
        model=embed_config.model,
        base_url=embed_config.base_url,
        api_key=embed_config.api_key or "not-needed",
        check_embedding_ctx_length=False,
    )


def embed_text(text: str, *, embed_config: ResolvedEmbeddingConfig) -> list[float]:
    """单文本向量化。"""
    return get_embedder(embed_config).embed_query(text)


def embed_texts(texts: list[str], *, embed_config: ResolvedEmbeddingConfig) -> list[list[float]]:
    """批量向量化。"""
    return get_embedder(embed_config).embed_documents(texts)
