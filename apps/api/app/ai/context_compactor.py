"""对话上下文压缩：双闸触发 + 首尾保留 + 中段摘要（运行时压缩，不污染原始 Message 表）。

设计见 docs/superpowers/specs/2026-07-30-context-compression-design.md。

职责：输入 (history, current_input, llm_config, budget) → 输出 (compressed_messages, snapshot)。
在「装配 messages 喂给 LLM 前」调用，取数层（_get_section_with_history）不动。
"""
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.llm_client import get_llm
from app.services.llm_config_service import ResolvedChatConfig


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


def estimate_tokens(text: str) -> int:
    """轻量 token 近似估算（无 tiktoken）。

    GLM 用不了 tiktoken 的 cl100k 编码（本身也是近似），故用混合字符加权：
    - CJK 字符按 ~1.5 字/token（即每字符 ~0.67 token）
    - 其他字符（英文/标点/数字）按 ~4 字符/token（即每字符 ~0.25 token）

    精度 ±25%，配合条数闸兜底（should_compress），不会明显误判触发。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    # 向上取整，避免短文本估为 0
    return max(1, round(cjk / 1.5 + other / 4))


def _is_cjk(ch: str) -> bool:
    """判断字符是否为 CJK 统一表意文字（中日韩）。"""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF    # CJK 统一表意文字
        or 0x3400 <= code <= 0x4DBF  # CJK 扩展 A
        or 0x3000 <= code <= 0x303F  # CJK 标点
    )


def estimate_tokens_messages(messages) -> int:
    """对消息列表（Message 对象或 dict）累加 content 的 token 估算。"""
    total = 0
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        total += estimate_tokens(content or "")
    return total


def should_compress(
    history_count: int, est_tokens: int, budget: BudgetConfig = DEFAULT_BUDGET
) -> bool:
    """双闸触发判定（OR）：条数 > max_messages 或 token > token_budget 即触发。

    先挡「连首尾都凑不齐」的情况（无中段可压）。
    """
    if history_count <= budget.keep_head + budget.keep_tail:
        return False
    if history_count > budget.max_messages:
        return True
    if est_tokens > budget.token_budget:
        return True
    return False


class SummarizeRuntimeError(Exception):
    """摘要运行时失败（超时/限流/网络/返回空）。由 compress_history 捕获后降级。"""


SUMMARIZE_PROMPT = """你是对话历史压缩器。把多轮对话压缩成一段高密度摘要，供 AI 撰写助手延续上下文。

必须保留（缺一不可）：
1. 用户确定的技术问题、技术方案、关键术语（原词不换同义词）
2. 已达成的结论、用户明确表达的偏好或约束
3. 待解决/未确定的开放问题

可以省略：寒暄、重复内容、已被后续对话推翻的旧说法。

输出要求：纯文本摘要（不要 Markdown 标题），300 字以内。只输出摘要，不要解释。"""


def _format_for_summary(messages: list) -> str:
    """把消息列表格式化为摘要输入文本。"""
    lines = []
    for m in messages:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "user")
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}：{content}")
    return "\n".join(lines)


async def summarize(messages: list, llm_config: ResolvedChatConfig | None) -> str:
    """用用户自己的 chat 配置摘要中段消息。

    分类降级协议（spec §5.2）：
    - 配置类错误（无 config / model 空）→ 抛 ValueError（该报则报）。
    - 运行时错误（超时/限流/网络/返回空）→ 抛 SummarizeRuntimeError（由 compress_history 降级）。
    """
    if llm_config is None or not getattr(llm_config, "model", None):
        raise ValueError("LLM 配置缺少 model，无法生成摘要")
    try:
        llm = get_llm(llm_config, streaming=False)
        resp = await llm.ainvoke([
            SystemMessage(content=SUMMARIZE_PROMPT),
            HumanMessage(content=_format_for_summary(messages)),
        ])
        text = (resp.content or "").strip()
        if not text:
            raise SummarizeRuntimeError("摘要返回空")
        return text
    except SummarizeRuntimeError:
        raise
    except ValueError:
        raise
    except Exception as e:
        raise SummarizeRuntimeError(str(e)) from e
