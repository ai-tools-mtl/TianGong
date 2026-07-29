"""[S2-2] 意图识别规则层测试（spec 2026-07-29-prompt-content-design §4 S2-2）。

纯规则层（零 LLM 调用）：按关键词把用户输入分为 draft/info/edit/guide/None。
LLM 兜底为独立决策（D1，默认关），不在本测试范围。
"""
from app.ai.intent import classify_intent


# ===== draft 意图：用户想让 AI 代写 =====

def test_classify_intent_draft_help_me_write():
    assert classify_intent("帮我写一下技术方案") == "draft"


def test_classify_intent_draft_generate():
    assert classify_intent("生成背景技术这段") == "draft"


def test_classify_intent_draft_draft():
    assert classify_intent("起草一个实施例") == "draft"


# ===== info 意图：用户在问问题 =====

def test_classify_intent_info_what_is():
    assert classify_intent("什么是独立权利要求？") == "info"


def test_classify_intent_info_why():
    assert classify_intent("为什么要写背景技术？") == "info"


def test_classify_intent_info_difference():
    assert classify_intent("实施例和技术方案有什么区别？") == "info"


# ===== edit 意图：用户想改某段 =====

def test_classify_intent_edit_rewrite():
    assert classify_intent("重写这段，更简洁一点") == "edit"


def test_classify_intent_edit_modify():
    assert classify_intent("把第二段改一下") == "edit"


def test_classify_intent_edit_adjust():
    assert classify_intent("调整一下措辞") == "edit"


# ===== guide 意图：用户在寻求引导 =====

def test_classify_intent_guide_help_me():
    assert classify_intent("我不知道怎么写技术效果") == "guide"


def test_classify_intent_guide_guide():
    assert classify_intent("引导我写一下") == "guide"


def test_classify_intent_guide_confused():
    assert classify_intent("这块该怎么写？") == "guide"


# ===== None：无法识别（走默认行为）=====

def test_classify_intent_none_ambiguous():
    """不含任何意图关键词的输入返回 None。"""
    assert classify_intent("这个方案用了凸轮机构") == "none"


def test_classify_intent_none_empty():
    assert classify_intent("") == "none"


def test_classify_intent_none_whitespace():
    assert classify_intent("   ") == "none"
