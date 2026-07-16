from app.services.llm_config_service import ResolvedLLMConfig


def _cfg():
    return ResolvedLLMConfig(
        base_url="https://x.example.com",
        api_key="sk-test",
        model="glm-4-flash",
        embedding_model="embedding-3",
        source="user",
    )


def test_get_llm_returns_chat_model():
    from app.ai.llm_client import get_llm
    llm = get_llm(_cfg())
    assert llm.model_name == "glm-4-flash"


def test_get_llm_streaming_flag():
    from app.ai.llm_client import get_llm
    llm = get_llm(_cfg(), streaming=True)
    assert llm.streaming is True


def test_astream_llm_is_async_generator():
    """astream_llm 返回 async generator（不实际调用 LLM）。"""
    import inspect
    from app.ai.llm_client import astream_llm
    from langchain_core.messages import HumanMessage

    gen = astream_llm([HumanMessage(content="hi")], llm_config=_cfg())
    assert inspect.isasyncgen(gen)


def test_stream_llm_still_exists():
    """同步 stream_llm 保留（审查引擎仍用）。"""
    from app.ai.llm_client import stream_llm
    assert callable(stream_llm)


def test_get_embedder_raises_when_embedding_model_none():
    """embedding_model=None 时 get_embedder 抛清晰错误（而非 pydantic 晦涩报错）。"""
    import pytest
    from app.rag.embedding import get_embedder
    cfg = ResolvedLLMConfig(
        base_url="https://x.example.com",
        api_key="sk-test",
        model="glm-4-flash",
        embedding_model=None,
        source="user",
    )
    with pytest.raises(ValueError, match="embedding"):
        get_embedder(cfg)
