def test_get_llm_returns_chat_model():
    from app.ai.llm_client import get_llm
    llm = get_llm()
    assert llm.model_name == "glm-4-flash"


def test_get_llm_streaming_flag():
    from app.ai.llm_client import get_llm
    llm = get_llm(streaming=True)
    assert llm.streaming is True
