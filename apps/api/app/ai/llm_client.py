"""LLM 抽象层。封装 ChatOpenAI 接入 GLM（OpenAI 兼容协议）。"""

import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
)

from app.services.llm_config_service import ResolvedChatConfig

logger = logging.getLogger("tiangong.llm")


# ── P0-3/P0-4：超时与重试策略 ──────────────────────────────────────────
# 单次 HTTP 请求超时（秒）。与 AGENT_LOOP_TOTAL_TIMEOUT=120 对齐；
# figure（同步 llm.invoke）和 rewrite（裸 astream_llm）也走此值，不再用 SDK 默认的 600s。
LLM_REQUEST_TIMEOUT = 120

# 可重试的瞬时错误类型：连接错误（含超时，APITimeoutError 是其子类）、限流、服务端 5xx。
# 注意：余额不足（智谱 1113）是 APIStatusError 的子类但不在列表里，不重试（重试也是徒劳）。
_RETRYABLE_EXCEPTIONS = (
    APIConnectionError,   # 含 APITimeoutError（子类）、连接重置、DNS 失败
    RateLimitError,       # 429 限流（指数退避后通常可恢复）
    InternalServerError,  # 5xx 服务端临时故障
)

# 重试配置：最多 3 次（含首次），指数退避 1→2→4s，上限 8s。
_RETRY_ATTEMPTS = 3
_RETRY_MULTIPLIER = 1
_RETRY_MIN_WAIT = 1
_RETRY_MAX_WAIT = 8


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
        # P0-3：显式 request_timeout，替代 openai SDK 默认的 600s。
        # 与 AGENT_LOOP_TOTAL_TIMEOUT=120 对齐；figure（同步 invoke）/ rewrite（裸 astream）也覆盖。
        request_timeout=LLM_REQUEST_TIMEOUT,
    )


def stream_llm(messages: list[BaseMessage], *, llm_config: ResolvedChatConfig) -> Iterator[str]:
    """流式调用 LLM，逐 token yield 文本（同步版，旧 orchestrator 兼容路径）。

    注意：主链路已迁到 agent loop（异步 astream_llm），此函数仅旧 stream_chat/
    stream_generate/stream_rewrite 的兼容路径用。同步重试实现复杂（迭代器 + retryer
    交织易出错）且此路径非主线，故不加重试——仅靠 P0-3 的 request_timeout 兜底超时。
    真正的重试保护在 astream_llm（异步主线）和 invoke_llm（非流式 figure 等）。
    """
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

    P0-4 重试：连接建立阶段（首个 chunk 前）对瞬时错误做指数退避重试。
    一旦开始 yield token 就不再重试（已吐出的内容无法撤回）。
    """
    llm = get_llm(llm_config, streaming=True, stream_usage=True)

    # 重试只保护「建立连接取首块」——这是 HTTP 请求真正发出的时刻。
    # 拿到首块后离开重试块，后续 chunk 的失败直接上抛（token 已产出无法撤回）。
    # 注意：首块与后续块必须来自同一个流迭代器（langchain 每次 astream() 调用
    # 返回独立的新流，会重新发请求）。故 _astream_first_chunk_with_retry 返回
    # (流迭代器, 首块)，后续继续消费同一迭代器。
    stream_iter, first_chunk = await _astream_first_chunk_with_retry(llm, messages)

    # 处理首块（可能与后续块一样含 content/usage）
    if first_chunk.content:
        yield first_chunk.content
    _capture_usage(first_chunk, usage_sink)

    # 消费剩余流（不重试，同一迭代器）
    async for chunk in stream_iter:
        if chunk.content:
            yield chunk.content
        _capture_usage(chunk, usage_sink)


def _capture_usage(chunk: Any, usage_sink: dict | None) -> None:
    """从 chunk 读 usage_metadata 写入 sink（末块才有，每块都试，last-wins）。

    异常/客户端取消未到末块时 sink 为空，token 落 None（正确：未完成调用）。
    """
    usage = getattr(chunk, "usage_metadata", None)
    if usage and usage_sink is not None:
        usage_sink["prompt"] = usage.get("input_tokens")
        usage_sink["completion"] = usage.get("output_tokens")


async def _astream_first_chunk_with_retry(llm, messages) -> tuple[Any, Any]:
    """用 tenacity 重试获取流的首个 chunk（连接建立阶段保护）。

    返回 (流迭代器, 首块)。重试时整个流重新建立（每次 astream() 是独立请求），
    成功后返回的迭代器供调用方继续消费剩余 chunk。
    """
    from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

    def _log_retry(rs):
        sleep_s = rs.next_action.sleep if rs.next_action else 0
        logger.warning(
            "LLM 异步流式调用失败，%.1fs 后重试（第 %d/%d 次）: %s",
            sleep_s, rs.attempt_number, _RETRY_ATTEMPTS, rs.outcome.exception(),
        )

    retryer = AsyncRetrying(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        wait=wait_exponential(multiplier=_RETRY_MULTIPLIER, min=_RETRY_MIN_WAIT, max=_RETRY_MAX_WAIT),
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        reraise=True,
        before_sleep=_log_retry,
    )
    # retry 块内每次重新建立流（astream 每次返回独立迭代器）。
    # 拿到首块即返回该迭代器 + 首块，供后续继续消费。
    async for attempt in retryer:
        with attempt:
            stream = llm.astream(messages)
            first = await stream.__anext__()
            return stream, first


def invoke_llm(llm_config: ResolvedChatConfig, messages: list[BaseMessage]) -> Any:
    """非流式调用 LLM（同步，带重试）。

    供 figure_service / summary_service 等同步 .invoke() 路径用。
    P0-3 的 request_timeout + P0-4 的重试都在此生效。
    返回 LLM 的响应 message（含 .content）。
    """
    from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

    llm = get_llm(llm_config)

    def _log_retry(rs):
        sleep_s = rs.next_action.sleep if rs.next_action else 0
        logger.warning(
            "LLM 非流式调用失败，%.1fs 后重试（第 %d/%d 次）: %s",
            sleep_s, rs.attempt_number, _RETRY_ATTEMPTS, rs.outcome.exception(),
        )

    retryer = Retrying(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        wait=wait_exponential(multiplier=_RETRY_MULTIPLIER, min=_RETRY_MIN_WAIT, max=_RETRY_MAX_WAIT),
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        reraise=True,
        before_sleep=_log_retry,
    )
    for attempt in retryer:
        with attempt:
            return llm.invoke(messages)
