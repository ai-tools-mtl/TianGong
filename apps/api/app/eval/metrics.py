"""[P2] eval 评估指标定义（spec 2026-07-29-prompt-content-design 附录 A.3 / P2）。

无参考评估的三个指标，对应 S1–S5 的改进点——让 eval 能量化提示词改进的效果：
- structure（结构完整性）：输出是否覆盖 completion_criteria 要求的维度 → 验证 S1
- consistency（前文一致性）：是否沿用前文术语、呼应前文章节 → 验证 S3-1
- conformity（章节规范度）：是否符合专利交底书的表述范式 → 验证 S4-1

每个指标含一个 judge_prompt：喂给 LLM-as-judge，让它按 0-100 打分 + 给理由。
无参考评估 = 不对比「期望输出」，只评生成输出本身的质量（轻量、不需 golden set）。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    """单个评估指标。"""
    key: str
    description: str
    judge_prompt: str


METRICS: dict[str, Metric] = {
    "structure": Metric(
        key="structure",
        description="结构完整性：输出是否覆盖该章节应具备的维度（如技术方案的 结构/流程/关键要素）",
        judge_prompt=(
            "你是专利交底书质量评审专家。请评估以下「章节内容」的结构完整性。\n\n"
            "评分标准：\n"
            "- 90-100：完整覆盖该章节应具备的所有维度（如技术方案覆盖整体架构、关键要素、工作原理）\n"
            "- 60-89：覆盖主要维度但有遗漏\n"
            "- 0-59：严重缺失关键维度，结构不完整\n\n"
            "章节内容：\n{output}\n\n"
            "请输出 JSON：{{\"score\": 0到100的整数, \"reason\": \"评分理由（指出覆盖/遗漏了哪些维度）\"}}"
        ),
    ),
    "consistency": Metric(
        key="consistency",
        description="前文一致性：是否沿用前文术语、呼应前文章节（如方案呼应技术问题）",
        judge_prompt=(
            "你是专利交底书质量评审专家。请评估以下「章节内容」与前文的一致性。\n\n"
            "评分标准：\n"
            "- 90-100：完全沿用前文术语，且显式呼应前文章节（如方案明确对准技术问题）\n"
            "- 60-89：基本一致，但术语有少量出入或呼应不够明确\n"
            "- 0-59：术语混乱、与前文矛盾、或完全未呼应前文\n\n"
            "前文上下文：\n{context}\n\n"
            "章节内容：\n{output}\n\n"
            "请输出 JSON：{{\"score\": 0到100的整数, \"reason\": \"评分理由（指出一致/不一致之处）\"}}"
        ),
    ),
    "conformity": Metric(
        key="conformity",
        description="章节规范度：是否符合专利交底书的表述范式（专业术语、客观陈述、无夸大）",
        judge_prompt=(
            "你是专利交底书质量评审专家。请评估以下「章节内容」是否符合专利交底书的表述规范。\n\n"
            "评分标准：\n"
            "- 90-100：完全符合专利表述范式（专业客观、术语准确、无夸大、无营销话术）\n"
            "- 60-89：基本规范，但偶有口语化或不够严谨\n"
            "- 0-59：严重偏离专利表述范式（营销话术、主观夸大、口语化严重）\n\n"
            "章节内容：\n{output}\n\n"
            "请输出 JSON：{{\"score\": 0到100的整数, \"reason\": \"评分理由（指出规范/不规范之处）\"}}"
        ),
    ),
}


def get_metric(key: str) -> Metric:
    """获取指标。未知 key 抛 ValueError。"""
    if key not in METRICS:
        raise ValueError(f"未知评估指标: {key}（可选: {', '.join(METRICS.keys())}）")
    return METRICS[key]
