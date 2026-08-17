# apps/api/tests/test_agent_usage_capture.py
"""P0-2：agent loop token 用量记账测试。

验证 orchestrator.astream_chat / astream_generate 的 on_chat_model_stream 分支
正确捕获 chunk.usage_metadata 写入 usage_sink：
- 单步生成：末块带 usage_metadata → usage_sink 填充 prompt + completion
- 多步（先 tool_call 再生成，on_chat_model_stream 触发多次）：completion 累加，
  prompt 取 last-wins

不真实调 GLM，mock build_agent 返回假 agent（astream_events 产出预设事件序列）。
"""
import asyncio
import uuid
from unittest.mock import MagicMock

import pytest


def _chunk(content="", usage=None, reasoning=None):
    """构造一个假 AIMessageChunk-like 对象。

    - content: 正文文本
    - usage: usage_metadata dict（仅末块携带），None 表示中间块
    - reasoning: additional_kwargs 的 reasoning_content（思考过程）
    """
    chunk = MagicMock()
    chunk.content = content
    chunk.usage_metadata = usage
    ak = {}
    if reasoning:
        ak["reasoning_content"] = reasoning
    chunk.additional_kwargs = ak
    return chunk


def _make_fake_agent(events):
    """构造假 CompiledStateGraph，astream_events 产出预设事件列表。

    签名含 config（checkpoint 批次起 _astream_agent_events 以
    astream_events(input, version="v2", config=...) 调用——config 可为 None）。
    """
    async def _astream_events(input, *, version=None, config=None):
        for evt in events:
            yield evt
    agent = MagicMock()
    agent.astream_events = _astream_events
    return agent


def _make_section():
    """构造一个最小 section mock。"""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.project_id = uuid.uuid4()
    s.title = "技术方案"
    s.key = "solution"
    return s


def _setup_orchestrator_mocks(monkeypatch, fake_agent, *, scene="chat"):
    """mock 掉 orchestrator 依赖的 build_agent / compress_history / classify_intent。

    让 astream_chat / astream_generate 直接用 fake_agent 跑事件流。
    """
    from app.ai import orchestrator as orch

    async def _fake_build_agent(db, *, llm_config, user_id, section=None,
                                user_input=None, intent=None, **kw):
        return fake_agent

    async def _noop_compress(history, current_input, llm_config, *, scene=None):
        snap = MagicMock()
        snap.triggered = False
        snap.to_dict.return_value = {}
        return [], snap

    # build_agent / classify_intent / compress_history 在函数体内 import，patch 源模块
    from app.ai import agent as agent_mod
    from app.ai import context_compactor as cc_mod
    monkeypatch.setattr(agent_mod, "build_agent", _fake_build_agent)
    monkeypatch.setattr(cc_mod, "compress_history", _noop_compress)


def test_astream_chat_captures_usage_single_step(monkeypatch, db_session):
    """单步生成：on_chat_model_stream 末块带 usage_metadata → usage_sink 填充。"""
    from app.ai.orchestrator import astream_chat

    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(content="你好")}, "name": "struct"},
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(content="，世界")}, "name": "struct"},
        # 末块：带 usage_metadata（stream_usage=True 时 provider 回填）
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(
            content="", usage={"input_tokens": 150, "output_tokens": 30}
        )}, "name": "struct"},
    ]
    fake_agent = _make_fake_agent(events)
    _setup_orchestrator_mocks(monkeypatch, fake_agent)

    usage_sink = {}
    section = _make_section()

    async def _run():
        async for _ in astream_chat(
            db_session, section, [], "你好",
            llm_config=MagicMock(model="glm-4.7"), usage_sink=usage_sink,
        ):
            pass

    asyncio.run(_run())

    assert usage_sink.get("prompt") == 150
    assert usage_sink.get("completion") == 30


