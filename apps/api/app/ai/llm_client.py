"""LLM 抽象层。封装 ChatOpenAI 接入 GLM（OpenAI 兼容协议）。"""

import logging
from collections.abc import AsyncIterator, Iterator

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.services.llm_config_service import ResolvedChatConfig

logger = logging.getLogger("tiangong.llm")


def get_llm(
    llm_config: ResolvedChatConfig, *, streaming: bool = False, stream_usage: bool = False,
) -> ChatOpenAI:
    """构造 LLM 实例。用解析后的配置（用户自配/全局/admin）。

    streaming=True 时开启流式输出。
    stream_usage=True 时额外传 stream_options={include_usage: True}，
    让 LangChain 在流的最后一块 AIMessageChunk 上回填 usage_metadata
    （input_tokens/output_tokens），供 astream_llm 侧捕获用于 LLMCallLog
    记账（断链 C3）。默认关闭：部分 OpenAI 兼容提供商（Ollama / 自定义代理）
    不支持 stream_options，会返回空响应导致 JSONDecodeError。
    仅 astream_llm（rewrite 等直接流式路径）按需开启；
    agent loop 路径（chat/generate）不开启——usage_sink 在 agent loop 下
    本身不会被填充（见 orchestrator.py 注释），开了也白开，反而多一个兼容性风险。
    """
    # 防御闸（1214 修复）：空 model 透传给 ChatOpenAI 不会在客户端报错，
    # 会原样发给智谱 → 回 1214 "model code cannot be empty"（晦涩英文）。
    # 在工厂入口提前拦住，抛清晰中文错误（会冒到 SSE error 事件给前端 toast）。
    if not llm_config.model:
        raise ValueError("LLM 配置缺少 model，无法发起调用，请前往设置补全模型名")

    logger.info(
        "构造 ChatOpenAI: model=%s base_url=%s streaming=%s stream_usage=%s source=%s",
        llm_config.model,
        llm_config.base_url,
        streaming,
        stream_usage,
        llm_config.source,
    )
    return ChatOpenAI(
        model=llm_config.model,
        base_url=llm_config.base_url,
        api_key=llm_config.api_key,
        streaming=streaming,
        stream_usage=stream_usage,
        temperature=0.7,
    )


def stream_llm(messages: list[BaseMessage], *, llm_config: ResolvedChatConfig) -> Iterator[str]:
    """流式调用 LLM，逐 token yield 文本。"""
    llm = get_llm(llm_config, streaming=True)
    for chunk in llm.stream(messages):
        if chunk.content:
            yield chunk.content


async def astream_llm(
    messages: list[BaseMessage], *, llm_config: ResolvedChatConfig,
    usage_sink: dict | None = None,
) -> AsyncIterator[str]:
    """异步流式调用 LLM，逐 token yield 文本。

    用于 SSE 端点：客户端断开时 generator 被取消，底层 httpx 连接关闭，
    真正停止从 LLM API 拉取（不浪费 token）。

    usage_sink（断链 C3）：可选的可变 dict；流式过程中若 chunk 携带
    usage_metadata（LangChain 在 stream_usage=True 时于最后一块回填），
    把 input_tokens/output_tokens 写入 usage_sink，供调用方在流结束后
    记入 LLMCallLog。generator 无法 return 侧值，故用 holder 透传。
    """
    llm = get_llm(llm_config, streaming=True, stream_usage=True)
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content
        # 捕获 token 用量：usage_metadata 仅出现在最后一块（trailing chunk），
        # 中间块不带；故每块都尝试读（last-wins，实际只有末块命中）。
        # 异常/客户端取消未到末块时 sink 为空，token 落 None（正确：未完成调用）。
        usage = getattr(chunk, "usage_metadata", None)
        if usage and usage_sink is not None:
            usage_sink["prompt"] = usage.get("input_tokens")
            usage_sink["completion"] = usage.get("output_tokens")
