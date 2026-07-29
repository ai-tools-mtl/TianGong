"""[S4-2] generate 草稿指令构造测试（spec 2026-07-29-prompt-content-design §4 S4-2）。

验证 build_generate_instruction 产出含 CoT（分步思考）引导的指令，
让模型在生成草稿前理清前文呼应、维度覆盖、一致性，而非端到端直接吐内容。
"""
from app.ai.orchestrator import build_generate_instruction
from app.models import Section


def _make_section(key="solution", title="技术方案"):
    return Section(
        template_section_id="ts", order=1, key=key, title=title,
        project_id="00000000-0000-0000-0000-000000000000",
    )


def test_build_generate_instruction_includes_section_title():
    """指令含当前章节标题。"""
    s = _make_section("solution", "技术方案")
    instr = build_generate_instruction(s)
    assert "技术方案" in instr


def test_build_generate_instruction_includes_output_format():
    """指令含 output_format（达标判定的格式要求）。"""
    s = _make_section("solution", "技术方案")
    instr = build_generate_instruction(s)
    # solution 的 output_format 含「整体架构」
    assert "整体架构" in instr


def test_build_generate_instruction_includes_completion_criteria():
    """[S4-2] 指令含 completion_criteria（让模型知道什么算达标）。"""
    s = _make_section("solution", "技术方案")
    instr = build_generate_instruction(s)
    # solution 的 completion_criteria 含「关键要素」
    assert "关键要素" in instr


def test_build_generate_instruction_has_cot_steps():
    """[S4-2] 指令含 CoT 分步思考引导（回顾/梳理/检查/输出）。"""
    s = _make_section("solution", "技术方案")
    instr = build_generate_instruction(s)
    # CoT 的核心动作词：回顾对话/梳理维度/检查一致性/输出
    assert "回顾" in instr or "梳理" in instr  # 至少有思考步骤
    assert "检查" in instr or "一致性" in instr  # 含一致性检查步骤


def test_build_generate_instruction_output_only_final_draft():
    """[S4-2] 指令明确要求只输出最终草稿（不暴露思考过程给用户）。"""
    s = _make_section("solution", "技术方案")
    instr = build_generate_instruction(s)
    # 明确「只输出最终」/「不输出思考」之一，避免把 CoT 过程展示给用户
    assert "只输出" in instr or "最终草稿" in instr or "不输出思考" in instr


def test_build_generate_instruction_requests_markdown():
    """指令要求 Markdown 格式输出。"""
    s = _make_section("solution", "技术方案")
    instr = build_generate_instruction(s)
    assert "Markdown" in instr or "markdown" in instr.lower()
