"""LLM 抽象层。封装 ChatOpenAI 接入 GLM（OpenAI 兼容协议）。"""

import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_openai import ChatOpenAI

from app.services.llm_config_service import ResolvedChatConfig

logger = logging.getLogger("tiangong.llm")


def extract_reasoning(chunk: Any) -> str | None:
    """从 LangChain chunk 中提取模型的思考过程（reasoning）。

    背景：langchain-openai 1.3.5 的 `_convert_delta_to_message_chunk` 只读
    OpenAI delta 的 `content`，把 provider 扩展字段（GLM 的 `reasoning_content`、
    DeepSeek 的 `reasoning_content` 等）丢弃——这些字段到不了 on_chat_model_stream。

    为此本模块自定义了 `ReasoningChatOpenAI`，把 delta 的 `reasoning_content`
    回填进 chunk 的 `additional_kwargs["reasoning_content"]`（见下）。本函数即
    从该位置读出思考文本，供 orchestrator 透传成 ("thinking", text) 事件。

    防御性多路径读取：兼容不同 provider 可能的字段名（reasoning_content /
    reasoning / thinking），以及个别版本可能放进 response_metadata 的情形。
    """
    # 主路径：ReasoningChatOpenAI 已把 reasoning_content 回填到 additional_kwargs
    ak = getattr(chunk, "additional_kwargs", None) or {}
    text = ak.get("reasoning_content") or ak.get("reasoning") or ak.get("thinking")
    if text:
        return text
    # 兜底：部分 provider 可能放 response_metadata
    rm = getattr(chunk, "response_metadata", None) or {}
    return rm.get("reasoning_content") or rm.get("reasoning")


class ReasoningChatOpenAI(ChatOpenAI):
    """自定义 ChatOpenAI：透传 GLM 等 provider 的 reasoning_content（思考过程）。

    langchain-openai 1.3.5 官方 ChatOpenAI 只取 OpenAI delta 的 `content`，
    丢弃 provider 扩展的 `reasoning_content` 字段（GLM-4.x 思考模型、DeepSeek-R1
    等推理模型都用此字段返回思考过程）。本子类重写流式 chunk 转换，把
    `reasoning_content` 回填进 AIMessageChunk.additional_kwargs，使下游
    astream_events 的 on_chat_model_stream 能拿到，从而透传给前端展示。

    重写要点：仅覆盖 `_convert_chunk_to_generation_chunk`，在父类转换完成后，
    从原始 delta dict 里捞 `reasoning_content` 写到 message_chunk 上。
    其它行为完全沿用父类（_stream / astream / 序列化 / usage 捕获等不变）。
    """

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ):  # type: ignore[override]
        gen_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if gen_chunk is None:
            return None
        # 从原始 SSE chunk 里捞 reasoning_content（provider 扩展字段，
        # OpenAI SDK 因 extra='allow' 在 model_dump() 后保留；langchain 默认丢弃）。
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
        if choices:
            delta = choices[0].get("delta") or {}
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning and isinstance(gen_chunk.message, AIMessageChunk):
                # 累加进 additional_kwargs（流式分块会由 LangChain 自动合并）
                existing = gen_chunk.message.additional_kwargs.get("reasoning_content", "")
                gen_chunk.message.additional_kwargs["reasoning_content"] = existing + reasoning
        return gen_chunk


def get_llm(
    llm_config: ResolvedChatConfig, *, streaming: bool = False, stream_usage: bool = False,
) -> ChatOpenAI:
    """构造 LLM 实例。用解析后的配置（用户自配/全局/admin）。

    返回 ReasoningChatOpenAI（ChatOpenAI 子类）——透传 GLM/DeepSeek 等推理模型的
    reasoning_content（思考过程），供 agent loop 透传到前端展示（见 extract_reasoning）。
    非推理模型无此字段，行为与原 ChatOpenAI 完全一致，无副作用。

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
    return ReasoningChatOpenAI(
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
