"""Embedding 封装。用 LangChain OpenAIEmbeddings 接智谱 embedding-3。"""

from langchain_openai import OpenAIEmbeddings

from app.services.llm_config_service import ResolvedLLMConfig


def get_embedder(embed_config: ResolvedLLMConfig) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=embed_config.embedding_model,
        base_url=embed_config.base_url,
        api_key=embed_config.api_key,
    )


def embed_text(text: str, *, embed_config: ResolvedLLMConfig) -> list[float]:
    """单文本向量化。"""
    return get_embedder(embed_config).embed_query(text)


def embed_texts(texts: list[str], *, embed_config: ResolvedLLMConfig) -> list[list[float]]:
    """批量向量化。"""
    return get_embedder(embed_config).embed_documents(texts)
