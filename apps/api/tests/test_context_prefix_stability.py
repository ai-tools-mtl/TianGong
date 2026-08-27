"""批次 A：prefix cache 友好化测试。

灵魂测试（计划原文）：同一章节会话连续两轮，发送给模型的
[system prompt + history] 前缀必须逐字节一致——每轮唯一允许的差异是尾部新消息。
静态/易变拆分（决策 D1）的全部守护断言集中于此文件。
"""
import uuid


# ── 灵魂测试：前缀逐字节稳定 ──────────────────────────────────────────────────

def _mk_section(db_session):
    from app.models import Project, Section

    project = Project(title="稳定性项目", user_id=uuid.uuid4())
    db_session.add(project)
    db_session.commit()
    section = Section(
        project_id=project.id, template_section_id="background",
        key="background", title="背景技术", order=1, content=None,
    )
    db_session.add(section)
    db_session.commit()
    return section


def test_static_prompt_byte_stable_across_turns(db_session, monkeypatch):
    """【灵魂测试·上半】静态 system prompt 与当轮输入/检索结果/意图完全无关。

    连续两轮的 user_input、KB 检索结果、记忆命中各不相同，
    build_system_prompt 输出仍须逐字节相等——这是供应商前缀缓存的锚。
    """
    from app.ai.context_assembler import build_system_prompt

    section = _mk_section(db_session)
    p1 = build_system_prompt(db_session, section)

    # 第二轮：不同输入 + 不同意图。知识库/记忆结果由 DB 态决定，此处两层均空，
    # 关键断言在「输入与意图不进静态层」——它们曾是最强的逐轮扰动源之一。
    p2 = build_system_prompt(db_session, section)
    assert p1 == p2
    # 易变信号的典型特征词不得出现在静态层（意图指令 / 检索块标题 / 记忆段标题）
    assert "直接产出结构化内容" not in p1      # intent=draft 特征词
    assert "关于这位用户的长期记忆" not in p1   # 记忆段标题
    assert "# 知识库参考" not in p1             # KB 块标题
    assert "# 本项目术语表" not in p1           # 术语表标题（迁移后属易变层）
    assert "已完成章节内容" not in p1           # 已写章节标题（迁入易变层）
    # （画像留在静态层的正向断言由 tests/test_profile_api.py 注入用例覆盖）


