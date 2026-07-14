"""LLM 抽象层。封装 ChatOpenAI 接入 GLM（OpenAI 兼容协议）。"""

from collections.abc import AsyncIterator, Iterator

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def get_llm(streaming: bool = False) -> ChatOpenAI:
    """构造 LLM 实例。从 settings 读 GLM 配置。"""
    s = get_settings()
    return ChatOpenAI(
        model=s.glm_model,
        base_url=s.glm_base_url,
        api_key=s.glm_api_key,
        streaming=streaming,
        temperature=0.7,
    )


def stream_llm(messages: list[BaseMessage]) -> Iterator[str]:
    """流式调用 LLM，逐 token yield 文本。"""
    llm = get_llm(streaming=True)
    for chunk in llm.stream(messages):
        if chunk.content:
            yield chunk.content


async def astream_llm(messages: list[BaseMessage]) -> AsyncIterator[str]:
    """异步流式调用 LLM，逐 token yield 文本。

    用于 SSE 端点：客户端断开时 generator 被取消，底层 httpx 连接关闭，
    真正停止从 LLM API 拉取（不浪费 token）。
    """
    llm = get_llm(streaming=True)
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content
