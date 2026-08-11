# apps/api/tests/test_llm_timeout_retry.py
"""P0-3/P0-4：LLM 调用超时 + 重试测试。

P0-3：get_llm 返回的 ChatOpenAI 实例带 request_timeout=120（替代 SDK 默认 600s）。
P0-4：astream_llm 和 invoke_llm 对瞬时错误（429/5xx/连接）做指数退避重试，
      且流式路径「一旦产出 token 就不重试」。
"""
import asyncio
from unittest.mock import MagicMock

import pytest


def _fake_llm_config():
    from app.services.llm_config_service import ResolvedChatConfig
    return ResolvedChatConfig(
        base_url="http://x", api_key="k", model="glm-4.7", source="env",
    )


# ── P0-3：request_timeout ──────────────────────────────────────────────

def test_get_llm_has_request_timeout():
    """get_llm 返回的实例 request_timeout=120（P0-3）。"""
    from app.ai.llm_client import get_llm, LLM_REQUEST_TIMEOUT

    llm = get_llm(_fake_llm_config())
    assert llm.request_timeout == LLM_REQUEST_TIMEOUT
    assert llm.request_timeout == 120


def test_get_llm_streaming_has_request_timeout():
    """流式模式同样带 timeout。"""
    from app.ai.llm_client import get_llm

    llm = get_llm(_fake_llm_config(), streaming=True, stream_usage=True)
    assert llm.request_timeout == 120


# ── P0-4：invoke_llm 重试 ──────────────────────────────────────────────

def test_invoke_llm_retries_on_rate_limit():
    """invoke_llm 遇 RateLimitError 重试，最终成功。"""
    from openai import RateLimitError
    from app.ai.llm_client import invoke_llm
    from app.ai import llm_client as mod

    call_count = {"n": 0}

    class _FakeLLM:
        def invoke(self, messages):
            call_count["n"] += 1
            if call_count["n"] < 3:
                # RateLimitError 需要 message/response/body 构造
                resp = MagicMock()
                resp.status_code = 429
                resp.headers = {}
                raise RateLimitError("rate limited", response=resp, body=None)
            return MagicMock(content="<mxfile>ok</mxfile>")

    # mock get_llm 返回假实例（跳过真实 HTTP）
    orig_get_llm = mod.get_llm
    mod.get_llm = lambda config, **kw: _FakeLLM()
    try:
        # 缩短重试等待时间（避免测试慢）
        orig_min, orig_max = mod._RETRY_MIN_WAIT, mod._RETRY_MAX_WAIT
        mod._RETRY_MIN_WAIT, mod._RETRY_MAX_WAIT = 0.01, 0.05
        try:
            result = invoke_llm(_fake_llm_config(), [])
        finally:
            mod._RETRY_MIN_WAIT, mod._RETRY_MAX_WAIT = orig_min, orig_max
    finally:
        mod.get_llm = orig_get_llm

    assert call_count["n"] == 3, f"应重试到第 3 次成功，实际 {call_count['n']}"
    assert result.content == "<mxfile>ok</mxfile>"


def test_invoke_llm_does_not_retry_on_non_retryable():
    """invoke_llm 遇非瞬时错误（如 ValueError）不重试，直接抛出。"""
    from app.ai.llm_client import invoke_llm
    from app.ai import llm_client as mod

    call_count = {"n": 0}

    class _FakeLLM:
        def invoke(self, messages):
            call_count["n"] += 1
            raise ValueError("非瞬时错误，不应重试")

    orig_get_llm = mod.get_llm
    mod.get_llm = lambda config, **kw: _FakeLLM()
    try:
        with pytest.raises(ValueError, match="不应重试"):
            invoke_llm(_fake_llm_config(), [])
    finally:
        mod.get_llm = orig_get_llm

    assert call_count["n"] == 1, "非瞬时错误不应重试"


# ── P0-4：astream_llm 重试（连接建立阶段）──────────────────────────────

def test_astream_llm_retries_first_chunk_on_connection_error(monkeypatch):
    """astream_llm 建立连接时遇 APIConnectionError 重试，拿到首块后不再重试。"""
    from openai import APIConnectionError
    from app.ai.llm_client import astream_llm
    from app.ai import llm_client as mod
    from langchain_core.messages import HumanMessage

    attempt = {"n": 0}

    class _FakeChunk:
        def __init__(self, content, usage=None):
            self.content = content
            self.usage_metadata = usage

    class _FakeStream:
        """假 async 迭代器。"""
        def __init__(self, chunks):
            self._chunks = chunks
            self._idx = 0
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self._idx >= len(self._chunks):
                raise StopAsyncIteration
            c = self._chunks[self._idx]
            self._idx += 1
            return c

    class _FakeLLM:
        """首次 astream 抛连接错误，第二次成功。"""
        def astream(self, messages):
            attempt["n"] += 1
            if attempt["n"] == 1:
                raise APIConnectionError(request=MagicMock())
            return _FakeStream([
                _FakeChunk("你好"),
                _FakeChunk("世界", usage={"input_tokens": 10, "output_tokens": 5}),
            ])

    monkeypatch.setattr(mod, "get_llm", lambda config, **kw: _FakeLLM())
    monkeypatch.setattr(mod, "_RETRY_MIN_WAIT", 0.01)
    monkeypatch.setattr(mod, "_RETRY_MAX_WAIT", 0.05)

    usage = {}
    tokens = []

    async def _run():
        async for t in astream_llm(
            [HumanMessage(content="hi")], llm_config=_fake_llm_config(), usage_sink=usage,
        ):
            tokens.append(t)

    asyncio.run(_run())

    assert attempt["n"] == 2, "首次失败应重试一次后成功"
    assert tokens == ["你好", "世界"]
    assert usage.get("prompt") == 10
    assert usage.get("completion") == 5


def test_astream_llm_no_retry_after_first_token(monkeypatch):
    """首块拿到后，后续流失败不重试（已产出 token 无法撤回）。"""
    from openai import APIConnectionError
    from app.ai.llm_client import astream_llm
    from app.ai import llm_client as mod
    from langchain_core.messages import HumanMessage

    class _FakeChunk:
        def __init__(self, content):
            self.content = content
            self.usage_metadata = None

    class _FakeStream:
        """产出首块后，第二个 chunk 抛错。"""
        def __init__(self):
            self._idx = 0
        def __aiter__(self):
            return self
        async def __anext__(self):
            self._idx += 1
            if self._idx == 1:
                return _FakeChunk("第一个token")
            # 第二次迭代抛错——不应触发重试（已有 token 产出）
            raise APIConnectionError(request=MagicMock())

    class _FakeLLM:
        def astream(self, messages):
            return _FakeStream()

    monkeypatch.setattr(mod, "get_llm", lambda config, **kw: _FakeLLM())
    monkeypatch.setattr(mod, "_RETRY_MIN_WAIT", 0.01)
    monkeypatch.setattr(mod, "_RETRY_MAX_WAIT", 0.05)

    tokens = []

    async def _run():
        async for t in astream_llm(
            [HumanMessage(content="hi")], llm_config=_fake_llm_config(),
        ):
            tokens.append(t)

    # 首块后的错误应直接抛出（不重试、不吞）
    with pytest.raises(APIConnectionError):
        asyncio.run(_run())

    # 首块 token 已产出
    assert tokens == ["第一个token"]
