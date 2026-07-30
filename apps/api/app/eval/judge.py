"""[P2] LLM-as-judge：给章节输出打分（spec 附录 A.3 / P2）。

judge 用项目已有的 get_llm 调 LLM，按 metrics 里定义的 judge_prompt 评分。
复用 S5 的健壮 JSON 解析思路（括号配平，支持嵌套）。

设计要点：
- judge 是「无参考评估」——只评输出本身，不对比期望输出。
- 失败不抛异常（返回 0 分 + 失败原因），保证 eval 批量跑时不中断。
- _call_judge_llm 是可 mock 的边界（单测 mock 它，不依赖真实 LLM）。
"""
import json
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.llm_client import get_llm
from app.eval.metrics import get_metric
from app.services.llm_config_service import ResolvedChatConfig

JUDGE_SYSTEM_PROMPT = "你是专利交底书质量评审专家。请严格、客观地按评分标准打分，输出必须是合法 JSON。"


@dataclass
class JudgeResult:
    """judge 单次评分结果。"""
    score: int
    reason: str


def judge(
    metric_key: str, output: str, llm_config: ResolvedChatConfig,
    *, context: str | None = None,
) -> JudgeResult:
    """对 output 按 metric_key 指标打分。

    Args:
        metric_key: 指标键（structure/consistency/conformity）。
        output: 待评的章节内容。
        llm_config: LLM 配置（judge 调用用）。
        context: 前文上下文（仅 consistency 指标需要）。

    Returns:
        JudgeResult（score 0-100 + reason）。失败时 score=0、reason 含失败说明。
    """
    # 校验指标存在（未知指标抛 ValueError，这是调用方 bug，不该被吞）
    get_metric(metric_key)
    try:
        score, reason = _call_judge_llm(metric_key, output, llm_config, context=context)
        return JudgeResult(score=max(0, min(100, score)), reason=reason)
    except Exception as e:
        return JudgeResult(score=0, reason=f"评分失败：{e}")


def _call_judge_llm(
    metric_key: str, output: str, llm_config: ResolvedChatConfig,
    *, context: str | None = None,
) -> tuple[int, str]:
    """实际调 LLM 打分（可 mock 边界）。

    返回 (score, reason)。score 由 judge() clamp，这里原样返回。
    """
    metric = get_metric(metric_key)
    prompt = metric.judge_prompt.format(output=output, context=context or "（无前文上下文）")
    llm = get_llm(llm_config)
    resp = llm.invoke([
        SystemMessage(content=JUDGE_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    data = _parse_json(resp.content)
    return int(data.get("score", 0)), str(data.get("reason", ""))


def _parse_json(text: str) -> dict:
    """健壮解析 LLM 输出的 JSON（括号配平，支持嵌套）。复用 S5 思路。"""
    if not isinstance(text, str):
        text = str(text)
    start = text.find("{")
    if start == -1:
        return json.loads(text)
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    return json.loads(text)
