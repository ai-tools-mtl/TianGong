"""[S2-2] 意图识别（规则层）—— spec 2026-07-29-prompt-content-design §4 S2-2。

让模型理解用户：用户输入同一句话，意图不同行为应不同（代写 / 答疑 / 改写 / 引导）。
此前用户输入直接塞进 messages，模型不区分意图——可能该代写时不停追问，或该答疑时甩一整段。

决策 D1：规则层先上（零成本、零延迟），LLM 兜底默认关。
- 命中规则即返回意图，未命中返回 "none"（走默认行为，不强制分类）。
- 关键词表设计原则：选「强信号」词（如「帮我写」「什么是」「重写」），避免误命中。
- 意图值用于 build_system_prompt 注入行为指令，返回字符串而非 None 便于直接做 dict 查询。

未来扩展：LLM 兜底层（规则未命中时调小模型分类），见 spec D1，独立开关，不在此实现。
"""

# 意图 → 关键词（强信号词）。顺序即优先级：guide > edit > draft > info。
# guide 排最前：「引导我写一下」含「写一下」（draft 词），但用户明显想要引导而非代写，
#   故 guide 的强信号词「引导我」「教我」必须先于 draft 判定。
# edit 排 draft 前：「重写这段写一下」更可能想改这段，而非重新代写。
# info 排最后：问句词（什么是/为什么）泛化性强，放最后避免误判。
_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("guide", ["怎么写", "如何写", "不知道怎么", "引导我", "不会写", "教我", "该怎么"]),
    ("edit", ["重写", "改一下", "修改", "改写", "调整", "润色", "优化这段"]),
    ("draft", ["帮我写", "帮我起草", "起草", "生成", "写一段", "写一下", "代写", "撰写"]),
    ("info", ["什么是", "什么是独立", "为什么", "区别", "指的是", "解释一下", "啥是", "啥意思"]),
]


def classify_intent(user_input: str) -> str:
    """规则层意图识别。返回 draft/edit/info/guide/none。

    命中第一个匹配的意图即返回（按 _INTENT_KEYWORDS 顺序的优先级）。
    空输入或无匹配返回 "none"（调用方据此决定是否走默认行为）。

    Args:
        user_input: 用户当前输入（chat 场景的消息文本）。

    Returns:
        意图字符串。设计为字符串而非 None：
        - 便于直接做 dict 查询（INTENT_HINTS[intent]）
        - "none" 是显式的「未识别」语义，比 None 更适合做 fallback key
        - 前端/日志展示更清晰
    """
    if not user_input or not user_input.strip():
        return "none"
    text = user_input.strip()
    for intent, keywords in _INTENT_KEYWORDS:
        if any(kw in text for kw in keywords):
            return intent
    return "none"
