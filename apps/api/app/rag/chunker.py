"""章节语义分块器（设计 10.3，2026-07 语义边界改造）。

改造前是纯字符滑动窗口（800 字符硬切 + 100 overlap），在任意位置切断，
导致表格/句子/段落被腰斩。现改为语义边界感知：

1. 优先按段落（双换行）切——段落是自然语义单元
2. 表格（|...| 连续行）作为原子单元整体保留，不腰斩
3. 超长段落按句子边界（句号/问号/叹号/换行）二次切，不在词中间断
4. 保留 overlap：相邻块留 OVERLAP_CHARS 重叠，保证检索上下文连续性
5. 小段落合并：连续短段聚到 MAX_CHUNK_CHARS 附近再切，避免过碎

输入：sections=[{key, title, content}]，content 是纯文本（PDF/docx 提取或 Tiptap 转纯文本）。
输出：Chunk 列表（content + section_key + chunk_index）。
"""

import re
from dataclasses import dataclass

MAX_CHUNK_CHARS = 800
MIN_CHUNK_CHARS = 200
OVERLAP_CHARS = 100

# 句子结束符（中英文句号/问号/叹号），用于超长段落二次切分
_SENTENCE_END_RE = re.compile(r"[。！？!?\n]+")


@dataclass
class Chunk:
    content: str
    section_key: str | None
    chunk_index: int


def chunk_sections(sections: list[dict]) -> list[Chunk]:
    """把章节列表按语义边界分块。

    每个 section 独立分块（不跨章节合并，因章节本身是语义边界）。
    """
    chunks: list[Chunk] = []
    for sec in sections:
        text = (sec.get("content") or "").strip()
        if not text:
            continue
        key = sec.get("key")
        for piece in _split_text_semantic(text):
            piece = piece.strip()
            if piece:
                chunks.append(Chunk(content=piece, section_key=key, chunk_index=len(chunks)))
    return chunks


def _split_text_semantic(text: str) -> list[str]:
    """语义分块核心：段落 → 表格感知 → 超长按句切 → 小段合并 → overlap。"""
    # 1. 按段落（双换行）拆，表格行聚成原子 block
    blocks = _split_paragraphs_and_tables(text)

    # 2. 处理每个 block：表格整体保留；普通段落超长按句切
    pieces: list[str] = []
    for block in blocks:
        if _is_table_block(block):
            pieces.extend(_split_table(block))
        elif len(block) <= MAX_CHUNK_CHARS:
            pieces.append(block)
        else:
            pieces.extend(_split_by_sentence(block, MAX_CHUNK_CHARS))

    # 3. 合并过碎的小块
    merged = _merge_small_pieces(pieces, MAX_CHUNK_CHARS, MIN_CHUNK_CHARS)

    # 4. overlap
    return _add_overlap(merged, OVERLAP_CHARS)


def _split_paragraphs_and_tables(text: str) -> list[str]:
    """按双换行拆段落，连续的表格行（|...|）聚成一个 block 不拆散。"""
    raw_paras = re.split(r"\n\s*\n", text)
    blocks: list[str] = []
    table_buffer: list[str] = []

    def flush_table():
        if table_buffer:
            blocks.append("\n".join(table_buffer))
            table_buffer.clear()

    for para in raw_paras:
        para = para.strip()
        if not para:
            continue
        if _is_table_line(para):
            table_buffer.append(para)
        else:
            flush_table()
            blocks.append(para)
    flush_table()
    return blocks


def _is_table_line(line: str) -> bool:
    """判断是否为 Markdown 表格行（含 | 分隔符）。"""
    return "|" in line and line.strip().startswith("|")


def _is_table_block(block: str) -> bool:
    """判断一个 block 是否整体是表格（多行 |...| 占主导）。"""
    lines = [l for l in block.strip().split("\n") if l.strip()]
    if not lines:
        return False
    table_lines = [l for l in lines if _is_table_line(l)]
    return len(table_lines) >= 2 and len(table_lines) / len(lines) > 0.8


def _split_table(table_block: str) -> list[str]:
    """表格超长时按行切（保留表头重复到每块）。单块内不切行。"""
    if len(table_block) <= MAX_CHUNK_CHARS:
        return [table_block]
    lines = table_block.split("\n")
    if len(lines) < 2:
        return [table_block]
    header = lines[0]
    separator = lines[1] if len(lines) > 1 and _is_table_line(lines[1]) else None
    pieces = []
    current = [header] + ([separator] if separator else [])
    body_start = 2 if separator else 1
    for line in lines[body_start:]:
        candidate = current + [line]
        if len("\n".join(candidate)) > MAX_CHUNK_CHARS and len(current) > body_start:
            pieces.append("\n".join(current))
            current = [header] + ([separator] if separator else []) + [line]
        else:
            current = candidate
    if len(current) > body_start:
        pieces.append("\n".join(current))
    return pieces


def _split_by_sentence(text: str, max_chars: int) -> list[str]:
    """超长文本按句子边界切分，保留句末标点。"""
    sentences: list[str] = []
    last = 0
    for m in _SENTENCE_END_RE.finditer(text):
        sentences.append(text[last:m.end()])
        last = m.end()
    if last < len(text):
        sentences.append(text[last:])

    pieces = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) > max_chars and current:
            pieces.append(current)
            current = sent
        else:
            current += sent
    if current:
        pieces.append(current)
    return pieces


def _merge_small_pieces(pieces: list[str], max_chars: int, min_chars: int) -> list[str]:
    """合并连续小块到 max_chars 附近，避免过碎。"""
    if not pieces:
        return []
    merged: list[str] = []
    for p in pieces:
        if merged and len(merged[-1]) + len(p) + 1 <= max_chars:
            merged[-1] = merged[-1] + "\n" + p
        else:
            merged.append(p)
    return merged


def _add_overlap(pieces: list[str], overlap: int) -> list[str]:
    """相邻块添加 overlap（前一块尾部接到后一块开头）。"""
    if overlap <= 0 or len(pieces) <= 1:
        return pieces
    result = [pieces[0]]
    for i in range(1, len(pieces)):
        prev_tail = pieces[i - 1][-overlap:] if len(pieces[i - 1]) > overlap else pieces[i - 1]
        result.append(prev_tail + "\n" + pieces[i])
    return result
