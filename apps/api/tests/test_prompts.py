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