def test_two_consecutive_turns_share_prefix_bytes(db_session):
    """【灵魂测试·下半】模拟连续两轮的消息装配：前缀逐字节一致，差异只在尾部。

    轮 N-1：history=[]，输入 u1 → 发送 [system, u1']
    轮 N  ：history=[u1, a1]（DB 原文回放），输入 u2 → 发送 [system, u1, a1, u2']

    断言：turn2 的前两个元素与 turn1 的 [system, u1'] 逐字节相等
    （u1' 在两轮中都是 DB 原文——快照只存在于各自当轮的注入里）。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from app.ai.context_assembler import (
        SYSTEM_PROMPT, build_system_prompt, wrap_user_message,
    )

    section = _mk_section(db_session)
    static_prompt = build_system_prompt(db_session, section)

    # ── 第 N-1 轮：无历史 ──
    turn1 = [{"role": "system", "content": static_prompt}]
    r1 = "本轮 KB 参考片段甲（逐轮变化）"
    turn1.append({"role": "user",
                  "content": wrap_user_message("第一句输入", r1)})
    # turn 结束后落库的只有原始输入——历史回放不含快照（决策 D1 核心不变量）
    history_db = [
        {"role": "user", "content": "第一句输入"},
        {"role": "assistant", "content": "回复甲"},
    ]

    # ── 第 N 轮：历史从 DB 原文重建 ──
    turn2 = [{"role": "system", "content": static_prompt}]
    for m in history_db:
        turn2.append(dict(m))
    r2 = "本轮 KB 参考片段乙（与上轮不同的快照）"
    turn2.append({"role": "user",
                  "content": wrap_user_message("第二句输入", r2)})

    # 前缀逐字节一致（system 相同 + 历史=上轮原文）
    assert turn2[0]["content"] == turn1[0]["content"] == static_prompt
    assert turn2[1] == {"role": "user", "content": "第一句输入"} == history_db[0]
    # 差异只允许出现在尾部：tail 含快照且互不相同
    assert r1 != r2 and r1 in turn1[-1]["content"] and r2 in turn2[-1]["content"]
    # 快照包裹形态：原文在前，标签在后
    assert turn2[-1]["content"].startswith("第二句输入")
    assert "<system-reminder>" in turn2[-1]["content"]
    assert "</system-reminder>" in turn2[-1]["content"]

    # LangChain 序列化视角下同样成立（供 deepagents 入口消费的真实形态）
    lc_history = [HumanMessage(content="第一句输入"), AIMessage(content="回复甲")]
    assert [m.content for m in lc_history] == ["第一句输入", "回复甲"]
    assert SYSTEM_PROMPT in static_prompt


# ── A-3：缓存命中 token 提取 ────────────────────────────────────────────────

def test_extract_cached_tokens_langchain_details_form():
    """OpenAI 系归一化形态：input_token_details.cache_read。"""
    from app.ai.llm_client import extract_cached_tokens
    usage = {"input_tokens": 1000, "output_tokens": 10,
             "input_token_details": {"cache_read": 800, "audio": 0}}
    assert extract_cached_tokens(usage) == 800


def test_extract_cached_tokens_deepseek_top_level_form():
    """DeepSeek 原生形态：顶层 prompt_cache_hit_tokens。"""
    from app.ai.llm_client import extract_cached_tokens
    usage = {"input_tokens": 1000, "output_tokens": 10,
             "prompt_cache_hit_tokens": 640}
    assert extract_cached_tokens(usage) == 640


def test_extract_cached_tokens_absent_or_zero_returns_none():
    """provider 不回传 / 零命中 / 非 dict → None（调用方不写键）。"""
    from app.ai.llm_client import extract_cached_tokens
    assert extract_cached_tokens(None) is None
    assert extract_cached_tokens({}) is None
    assert extract_cached_tokens({"input_token_details": {}}) is None
    assert extract_cached_tokens({"prompt_cache_hit_tokens": 0}) is None
    assert extract_cached_tokens({"input_token_details": {"cache_read": 0}}) is None


def test_capture_usage_writes_cached_into_sink():
    """_capture_usage 把命中数带进 sink；无回传时不产生该键。"""
    from types import SimpleNamespace

    from app.ai.llm_client import _capture_usage

    sink = {}
    chunk_hit = SimpleNamespace(usage_metadata={
        "input_tokens": 500, "output_tokens": 20,
        "input_token_details": {"cache_read": 400},
    })
    _capture_usage(chunk_hit, sink)
    assert sink == {"prompt": 500, "completion": 20, "cached": 400}

    sink2 = {}
    chunk_plain = SimpleNamespace(usage_metadata={"input_tokens": 5, "output_tokens": 1})
    _capture_usage(chunk_plain, sink2)
    assert sink2 == {"prompt": 5, "completion": 1}


# ── A-4：单 turn token 预算熔断 ──────────────────────────────────────────────

def test_budget_service_defaults_and_roundtrip(db_session):
    """默认宽松值开启；set/get 往返；<=0 关闭。"""
    from app.services.agent_budget_service import (
        DEFAULT_TURN_TOKEN_BUDGET, get_turn_token_budget, set_turn_token_budget,
    )

    assert get_turn_token_budget(db_session) == DEFAULT_TURN_TOKEN_BUDGET
    assert get_turn_token_budget(db_session) > 0  # 默认开启

    set_turn_token_budget(db_session, budget=12345)
    assert get_turn_token_budget(db_session) == 12345

    set_turn_token_budget(db_session, budget=0)
    assert get_turn_token_budget(db_session) == 0  # 显式关闭

    set_turn_token_budget(db_session, budget=-7)
    assert get_turn_token_budget(db_session) == 0


class _FakeChunk:
    def __init__(self, *, content="", usage=None):
        self.content = content
        self.usage_metadata = usage


class _FakeAgent:
    """astream_events 最小 fake：按序吐预设事件流。"""

    def __init__(self, events):
        self._events = events

    async def astream_events(self, input_value, version=None, config=None):
        for e in self._events:
            yield e


async def _collect(agent, **kwargs):
    from app.ai.orchestrator import _astream_agent_events
    out = []
    async for item in _astream_agent_events(agent, {"messages": []},
                                            thread_id=None, **kwargs):
        out.append(item)
    return out


def test_event_loop_budget_caps_and_flags():
    """超预算：yield 收尾提示、停止消费后续事件、sink 打标。"""
    import asyncio

    from app.services.agent_budget_service import DEFAULT_TURN_TOKEN_BUDGET

    big_usage = {"input_tokens": DEFAULT_TURN_TOKEN_BUDGET, "output_tokens": 10}
    events = [
        {"event": "on_chat_model_stream",
         "data": {"chunk": _FakeChunk(content="开头", usage=dict(big_usage))}},
        {"event": "on_chat_model_stream",
         "data": {"chunk": _FakeChunk(content="本句不应出现", usage={"input_tokens": 1, "output_tokens": 1})}},
    ]
    sink = {}
    out = asyncio.run(_collect(_FakeAgent(events), usage_sink=sink,
                               timeout_notice="[timeout]", token_budget=50))
    texts = [p for k, p in out if k == "token"]
    assert any("token 预算上限" in t for t in texts)
    assert not any("不应出现" in t for t in texts)  # 后续事件已被截断
    assert sink["_budget_capped"] is True
    assert sink["turn_total"] >= big_usage["input_tokens"]


def test_event_loop_no_budget_keeps_streaming():
    """预算关闭（None）：不熔断，事件全部透传。"""
    import asyncio

    events = [
        {"event": "on_chat_model_stream",
         "data": {"chunk": _FakeChunk(content="a", usage={"input_tokens": 10**9, "output_tokens": 1})}},
        {"event": "on_chat_model_stream",
         "data": {"chunk": _FakeChunk(content="b", usage={"input_tokens": 10**9, "output_tokens": 1})}},
    ]
    sink = {}
    out = asyncio.run(_collect(_FakeAgent(events), usage_sink=sink,
                               timeout_notice="[timeout]", token_budget=None))
    assert "".join(p for k, p in out if k == "token") == "ab"
    assert "_budget_capped" not in sink


def test_event_loop_captures_cached_tokens():
    """A-3 链路贯通：事件循环把缓存命中写进 sink（orchestrator 侧复用 llm_client 提取）。"""
    import asyncio

    events = [{"event": "on_chat_model_stream",
               "data": {"chunk": _FakeChunk(content="x", usage={
                   "input_tokens": 300, "output_tokens": 5,
                   "prompt_cache_hit_tokens": 250})}}]
    sink = {}
    asyncio.run(_collect(_FakeAgent(events), usage_sink=sink,
                         timeout_notice="[t]", token_budget=None))
    assert sink["cached"] == 250
