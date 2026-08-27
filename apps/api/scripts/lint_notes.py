"""Agent Notes 决策记录 lint（借鉴机制批次 G，源自 deepseek-harness 的裁剪版）。

约定：docs/notes/{proposed,implemented,rejected}/YYYY-MM-DD-主题.md
四段骨架：Problem / Decision / Alternatives considered（强制至少一条）/ Consequences。
Status 行与所在目录互验；implemented = 已发布事实（现在时），rejected 保留理由。

用法：
    uv run python -m scripts.lint_notes            # 校验，违规 exit 1
CI 在 backend job 里跑一遍，防骨架腐化（引导而非强制，成本极低）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 路径：SCRIPT_DIR=<repo>/apps/api/scripts；其 parents=[api, apps, repo]
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
NOTES_DIR = REPO_ROOT / "docs" / "notes"

STATUSES = ("proposed", "implemented", "rejected")
FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$")
REQUIRED_SECTIONS = ("## Problem", "## Decision", "## Alternatives considered", "## Consequences")
STATUS_LINE_RE = re.compile(r"^Status:\s*(proposed|implemented|rejected)\s*$", re.M)


def check_note(path: Path, *, rel_base: Path = REPO_ROOT) -> list[str]:
    """单篇 note 的全部检查，返回违规描述列表。rel_base 供测试注入临时根。"""
    errors: list[str] = []
    rel = path.relative_to(rel_base).as_posix()

    folder = path.parent.name
    if folder not in STATUSES:
        errors.append(f"{rel}: 目录 {folder} 不在 {STATUSES} 内")
    if not FILENAME_RE.match(path.name):
        errors.append(f"{rel}: 文件名须为 YYYY-MM-DD-小写连字符主题.md")

    text = path.read_text(encoding="utf-8")

    m = STATUS_LINE_RE.search(text)
    if not m:
        errors.append(f"{rel}: 缺 Status 行（格式：Status: proposed|implemented|rejected）")
    elif folder in STATUSES and m.group(1) != folder:
        errors.append(f"{rel}: Status={m.group(1)} 与所在目录 {folder} 不一致")

    for section in REQUIRED_SECTIONS:
        if section not in text:
            errors.append(f"{rel}: 缺必填段落「{section}」")

    # Alternatives considered 强制有实质内容（至少一条非空正文行）
    # [ \t]*\n 而非 \s*\n：防止贪婪空白把后续段标题吃进捕获组
    alt = re.search(r"## Alternatives considered[ \t]*\n(.*?)(?=\n## |\Z)", text, re.S)
    if alt and not any(ln.strip() for ln in alt.group(1).splitlines()):
        errors.append(f"{rel}: Alternatives considered 段为空——决策记录的价值就在「放弃了什么」")

    return errors


def lint_notes_dir(root: Path = NOTES_DIR, *, rel_base: Path = REPO_ROOT) -> list[str]:
    """扫描全部 note，返回违规列表（目录不存在 = 还没写过，不算违规）。"""
    if not root.exists():
        return []
    errors: list[str] = []
    for path in sorted(root.rglob("*.md")):
        errors.extend(check_note(path, rel_base=rel_base))
    return errors


def main() -> int:
    errors = lint_notes_dir()
    if errors:
        print(f"Agent Notes lint：{len(errors)} 处违规")
        for e in errors:
            print(f"  - {e}")
        return 1
    count = sum(1 for _ in NOTES_DIR.rglob("*.md")) if NOTES_DIR.exists() else 0
    print(f"Agent Notes lint：通过（{count} 篇）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
