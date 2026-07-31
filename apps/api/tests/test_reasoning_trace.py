"""Agent 透明化（思考过程 + 工具调用）透传测试。

覆盖三个层次：
1. ReasoningChatOpenAI._convert_chunk_to_generation_chunk：把 GLM delta.reasoning_content
   回填进 chunk.additional_kwargs（核心——langchain-openai 1.3.5 默认丢弃此字段）。
2. extract_reasoning：从 chunk 多路径读出 reasoning 文本。
3. orchestrator.astream_chat：astream_events 的 on_chat_model_stream 事件里，
   reasoning 被透传成 ("thinking", str) 元组（在 token 之前），tool 事件原样透传。

策略与 test_orchestrator.py 一致：mock build_agent，假 agent.astream_events yield
构造好的事件（含 reasoning_content 的 chunk / on_tool_start / on_tool_end），
不真实调 LLM。
"""
import asyncio
import uuid
from types import SimpleNamespace
from typing import AsyncIterator


# ── 层次 1+2：ReasoningChatOpenAI 字段透传 + extract_reasoning ──

def test_reasoning_chat_openai_propagates_reasoning_content():
    """[阶段0结论验证] GLM 的 reasoning_content 经 ReasoningChatOpenAI 回填到 additional_kwargs。

    模拟 _stream 里 chunk.model_dump() 后传给 _convert_chunk_to_generation_chunk 的结构
    （含 delta.reasoning_content——OpenAI SDK 因 extra='allow' 保留，langchain 默认丢弃）。
    """
    from langchain_core.messages import AIMessageChunk
    from app.ai.llm_client import ReasoningChatOpenAI, extract_reasoning

    llm = ReasoningChatOpenAI(model="gpt-4o", api_key="fake", base_url="http://fake")
    chunk = {
        "choices": [{
            "delta": {"role": "assistant", "reasoning_content": "我先想想这个问题..."},
            "index": 0,
        }],
    }
    gen = llm._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, {})
    assert gen is not None
    reasoning = extract_reasoning(gen.message)
    assert reasoning == "我先想想这个问题...", "reasoning 应被透传到 chunk"


def test_reasoning_chat_openai_no_side_effect_on_normal_chunks():
    """普通 OpenAI chunk（无 reasoning）不应受影响，content 正常。"""
    from langchain_core.messages import AIMessageChunk
    from app.ai.llm_client import ReasoningChatOpenAI, extract_reasoning

    llm = ReasoningChatOpenAI(model="gpt-4o", api_key="fake", base_url="http://fake")
    chunk = {"choices": [{"delta": {"role": "assistant", "content": "你好"}, "index": 0}]}
    gen = llm._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, {})
    assert gen.message.content == "你好"
    assert extract_reasoning(gen.message) is None
    assert gen.message.additional_kwargs == {}


def test_extract_reasoning_returns_none_for_empty():
    """无 reasoning 字段的 chunk，extract_reasoning 返回 None（不抛错）。"""
    from app.ai.llm_client import extract_reasoning
    assert extract_reasoning(None) is None
    assert extract_reasoning(SimpleNamespace(additional_kwargs={})) is None


# ── 层次 3：orchestrator.astream_chat 透传 thinking + tool 事件 ──

