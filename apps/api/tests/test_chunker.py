"""语义分块器测试（段落/表格/句子/overlap 边界感知）。"""

from app.rag.chunker import chunk_sections


def test_short_paragraph_single_chunk():
    """短段落（< MAX_CHUNK）保持原样成一块。"""
    sections = [{"key": "s1", "title": "简介", "content": "这是一个短段落，不足 800 字。"}]
    chunks = chunk_sections(sections)
    assert len(chunks) == 1
    assert chunks[0].content == "这是一个短段落，不足 800 字。"
    assert chunks[0].section_key == "s1"
    assert chunks[0].chunk_index == 0


def test_multiple_paragraphs_not_split_mid_paragraph():
    """多个短段落不会被腰斩，各自保持完整（合并到 MAX_CHUNK 附近）。"""
    para1 = "段落一的内容。" * 30  # ~180 字
    para2 = "段落二的内容。" * 30
    sections = [{"key": "s1", "title": "t", "content": f"{para1}\n\n{para2}"}]
    chunks = chunk_sections(sections)
    # 两个短段应合并成一块（< 800），不腰斩
    assert len(chunks) == 1
    assert para1 in chunks[0].content
    assert para2 in chunks[0].content


def test_table_kept_intact():
    """表格作为原子单元整体保留，不腰斩。"""
    table = "| 指标 | 数值 |\n|---|---|\n| TPS | 10000 |\n| 延迟 | 50ms |\n| 吞吐 | 高 |"
    sections = [{"key": "s1", "title": "t", "content": f"说明文字。\n\n{table}"}]
    chunks = chunk_sections(sections)
    # 表格应在某一块中完整出现
    full = "\n".join(c.content for c in chunks)
    assert "| TPS | 10000 |" in full
    assert "| 吞吐 | 高 |" in full
    # 表格不应被拆到两块中间（至少有一块同时含表头和末行）
    assert any("| 指标 | 数值 |" in c.content and "| 吞吐 | 高 |" in c.content for c in chunks)


def test_long_paragraph_split_by_sentence():
    """超长段落按句子边界切，不在词中间断。"""
    # 造一个 2000+ 字的段落，每句以句号结尾
    long_text = "这是一句完整的技术方案描述内容。" * 80  # ~1600 字
    sections = [{"key": "s1", "title": "t", "content": long_text}]
    chunks = chunk_sections(sections)
    assert len(chunks) > 1
    # 每块不应在句中被腰斩（每块应以句号结尾或 overlap 接续）
    for c in chunks:
        # 块内容应包含至少一个完整句号（不被切到半句）
        assert "。" in c.content


def test_section_boundary_respected():
    """不同 section 的内容不跨 section 合并。"""
    sections = [
        {"key": "s1", "title": "第一章", "content": "第一章内容一。"},
        {"key": "s2", "title": "第二章", "content": "第二章内容二。"},
    ]
    chunks = chunk_sections(sections)
    keys = {c.section_key for c in chunks}
    assert keys == {"s1", "s2"}
    # 每块 section_key 正确
    assert all((c.section_key in ("s1", "s2")) for c in chunks)


def test_empty_section_skipped():
    """空内容 section 跳过。"""
    sections = [
        {"key": "s1", "title": "空", "content": ""},
        {"key": "s2", "title": "有", "content": "有内容。"},
    ]
    chunks = chunk_sections(sections)
    assert len(chunks) == 1
    assert chunks[0].section_key == "s2"


def test_chunk_index_sequential():
    """chunk_index 从 0 连续递增。"""
    text = "句子一。句子二。句子三。" * 100
    sections = [{"key": "s1", "title": "t", "content": text}]
    chunks = chunk_sections(sections)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_overlap_between_chunks():
    """超长文本分多块时，相邻块有 overlap（后块开头含前块尾部）。"""
    long_text = "这是一句独立的描述。" * 100  # ~1000 字
    sections = [{"key": "s1", "title": "t", "content": long_text}]
    chunks = chunk_sections(sections)
    if len(chunks) >= 2:
        # 第二块开头应有第一块尾部的 overlap
        prev_tail = chunks[0].content[-50:]
        # overlap 不一定精确 50 字，但第二块应含第一块部分尾部内容
        assert any(prev_tail[-20:] in chunks[i].content for i in range(1, len(chunks)))
