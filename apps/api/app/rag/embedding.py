"""Embedding 封装。用 LangChain OpenAIEmbeddings 接智谱 embedding-3。"""

from langchain_openai import OpenAIEmbeddings

from app.services.llm_config_service import ResolvedLLMConfig


def get_embedder(embed_config: ResolvedLLMConfig) -> OpenAIEmbeddings:
    if embed_config.embedding_model is None:
        raise ValueError(
            "当前 LLM 配置未指定 embedding 模型，无法构造 embedder。"
            "请在配置中补充 embedding_model 字段。"
        )
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
