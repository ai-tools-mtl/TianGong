def test_get_llm_returns_chat_model():
    from app.ai.llm_client import get_llm
    llm = get_llm()
    assert llm.model_name == "glm-4-flash"


def test_get_llm_streaming_flag():
    from app.ai.llm_client import get_llm
    llm = get_llm(streaming=True)
    assert llm.streaming is True


def test_astream_llm_is_async_generator():
    """astream_llm 返回 async generator（不实际调用 LLM）。"""
    import inspect
    from app.ai.llm_client import astream_llm
    from langchain_core.messages import HumanMessage

    gen = astream_llm([HumanMessage(content="hi")])
    assert inspect.isasyncgen(gen)


def test_stream_llm_still_exists():
    """同步 stream_llm 保留（审查引擎仍用）。"""
    from app.ai.llm_client import stream_llm
    assert callable(stream_llm)