def test_astream_chat_accumulates_completion_multi_step(monkeypatch, db_session):
    """多步调用（先 tool_call 再生成）：on_chat_model_stream 触发多次，completion 累加。

    模拟 agent loop：第一步调工具（on_tool_start/end），第二步生成正文。
    两次 on_chat_model_stream 各自末块带 usage_metadata → completion 相加。
    """
    from app.ai.orchestrator import astream_chat

    events = [
        # 第一步：工具调用（agent 决定先查知识库）
        {"event": "on_tool_start", "name": "rag_search", "data": {"input": {"query": "凸轮"}}},
        {"event": "on_tool_end", "name": "rag_search", "data": {"output": "相关内容"}},
        # 第一步的模型调用末块（tool calling 也消耗 token）
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(
            usage={"input_tokens": 100, "output_tokens": 10}
        )}, "name": "struct"},
        # 第二步：正文生成
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(content="根据检索结果")}, "name": "struct"},
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(
            usage={"input_tokens": 200, "output_tokens": 40}
        )}, "name": "struct"},
    ]
    fake_agent = _make_fake_agent(events)
    _setup_orchestrator_mocks(monkeypatch, fake_agent)

    usage_sink = {}
    section = _make_section()

    async def _run():
        async for _ in astream_chat(
            db_session, section, [], "查一下凸轮",
            llm_config=MagicMock(model="glm-4.7"), usage_sink=usage_sink,
        ):
            pass

    asyncio.run(_run())

    # completion 累加：10 + 40 = 50
    assert usage_sink.get("completion") == 50
    # prompt 取 last-wins：最后一次调用的 input_tokens（含完整上下文，最准）
    assert usage_sink.get("prompt") == 200


def test_astream_generate_captures_usage(monkeypatch, db_session):
    """astream_generate 同样捕获 usage（与 astream_chat 同逻辑）。"""
    from app.ai.orchestrator import astream_generate

    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(content="# 技术方案")}, "name": "struct"},
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(
            usage={"input_tokens": 300, "output_tokens": 80}
        )}, "name": "struct"},
    ]
    fake_agent = _make_fake_agent(events)
    _setup_orchestrator_mocks(monkeypatch, fake_agent)

    usage_sink = {}
    section = _make_section()

    async def _run():
        async for _ in astream_generate(
            db_session, section, [],
            llm_config=MagicMock(model="glm-4.7"), usage_sink=usage_sink,
        ):
            pass

    asyncio.run(_run())

    assert usage_sink.get("prompt") == 300
    assert usage_sink.get("completion") == 80


def test_usage_sink_none_does_not_crash(monkeypatch, db_session):
    """usage_sink=None 时不崩溃（向后兼容：调用方可能不传）。"""
    from app.ai.orchestrator import astream_chat

    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(
            content="ok", usage={"input_tokens": 10, "output_tokens": 5}
        )}, "name": "struct"},
    ]
    fake_agent = _make_fake_agent(events)
    _setup_orchestrator_mocks(monkeypatch, fake_agent)

    section = _make_section()
    tokens = []

    async def _run():
        async for kind, data in astream_chat(
            db_session, section, [], "hi",
            llm_config=MagicMock(model="glm-4.7"), usage_sink=None,
        ):
            if kind == "token":
                tokens.append(data)

    asyncio.run(_run())

    assert tokens == ["ok"]  # 正常流转，usage_sink=None 不影响


def test_no_usage_metadata_leaves_sink_empty(monkeypatch, db_session):
    """provider 未回传 usage_metadata（如不支持 stream_options）时 sink 保持空。

    向后兼容：部分 provider 可能不回传，此时 token 落 None（LLMCallLog 允许 NULL）。
    """
    from app.ai.orchestrator import astream_chat

    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": _chunk(content="ok", usage=None)}, "name": "struct"},
    ]
    fake_agent = _make_fake_agent(events)
    _setup_orchestrator_mocks(monkeypatch, fake_agent)

    usage_sink = {}
    section = _make_section()

    async def _run():
        async for _ in astream_chat(
            db_session, section, [], "hi",
            llm_config=MagicMock(model="glm-4.7"), usage_sink=usage_sink,
        ):
            pass

    asyncio.run(_run())

    assert "prompt" not in usage_sink
    assert "completion" not in usage_sink
