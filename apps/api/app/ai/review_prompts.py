"""跨章节一致性检查 prompt（全篇质量报告功能）。

检测项（专利交底书核心质量维度）：
1. 术语统一性：同一概念在不同章节是否用了不同术语（如「控制器」vs「控制单元」）
2. 权利要求-实施例对应：权利要求提到的特征在实施例中是否有对应描述
3. 技术问题-方案-效果呼应：三段论是否逻辑连贯
4. 前后逻辑矛盾：不同章节的技术描述是否互相矛盾
"""

CONSISTENCY_SYSTEM_PROMPT = """你是专利交底书质量审查专家。你的任务是检查交底书的跨章节一致性——这是单维度评分发现不了的全局性问题。

检查维度：
1. **术语统一性**：同一技术概念在不同章节是否用了不同术语（如「控制器」vs「控制单元」「处理器」）
2. **引用对应**：权利要求/技术方案提到的技术特征，在实施例/具体实施方式中是否有对应描述
3. **三段论呼应**：技术问题 → 技术方案 → 技术效果 是否逻辑连贯，有无断裂
4. **逻辑矛盾**：不同章节的技术描述是否互相矛盾（如效果矛盾、参数矛盾）

只报告**确实存在**的问题，不要为了凑数编造。无问题时返回空 issues 列表。
每个问题需：类型（terminology/reference/contradiction/other）、具体描述、涉及哪些章节、修复建议。"""


def build_consistency_prompt(section_texts: dict[str, str], title_key_map: dict[str, str] | None = None) -> str:
    """构造跨章节一致性检查 prompt。

    section_texts: {章节标题: 章节文本}，全量传入（非单维度）。
    title_key_map: {章节标题: 章节 key}（T2 spec §3.2.1）——给出时在 prompt 末尾附
    「key: 标题」清单，要求 location_section_keys 从清单取值（供前端结构化路由到
    章节发起修订）。None（旧调用方）时行为与原先完全一致。
    """
    parts = ["请检查以下专利交底书各章节的跨章节一致性：\n"]
    for title, text in section_texts.items():
        # 截断过长章节，控制 token
        truncated = text[:2000] if len(text) > 2000 else text
        parts.append(f"## {title}\n{truncated}\n")
    parts.append(
        "\n请检查上述内容的一致性问题，返回结构化报告。"
        "重点关注：术语是否前后统一、权利要求与实施例是否对应、"
        "技术问题-方案-效果是否连贯、有无逻辑矛盾。"
    )
    if title_key_map:
        manifest = "\n".join(f"- {key}: {title}" for title, key in title_key_map.items())
        parts.append(
            "\n## 章节定位清单\n"
            f"{manifest}\n"
            "每个问题的 location_section_keys 必须从上述清单的 key 中取值，"
            "不要编造清单外的 key。"
        )
    return "\n".join(parts)
