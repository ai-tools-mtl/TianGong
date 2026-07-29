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
