"""Agent Notes lint 测试（批次 G）：路径模式/Status 互验/必填段落/Alternatives 非空。"""
from pathlib import Path

from scripts.lint_notes import lint_notes_dir

VALID = """# 标题

Status: proposed
Date: 2026-08-28

## Problem

有个问题。

## Decision

这么解决。

## Alternatives considered

- 方案甲：因为 X 否决。

## Consequences

影响如下。
"""


def _mk(root: Path, folder: str, name: str, text: str) -> None:
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def test_valid_note_passes(tmp_path):
    _mk(tmp_path, "proposed", "2026-08-28-some-decision.md", VALID)
    assert lint_notes_dir(tmp_path, rel_base=tmp_path) == []


def test_status_folder_mismatch_detected(tmp_path):
    _mk(tmp_path, "proposed", "2026-08-28-bad.md",
        VALID.replace("Status: proposed", "Status: implemented"))
    errors = lint_notes_dir(tmp_path, rel_base=tmp_path)
    assert any("不一致" in e for e in errors)


def test_missing_sections_and_empty_alternatives(tmp_path):
    _mk(tmp_path, "implemented", "2026-08-28-worse.md",
        "# t\n\nStatus: implemented\n\n## Problem\n\np\n\n## Consequences\n\nc\n")
    errors = lint_notes_dir(tmp_path, rel_base=tmp_path)
    assert any("Alternatives considered" in e for e in errors)
    # 空的 Alternatives（只有标题）也要被抓
    _mk(tmp_path, "implemented", "2026-08-28-empty-alt.md",
        VALID.replace("- 方案甲：因为 X 否决。", ""))
    errors2 = lint_notes_dir(tmp_path, rel_base=tmp_path)
    assert any("为空" in e for e in errors2)


def test_bad_filename_and_folder(tmp_path):
    _mk(tmp_path, "wrongplace", "随便.md", VALID)
    errors = lint_notes_dir(tmp_path, rel_base=tmp_path)
    assert any("YYYY-MM-DD" in e for e in errors)
    assert any("wrongplace" in e for e in errors)


def test_missing_root_is_clean(tmp_path):
    assert lint_notes_dir(tmp_path / "nonexistent", rel_base=tmp_path) == []
