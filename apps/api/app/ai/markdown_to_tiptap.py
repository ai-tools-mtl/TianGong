"""Markdown → Tiptap JSON 转换器（设计 5.6）。

AI 输出 Markdown，后端转成 Tiptap doc JSON 入库。
支持：段落、标题(##/###)、有序/无序列表、加粗。
"""

import re
from typing import Any


def markdown_to_tiptap(md: str) -> dict[str, Any]:
    """把 Markdown 文本转成 Tiptap doc JSON。"""
    lines = md.strip().split("\n")
    content: list[dict] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        m = re.match(r"^(#{2,3})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))
            content.append({
                "type": "heading", "attrs": {"level": level},
                "content": _parse_inline(m.group(2)),
            })
            continue

        m = re.match(r"^[-*]\s+(.+)$", stripped)
        if m:
            content.append({
                "type": "bulletList",
                "content": [{
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": _parse_inline(m.group(1))}],
                }],
            })
            continue

        m = re.match(r"^\d+\.\s+(.+)$", stripped)
        if m:
            content.append({
                "type": "orderedList",
                "content": [{
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": _parse_inline(m.group(1))}],
                }],
            })
            continue

        content.append({"type": "paragraph", "content": _parse_inline(stripped)})

    return {"type": "doc", "content": content or [{"type": "paragraph"}]}


def _parse_inline(text: str) -> list[dict]:
    """解析行内格式（加粗 **text**）。"""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    nodes: list[dict] = []
    for i, part in enumerate(parts):
        if not part:
            continue
        if i % 2 == 1:
            nodes.append({"type": "text", "text": part, "marks": [{"type": "bold"}]})
        else:
            nodes.append({"type": "text", "text": part})
    return nodes or [{"type": "text", "text": text}]
