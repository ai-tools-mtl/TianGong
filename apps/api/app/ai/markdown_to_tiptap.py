"""Markdown → Tiptap JSON 转换器（设计 5.6）。

AI 输出 Markdown，后端转成 Tiptap doc JSON 入库。
支持：段落、标题(##/###)、有序/无序列表、加粗、表格。
"""

import re
from typing import Any


def markdown_to_tiptap(md: str) -> dict[str, Any]:
    """把 Markdown 文本转成 Tiptap doc JSON。"""
    md = _normalize_inline_tables(md)
    lines = md.strip().split("\n")
    content: list[dict] = []
    i = 0

    while i < len(lines):
        stripped = lines[i].strip()

        # 表格：连续 |...| 行组成一个表格块
        if _is_table_line(stripped):
            table_lines: list[str] = []
            while i < len(lines) and _is_table_line(lines[i].strip()):
                table_lines.append(lines[i])
                i += 1
            content.append(_parse_table(table_lines))
            continue

        i += 1

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


# ── 表格解析 ──────────────────────────────────────────────

# 分隔行：|----|----| 或 |:---|:---:| 等
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:]+\|[\s\-:|]*$")

# 行内分隔行标志：用于检测单行压缩表格（AI 偶尔会把整张表写在一行）
# 匹配完整分隔行如 |---|---| 或 |:---|:---:|---:|（含至少一个内部 |）
_INLINE_TABLE_SEP_RE = re.compile(r"\|\s*\-{3,}[\s\-:|]*\|")


def _normalize_inline_tables(md: str) -> str:
    """预处理：把单行压缩的 Markdown 表格展开为多行格式。

    AI 有时输出形如：
      | 名称 | 用途 | |---|---| | A | 说明A | | B | 说明B |
    本函数检测行内的 |---| 分隔符，拆分为正规多行表格。
    """
    lines = md.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not _is_table_line(stripped):
            result.append(line)
            continue

        # 整行就是分隔行 → 正常多行表格，不处理
        if _TABLE_SEP_RE.match(stripped):
            result.append(line)
            continue

        sep_m = _INLINE_TABLE_SEP_RE.search(stripped)
        if not sep_m:
            result.append(line)
            continue

        # 分隔符后无内容 → 不是行内压缩表格（可能只是末尾有 |---|）
        sep_end = sep_m.end()
        if not stripped[sep_end:].strip():
            result.append(line)
            continue

        # 找到行内分隔符位置
        sep_m = _INLINE_TABLE_SEP_RE.search(stripped)
        assert sep_m is not None
        sep_text = sep_m.group(0)
        sep_start = sep_m.start()

        header_part = stripped[:sep_start].rstrip()
        body_part = stripped[sep_start + len(sep_text):].lstrip()

        # 列数 = header 中 | 的数量 - 1
        col_count = header_part.count("|") - 1
        if col_count < 1:
            result.append(line)
            continue

        result.append(header_part)
        result.append(sep_text)

        # 按 | 拆分 body，过滤空串，按列数分组为行
        body_cells = [c.strip() for c in body_part.split("|")]
        body_cells = [c for c in body_cells if c]  # 去掉空格和空串
        for i in range(0, len(body_cells), col_count):
            row_cells = body_cells[i:i + col_count]
            if row_cells:
                result.append("| " + " | ".join(row_cells) + " |")

    return "\n".join(result)


def _is_table_line(line: str) -> bool:
    """判断一行是否为 Markdown 表格行（以 | 开头结尾，中间含 |）。"""
    return bool(re.match(r"^\|.+\|$", line.strip()))


def _parse_table(lines: list[str]) -> dict[str, Any]:
    """把连续的 Markdown 表格行转为 Tiptap table 节点。"""
    rows: list[dict] = []
    header_done = False

    for line in lines:
        stripped = line.strip()

        # 跳过分隔行（|---|---|）
        if _TABLE_SEP_RE.match(stripped):
            header_done = True
            continue

        # 按 | 切分单元格，去掉首尾空段
        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        cell_type = "tableHeader" if not header_done else "tableCell"

        row_cells: list[dict] = []
        for cell_text in cells:
            row_cells.append({
                "type": cell_type,
                "content": [{
                    "type": "paragraph",
                    "content": _parse_inline(cell_text) if cell_text else [{"type": "text", "text": ""}],
                }],
            })

        if row_cells:
            rows.append({"type": "tableRow", "content": row_cells})

    return {"type": "table", "content": rows}


# ── 行内格式 ──────────────────────────────────────────────


def _parse_inline(text: str) -> list[dict]:
    """解析行内格式（加粗 **text**）。"""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    nodes: list[dict] = []
    for j, part in enumerate(parts):
        if not part:
            continue
        if j % 2 == 1:
            nodes.append({"type": "text", "text": part, "marks": [{"type": "bold"}]})
        else:
            nodes.append({"type": "text", "text": part})
    return nodes or [{"type": "text", "text": text}]
