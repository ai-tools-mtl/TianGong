from app.ai.section_prompts import SECTION_PROMPTS, get_section_prompt


def test_all_standard_keys_exist():
    expected = {"name", "field", "background", "problem", "solution", "effect", "drawings", "embodiment", "custom"}
    assert expected.issubset(SECTION_PROMPTS.keys())


def test_get_section_prompt_known_key():
    sp = get_section_prompt("solution")
    assert sp.key == "solution"
    assert len(sp.guide_questions) > 0


def test_get_section_prompt_unknown_falls_back_to_custom():
    sp = get_section_prompt("nonexistent")
    assert sp.key == "custom"


# ===== S1：专利领域约束强化（spec 2026-07-29-prompt-content-design §4 S1-2）=====

def test_solution_prompt_links_to_problem():
    """solution 章节必须显式呼应「技术问题」章节（专利法核心：方案要对准问题）。"""
    sp = get_section_prompt("solution")
    blob = " ".join(sp.guide_questions) + " " + sp.completion_criteria
    assert "技术问题" in blob


def test_effect_prompt_requires_quantifiable():
    """effect 章节应引导可量化效果（避免空洞的「效果好」）。"""
    sp = get_section_prompt("effect")
    blob = " ".join(sp.guide_questions) + " " + sp.completion_criteria
    assert "量化" in blob or "可量化" in blob or "数据" in blob


def test_problem_prompt_distinguishes_technical_problem():
    """problem 章节应强调是「技术问题」而非商业/市场问题（专利法核心区分）。"""
    sp = get_section_prompt("problem")
    blob = sp.goal + " " + " ".join(sp.guide_questions) + " " + sp.completion_criteria
    assert "技术问题" in blob


# ===== S4-1：few-shot 范例（spec 2026-07-29-prompt-content-design §4 S4-1）=====
# 范例来源：4 份已授权真实交底书（脱敏抽象，保留结构与句式）。
# 给模型看「好样子」，让它照着写，而非端到端凭空生成。

def test_section_prompt_has_few_shot_example_field():
    """[S4-1] SectionPrompt dataclass 有 few_shot_example 字段。"""
    sp = get_section_prompt("background")
    assert hasattr(sp, "few_shot_example")


def test_core_sections_have_few_shot_examples():
    """[S4-1] 核心章节（background/problem/solution/effect）范例非空。"""
    for key in ("background", "problem", "solution", "effect"):
        sp = get_section_prompt(key)
        assert sp.few_shot_example, f"{key} 章节缺少 few_shot_example"


def test_few_shot_examples_are_anonymized():
    """[S4-1] 范例应通用化（不含真实专利的具体专有名词，体现写法而非具体技术）。

    范例用「某发明/某系统」等通用指代，避免把具体授权专利的技术细节当范例。
    """
    for key in ("background", "solution", "effect"):
        sp = get_section_prompt(key)
        # 范例应含通用化指代词（脱敏标志），而非堆砌具体技术名词
        assert "某" in sp.few_shot_example or "例如" in sp.few_shot_example \
            or "其特征" in sp.few_shot_example or "本发明" in sp.few_shot_example
