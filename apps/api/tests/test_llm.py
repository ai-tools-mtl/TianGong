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


# ── 1214 修复闸 1：get_llm 拦截空 model ──
# 根因：空 model 透传到 ChatOpenAI(model="") → 智谱回 1214（晦涩英文）。
# 这里在工厂入口提前拦住，抛清晰中文错误（会冒到 SSE error 事件给前端 toast）。

def test_get_llm_raises_when_model_empty():
    """model 为空串时 get_llm 抛 ValueError（含 'model' 关键字），不发请求。"""
    import pytest
    from app.ai.llm_client import get_llm
    cfg = ResolvedLLMConfig(
        base_url="https://x.example.com",
        api_key="sk-test",
        model="",  # ← 空 model
        source="user",
    )
    with pytest.raises(ValueError, match="model"):
        get_llm(cfg)


def test_get_llm_raises_when_model_none():
    """model 为 None 时同样抛 ValueError（防御 ResolvedLLMConfig 被构造时 model=None）。"""
    import pytest
    from app.ai.llm_client import get_llm
    cfg = ResolvedLLMConfig(
        base_url="https://x.example.com",
        api_key="sk-test",
        model=None,  # type: ignore[arg-type]  # 故意测异常输入
        source="user",
    )
    with pytest.raises(ValueError, match="model"):
        get_llm(cfg)
