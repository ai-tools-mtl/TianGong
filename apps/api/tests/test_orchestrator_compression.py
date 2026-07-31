"""orchestrator 接入压缩的集成测试（mock agent，验证压缩被调用）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.orchestrator import astream_chat
from app.models import Message


def _make_section():
    s = MagicMock()
    s.id = "00000000-0000-0000-0000-000000000001"
    s.project_id = "00000000-0000-0000-0000-000000000002"
    s.key = "technical_problem"
    s.title = "技术问题"
    s.status = "drafting"
    return s


def _make_history(n: int) -> list:
    objs = []
    for i in range(n):
        m = MagicMock()
        m.role = "user" if i % 2 == 0 else "assistant"
        m.content = f"历史消息-{i}" * 5
        objs.append(m)
    return objs


def _fake_llm_returning(summary_text: str):
    """构造一个 fake LLM：ainvoke 返回固定摘要文本（供 summarize 调用）。"""
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content=summary_text))
    return fake_llm


@pytest.mark.asyncio
async def test_astream_chat_compresses_long_history(monkeypatch):
    """35 条历史触发压缩 → mock agent 收到的 messages 含摘要标记。

    NOTE: compress_history 触发后调用 summarize → get_llm → 真实 LLM。
    若不 mock get_llm，summarize 会失败（SummarizeRuntimeError）→ fallback
    硬截断（无摘要标记），断言无法通过。故此处必须 mock get_llm，
    覆盖压缩成功路径（spec §5.1，非 fallback 路径）。
    """
    section = _make_section()
    history = _make_history(35)
    cfg = MagicMock(); cfg.model = "glm-4"; cfg.base_url = "x"; cfg.api_key = "y"

    # mock 压缩主流程里的 get_llm，让 summarize 返回成功摘要（不走 fallback）
    monkeypatch.setattr(
        "app.ai.context_compactor.get_llm",
        lambda *a, **k: _fake_llm_returning("技术问题与方案摘要内容"),
    )

    captured_messages = []

    class FakeAgent:
        async def astream_events(self, payload, version=None):
            captured_messages.extend(payload.get("messages", []))
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="hi")}}

    async def fake_build_agent(*a, **kw):
        return FakeAgent()

    monkeypatch.setattr("app.ai.orchestrator.build_agent", fake_build_agent, raising=False)
    monkeypatch.setattr("app.ai.agent.build_agent", fake_build_agent)
    monkeypatch.setattr("app.ai.intent.classify_intent", lambda x: "info")
    monkeypatch.setattr("app.ai.orchestrator._section_owner", lambda db, s: None)

    tokens = []
    async for kind, payload in astream_chat(None, section, history, "当前问题", llm_config=cfg):
        if kind == "token":
            tokens.append(payload)

    assert tokens == ["hi"]
    contents = [m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "") for m in captured_messages]
    assert any("早期对话历史摘要" in c for c in contents), "长历史应被压缩并含摘要标记"
    # 压缩成功路径不应回退硬截断
    assert all("已归档" in c or "早期对话历史摘要" not in c for c in contents)


@pytest.mark.asyncio
async def test_astream_chat_short_history_not_compressed(monkeypatch):
    """5 条历史不触发压缩 → messages 原样透传。"""
    section = _make_section()
    history = _make_history(5)
    cfg = MagicMock(); cfg.model = "glm-4"; cfg.base_url = "x"; cfg.api_key = "y"

    captured_messages = []

    class FakeAgent:
        async def astream_events(self, payload, version=None):
            captured_messages.extend(payload.get("messages", []))
            if False:
                yield {}

    async def fake_build_agent(*a, **kw):
        return FakeAgent()

    monkeypatch.setattr("app.ai.agent.build_agent", fake_build_agent)
    monkeypatch.setattr("app.ai.intent.classify_intent", lambda x: "info")
    monkeypatch.setattr("app.ai.orchestrator._section_owner", lambda db, s: None)

    async for _ in astream_chat(None, section, history, "当前问题", llm_config=cfg):
        pass

    contents = [m.get("content", "") for m in captured_messages]
    assert not any("早期对话历史摘要" in c for c in contents), "短历史不应被压缩"


# ── 项目初始化助手（init_orchestrator）接入压缩 ──
from app.ai.init_orchestrator import astream_init_chat  # noqa: E402


@pytest.mark.asyncio
async def test_astream_init_chat_compresses_long_history(monkeypatch):
    """init 助手 35 条历史触发压缩（测降级路径，与主路径共用 compress_history）。"""
    from app.ai.init_orchestrator import _astream_init_chat_fallback
    history = _make_history(35)
    cfg = MagicMock(); cfg.model = "glm-4"; cfg.base_url = "x"; cfg.api_key = "y"

    captured_messages = []

    async def fake_astream_llm(messages, *, llm_config, usage_sink=None):
        captured_messages.extend(messages)
        yield "tok"

    monkeypatch.setattr("app.ai.init_orchestrator.astream_llm", fake_astream_llm)
    # ALSO mock get_llm used by compress_history→summarize (long history triggers summarize)
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content="技术方案摘要内容"))
    monkeypatch.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)

    # 降级路径 yield ("token", str) 元组
    tokens = []
    async for kind, payload in _astream_init_chat_fallback(history, "当前问题", llm_config=cfg):
        if kind == "token":
            tokens.append(payload)

    assert tokens == ["tok"]
    contents = [getattr(m, "content", "") for m in captured_messages]
    assert any("早期对话历史摘要" in c for c in contents), "init 长历史应被压缩"


@pytest.mark.asyncio
async def test_astream_init_chat_short_history_not_compressed(monkeypatch):
    """init 助手 5 条历史不触发压缩（测降级路径）。"""
    from app.ai.init_orchestrator import _astream_init_chat_fallback
    history = _make_history(5)
    cfg = MagicMock(); cfg.model = "glm-4"; cfg.base_url = "x"; cfg.api_key = "y"

    captured_messages = []

    async def fake_astream_llm(messages, *, llm_config, usage_sink=None):
        captured_messages.extend(messages)
        if False:
            yield ""

    monkeypatch.setattr("app.ai.init_orchestrator.astream_llm", fake_astream_llm)

    async for _ in _astream_init_chat_fallback(history, "当前问题", llm_config=cfg):
        pass

    contents = [getattr(m, "content", "") for m in captured_messages]
    assert not any("早期对话历史摘要" in c for c in contents)


@pytest.mark.asyncio
async def test_astream_chat_writes_meta_sink(monkeypatch):
    """C1：长历史触发压缩时，meta_sink 应被写入 snapshot.to_dict()（供 _log_llm_call 记 context_meta）。"""
    section = _make_section()
    history = _make_history(35)
    cfg = MagicMock(); cfg.model = "glm-4"; cfg.base_url = "x"; cfg.api_key = "y"

    class FakeAgent:
        async def astream_events(self, payload, version=None):
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="hi")}}

    async def fake_build_agent(*a, **kw):
        return FakeAgent()

    monkeypatch.setattr("app.ai.agent.build_agent", fake_build_agent)
    monkeypatch.setattr("app.ai.intent.classify_intent", lambda x: "info")
    monkeypatch.setattr("app.ai.orchestrator._section_owner", lambda db, s: None)
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content="摘要内容"))
    monkeypatch.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)

    meta_sink = {}
    async for _ in astream_chat(
        None, section, history, "当前问题", llm_config=cfg, meta_sink=meta_sink
    ):
        pass

    # meta_sink 应被写入 context_meta，含完整 snapshot 字段
    assert "context_meta" in meta_sink
    cm = meta_sink["context_meta"]
    assert cm["triggered"] is True
    assert cm["original_count"] == 35
    assert cm["reason"] == "messages>30"
    assert cm["fallback"] is False
