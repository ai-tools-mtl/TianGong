"""LLM 抽象层。封装 ChatOpenAI 接入 GLM（OpenAI 兼容协议）。"""

from collections.abc import AsyncIterator, Iterator

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def get_llm(
    streaming: bool = False,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> ChatOpenAI:
    """构造 LLM 实例。

    配置优先级：显式参数 > settings.glm_*。
    显式参数由调用方从 llm_config_service.resolve_llm_config() 解析后传入
    （用户 BYOK > 全局 SystemSetting），让 BYOK / 全局配置真正生效。
    无显式参数时回退 settings（保持向后兼容）。
    """
    s = get_settings()
    return ChatOpenAI(
        model=model or s.glm_model,
        base_url=base_url or s.glm_base_url,
        api_key=api_key or s.glm_api_key,
        streaming=streaming,
        temperature=0.7,
    )


def stream_llm(
    messages: list[BaseMessage],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> Iterator[str]:
    """流式调用 LLM，逐 token yield 文本。"""
    llm = get_llm(streaming=True, base_url=base_url, api_key=api_key, model=model)
    for chunk in llm.stream(messages):
        if chunk.content:
            yield chunk.content


async def astream_llm(
    messages: list[BaseMessage],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    """异步流式调用 LLM，逐 token yield 文本。

    用于 SSE 端点：客户端断开时 generator 被取消，底层 httpx 连接关闭，
    真正停止从 LLM API 拉取（不浪费 token）。
    """
    llm = get_llm(streaming=True, base_url=base_url, api_key=api_key, model=model)
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content
