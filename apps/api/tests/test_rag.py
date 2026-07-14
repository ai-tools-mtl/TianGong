from app.rag.chunker import chunk_sections


def test_chunk_single_short_section():
    sections = [{"key": "name", "content": "一种智能温控系统"}]
    chunks = chunk_sections(sections)
    assert len(chunks) == 1
    assert chunks[0].content == "一种智能温控系统"
    assert chunks[0].section_key == "name"


def test_chunk_empty_section_skipped():
    sections = [{"key": "field", "content": ""}]
    chunks = chunk_sections(sections)
    assert len(chunks) == 0


def test_chunk_long_section_split():
    long_text = "技术方案内容。" * 200
    sections = [{"key": "solution", "content": long_text}]
    chunks = chunk_sections(sections)
    assert len(chunks) > 1
    assert all(c.section_key == "solution" for c in chunks)


def test_chunk_multiple_sections():
    sections = [
        {"key": "name", "content": "发明名称"},
        {"key": "background", "content": "背景技术内容"},
    ]
    chunks = chunk_sections(sections)
    assert len(chunks) == 2
    assert chunks[0].section_key == "name"
    assert chunks[1].section_key == "background"
