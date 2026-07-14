"""Embedding 封装。用 LangChain OpenAIEmbeddings 接智谱 embedding-3。"""

from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings


def get_embedder() -> OpenAIEmbeddings:
    s = get_settings()
    return OpenAIEmbeddings(
        model=s.glm_embedding_model,
        base_url=s.glm_base_url,
        api_key=s.glm_api_key,
    )


def embed_text(text: str) -> list[float]:
    """单文本向量化。"""
    return get_embedder().embed_query(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化。"""
    return get_embedder().embed_documents(texts)
