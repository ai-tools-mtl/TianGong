"""上下文压缩模块测试（纯逻辑，mock LLM，SQLite 内存库，遵循 GOTCHAS G2）。"""
from app.ai.context_compactor import (
    BudgetConfig,
    Snapshot,
    estimate_tokens,
    should_compress,
)


def test_budget_config_defaults():
    b = BudgetConfig()
    assert b.max_messages == 30
    assert b.token_budget == 24000
    assert b.keep_head == 1
    assert b.keep_tail == 10


def test_budget_config_is_frozen():
    import dataclasses
    b = BudgetConfig()
    assert dataclasses.is_dataclass(b)
    try:
        b.max_messages = 99  # frozen=True 应拒绝
        assert False, "应抛 FrozenInstanceError"
    except dataclasses.FrozenInstanceError:
        pass


def test_snapshot_fields():
    s = Snapshot(
        triggered=True, reason="messages>30",
        original_count=35, compressed_count=12,
        middle_count=24, est_tokens_before=1000, est_tokens_after=400,
    )
    assert s.triggered is True
    assert s.fallback is False  # 默认值


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_chinese_weighted_higher_than_english():
    """中文按 ~1.5 字/token（权重高），英文/标点按 ~4 字符/token（权重低）。
    同字符数的中文估算 token 应高于英文。"""
    chinese = "技术方案需要解决的核心问题"  # 12 个 CJK 字符
    english = "abcdefghijkl"  # 12 个 ASCII 字符
    assert estimate_tokens(chinese) > estimate_tokens(english)


def test_estimate_tokens_grows_with_length():
    assert estimate_tokens("短") < estimate_tokens("短" * 100)


def test_estimate_tokens_mixed():
    # 混合文本不报错，返回正整数
    t = estimate_tokens("技术方案 technical solution 123")
    assert t > 0


def test_should_compress_false_when_history_too_short():
    # 11 条，keep_head+keep_tail=11，无中段可压
    assert should_compress(11, 100) is False


def test_should_compress_false_under_both_thresholds():
    # 12 条（>11，有中段），token 不超，条数不超 → 不触发
    assert should_compress(12, 1000) is False


def test_should_compress_true_by_message_count():
    # 31 条 > max_messages=30 → 条数闸触发
    assert should_compress(31, 1000) is True


def test_should_compress_true_by_tokens():
    # 12 条，token > budget=24000 → token 闸触发
    assert should_compress(12, 30000) is True


def test_should_compress_respects_custom_budget():
    custom = BudgetConfig(max_messages=5, token_budget=100, keep_head=1, keep_tail=1)
    assert should_compress(6, 50, custom) is True   # 条数闸
    assert should_compress(3, 200, custom) is True  # token 闸
    assert should_compress(2, 50, custom) is False  # 太短


# ---------- summarize（摘要生成 + 分类降级，spec §5.2）----------
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.ai.context_compactor import summarize, SummarizeRuntimeError


def _make_messages(contents: list[str], role: str = "user") -> list:
    """构造简单 Message 替身对象（duck-typed，有 role/content）。"""
    objs = []
    for c in contents:
        m = MagicMock()
        m.role = role
        m.content = c
        objs.append(m)
    return objs


@pytest.mark.asyncio
async def test_summarize_success():
    """mock get_llm 返回摘要文本 → summarize 返回该文本。"""
    msgs = _make_messages(["讨论了技术方案A", "确定了核心模块"])
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content="摘要：技术方案A含核心模块"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)
        result = await summarize(msgs, _fake_chat_config())
    assert "技术方案A" in result


@pytest.mark.asyncio
async def test_summarize_empty_response_raises_runtime():
    """摘要返回空 → SummarizeRuntimeError（视为运行时失败，由上层降级）。"""
    msgs = _make_messages(["内容"])
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content="   "))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)
        with pytest.raises(SummarizeRuntimeError):
            await summarize(msgs, _fake_chat_config())


@pytest.mark.asyncio
async def test_summarize_llm_exception_raises_runtime():
    """LLM 抛超时 → 转 SummarizeRuntimeError（不抛原始异常，统一降级协议）。"""
    msgs = _make_messages(["内容"])
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=TimeoutError("upstream timeout"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)
        with pytest.raises(SummarizeRuntimeError):
            await summarize(msgs, _fake_chat_config())


@pytest.mark.asyncio
async def test_summarize_config_error_raises_value_error():
    """llm_config.model 为空 → ValueError（配置类，不降级，向上抛）。"""
    msgs = _make_messages(["内容"])
    bad_config = MagicMock()
    bad_config.model = ""
    with pytest.raises(ValueError):
        await summarize(msgs, bad_config)


@pytest.mark.asyncio
async def test_summarize_none_config_raises_value_error():
    """llm_config=None → ValueError。"""
    msgs = _make_messages(["内容"])
    with pytest.raises(ValueError):
        await summarize(msgs, None)


def _fake_chat_config():
    """构造一个最小可用的 ResolvedChatConfig 替身。"""
    cfg = MagicMock()
    cfg.model = "glm-4"
    cfg.base_url = "http://localhost"
    cfg.api_key = "sk-test"
    return cfg
