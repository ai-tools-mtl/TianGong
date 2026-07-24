"""Embedding 封装。用 LangChain OpenAIEmbeddings（OpenAI 兼容协议）。"""

from langchain_openai import OpenAIEmbeddings

from app.services.llm_config_service import ResolvedEmbeddingConfig


def get_embedder(embed_config: ResolvedEmbeddingConfig) -> OpenAIEmbeddings:
    """构造 embedder。用解析后的 embedding 配置（与 chat 独立）。

    embed_config 由 resolve_embedding_config 产出，model 已保证非空（resolve 的 build 分支都校验过）。
    """
    if not embed_config.model:
        raise ValueError("embedding 配置缺少 model")
    return OpenAIEmbeddings(
        model=embed_config.model,
        base_url=embed_config.base_url,
        api_key=embed_config.api_key,
    )


def embed_text(text: str, *, embed_config: ResolvedEmbeddingConfig) -> list[float]:
    """单文本向量化。"""
    return get_embedder(embed_config).embed_query(text)


def embed_texts(texts: list[str], *, embed_config: ResolvedEmbeddingConfig) -> list[list[float]]:
    """批量向量化。"""
    return get_embedder(embed_config).embed_documents(texts)
