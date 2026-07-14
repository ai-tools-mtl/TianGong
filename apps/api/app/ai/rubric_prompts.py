"""Rubric 驱动的评分 Prompt（设计 6.4）。"""

SCORE_SYSTEM_PROMPT = """你是专利交底书审查专家。你的任务是根据给定的评分标准，对交底书进行客观、一致的评分。

要求：
1. 严格按评分标准打分，不要主观臆断
2. 给出具体的评分依据（引用交底书内容）
3. 提供可操作的改进建议
4. 输出必须是合法 JSON"""


def build_score_prompt(criterion: dict, section_texts: dict) -> str:
    """为单个维度构造评分 prompt。"""
    guide_text = "\n".join(
        f"  {range_str}：{desc}" for range_str, desc in criterion.get("scoring_guide", {}).items()
    )
    content_text = "\n\n".join(
        f"【{title}】\n{text}" for title, text in section_texts.items() if text.strip()
    )
    return f"""请评估以下专利交底书在「{criterion['name']}」维度的得分。

评分标准：
{guide_text}

交底书内容：
{content_text[:3000]}

请严格按上述标准打分（0-100 整数），并给出具体证据。

输出 JSON 格式：
{{"score": 数字, "evidence": "评分依据", "suggestion": "改进建议"}}"""