def _build_section_with_project(db_session):
    from app.models import Project, Section, User
    from app.core.security import hash_password
    u = User(
        username=f"test-{uuid.uuid4().hex[:8]}",
        email=f"test-{uuid.uuid4().hex[:8]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="测试用户",
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    p = Project(user_id=u.id, title="reasoning 透传测试项目")
    db_session.add(p); db_session.commit(); db_session.refresh(p)
    s = Section(project_id=p.id, template_section_id="ts-solution",
                order=5, key="solution", title="技术方案", content=None, status="empty")
    db_session.add(s); db_session.commit(); db_session.refresh(s)
    return s


def _make_agent_emitting_events(events: list):
    """返回假 build_agent，其 astream_events 按序 yield 给定事件。

    events 是 astream_events v2 的事件 dict 列表，形如：
      {"event":"on_chat_model_stream","data":{"chunk": <AIMessageChunk>}}
      {"event":"on_tool_start","name":"rag_search","data":{"input":{...}}}
      {"event":"on_tool_end","name":"rag_search","data":{"output":"..."}}
    """

    class _FakeAgent:
        def astream_events(self, input_, *, version="v2") -> AsyncIterator:
            return self._iter()

        async def _iter(self):
            for e in events:
                yield e

    async def _build_agent(db, *, llm_config, user_id, section=None, **kw):
        return _FakeAgent()

    return _build_agent


def _collect(async_gen):
    """同步消费 async generator，收集所有 (kind, payload) 元组。"""
    async def _drain():
        out = []
        async for item in async_gen:
            out.append(item)
        return out
    return asyncio.run(_drain())


def test_astream_chat_emits_thinking_before_token(db_session, monkeypatch):
    """[阶段1] on_chat_model_stream 的 reasoning 被透传成 ("thinking", ...)，且在 token 之前。"""
    from langchain_core.messages import AIMessageChunk
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    # 构造一个同时含 reasoning_content（additional_kwargs）和 content 的 chunk
    chunk = AIMessageChunk(content="答案是42", additional_kwargs={"reasoning_content": "让我想想"})
    events = [{"event": "on_chat_model_stream", "data": {"chunk": chunk}}]
    monkeypatch.setattr(agent_mod, "build_agent", _make_agent_emitting_events(events))

    section = _build_section_with_project(db_session)
    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    result = _collect(orch_mod.astream_chat(db_session, section, [], "你好", llm_config=config))

    kinds = [k for k, _ in result]
    # thinking 应在 token 之前（GLM 先思考后答）
    assert "thinking" in kinds, f"应透传 thinking 事件，实际: {kinds}"
    assert "token" in kinds
    assert kinds.index("thinking") < kinds.index("token"), "thinking 应在 token 之前"
    thinking_payload = next(p for k, p in result if k == "thinking")
    assert thinking_payload == "让我想想"
    token_payload = next(p for k, p in result if k == "token")
    assert token_payload == "答案是42"


def test_astream_chat_emits_tool_events(db_session, monkeypatch):
    """[阶段1] on_tool_start / on_tool_end 透传成 tool_call / tool_result 元组。"""
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    events = [
        {"event": "on_tool_start", "name": "rag_search", "data": {"input": {"query": "电池"}}},
        {"event": "on_tool_end", "name": "rag_search", "data": {"output": "[命中3条]"}},
    ]
    monkeypatch.setattr(agent_mod, "build_agent", _make_agent_emitting_events(events))

    section = _build_section_with_project(db_session)
    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    result = _collect(orch_mod.astream_chat(db_session, section, [], "查一下", llm_config=config))

    kinds = [k for k, _ in result]
    assert kinds == ["tool_call", "tool_result"]
    call = next(p for k, p in result if k == "tool_call")
    assert call["name"] == "rag_search"
    assert call["args"] == {"query": "电池"}
    res = next(p for k, p in result if k == "tool_result")
    assert res["name"] == "rag_search"
    assert "[命中3条]" in res["result"]


def test_astream_chat_thinking_and_tools_interleave(db_session, monkeypatch):
    """[阶段1] 完整序列：思考→工具→思考→token，全部透传且保序。"""
    from langchain_core.messages import AIMessageChunk
    from app.ai import orchestrator as orch_mod
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先搜一下"})}},
        {"event": "on_tool_start", "name": "rag_search", "data": {"input": {"query": "x"}}},
        {"event": "on_tool_end", "name": "rag_search", "data": {"output": "ok"}},
        {"event": "on_chat_model_stream", "data": {"chunk": AIMessageChunk(content="结论", additional_kwargs={"reasoning_content": "综合结果"})}},
    ]
    monkeypatch.setattr(agent_mod, "build_agent", _make_agent_emitting_events(events))

    section = _build_section_with_project(db_session)
    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    result = _collect(orch_mod.astream_chat(db_session, section, [], "复杂问题", llm_config=config))

    kinds = [k for k, _ in result]
    # 第二个 on_chat_model_stream 同时含 reasoning + content → thinking 在 token 前
    assert kinds == ["thinking", "tool_call", "tool_result", "thinking", "token"]


# ── 层次 4：_StreamMeta 累积 + build ──

def test_stream_meta_build_returns_none_when_empty():
    """无任何事件时 build() 返回 None（不污染 Message.meta 列）。"""
    from app.api.ai import _StreamMeta
    sm = _StreamMeta()
    assert sm.build() is None


def test_stream_meta_accumulates_tool_events_and_thinking():
    """累积 tool_call/tool_result/thinking，build() 组装成正确结构。"""
    from app.api.ai import _StreamMeta
    sm = _StreamMeta()
    sm.add_thinking("想")
    sm.add_thinking("一想")
    sm.add_tool_call("rag_search", {"query": "q"})
    sm.add_tool_result("rag_search", "[命中]")
    meta = sm.build()
    assert meta is not None
    assert meta["thinking"] == "想一想"  # 流式分块拼接
    assert len(meta["tool_events"]) == 2
    assert meta["tool_events"][0] == {"kind": "call", "name": "rag_search", "args": {"query": "q"}}
    assert meta["tool_events"][1] == {"kind": "result", "name": "rag_search", "result": "[命中]"}


def test_stream_meta_thinking_only():
    """只有 thinking（无工具）时 build() 只含 thinking 键。"""
    from app.api.ai import _StreamMeta
    sm = _StreamMeta()
    sm.add_thinking("纯思考")
    meta = sm.build()
    assert meta == {"thinking": "纯思考"}
    assert "tool_events" not in meta
