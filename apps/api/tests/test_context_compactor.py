"""上下文压缩模块测试（纯逻辑，mock LLM，SQLite 内存库，遵循 GOTCHAS G2）。"""
from app.ai.context_compactor import BudgetConfig, Snapshot


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
