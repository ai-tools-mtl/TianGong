"""对话上下文压缩：双闸触发 + 首尾保留 + 中段摘要（运行时压缩，不污染原始 Message 表）。

设计见 docs/superpowers/specs/2026-07-30-context-compression-design.md。

职责：输入 (history, current_input, llm_config, budget) → 输出 (compressed_messages, snapshot)。
在「装配 messages 喂给 LLM 前」调用，取数层（_get_section_with_history）不动。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetConfig:
    """压缩预算配置（可调常量，集中管理）。"""
    # 双闸阈值（任一命中即触发）
    max_messages: int = 30          # 条数快闸
    token_budget: int = 24000       # token 慢闸（GLM 128k 窗口的 ~18%）
    # 保留策略
    keep_head: int = 1              # 保留首条 user（原始需求）
    keep_tail: int = 10             # 保留最近 10 条（连续性）


DEFAULT_BUDGET = BudgetConfig()


@dataclass
class Snapshot:
    """单次压缩的观测记录（不落库于 Message 表；序列化进 LLMCallLog.context_meta）。"""
    triggered: bool
    reason: str            # "uncompressed" / "messages>30" / "tokens>24000" / "summarize_failed"
    original_count: int
    compressed_count: int
    middle_count: int
    est_tokens_before: int
    est_tokens_after: int
    fallback: bool = False
