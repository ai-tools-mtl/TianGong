from app.ai.markdown_to_tiptap import markdown_to_tiptap


def test_plain_paragraph():
    doc = markdown_to_tiptap("普通段落")
    assert doc["type"] == "doc"
    assert doc["content"][0]["type"] == "paragraph"


def test_heading():
    doc = markdown_to_tiptap("## 标题二")
    assert doc["content"][0]["type"] == "heading"
    assert doc["content"][0]["attrs"]["level"] == 2


def test_bullet_list():
    doc = markdown_to_tiptap("- 列表项")
    assert doc["content"][0]["type"] == "bulletList"


def test_ordered_list():
    doc = markdown_to_tiptap("1. 有序项")
    assert doc["content"][0]["type"] == "orderedList"


def test_bold_text():
    doc = markdown_to_tiptap("**加粗**文字")
    para = doc["content"][0]
    assert any(m.get("type") == "bold" for n in para["content"] for m in n.get("marks", []))


def test_empty_returns_minimal_doc():
    doc = markdown_to_tiptap("")
    assert doc["content"][0]["type"] == "paragraph"


# ── 表格测试 ──────────────────────────────────────────────


def test_table_basic():
    md = """| 名称 | 功能 |
|------|------|
| 模块A | 处理请求 |
| 模块B | 响应数据 |"""
    doc = markdown_to_tiptap(md)
    table = doc["content"][0]
    assert table["type"] == "table"
    assert len(table["content"]) == 3  # header + 2 data rows

    # 首行为表头
    header_row = table["content"][0]
    assert header_row["type"] == "tableRow"
    assert header_row["content"][0]["type"] == "tableHeader"
    assert header_row["content"][0]["content"][0]["content"][0]["text"] == "名称"

    # 数据行
    data_row = table["content"][1]
    assert data_row["content"][0]["type"] == "tableCell"
    assert data_row["content"][0]["content"][0]["content"][0]["text"] == "模块A"


def test_table_cell_with_bold():
    md = "| **重点** | 说明 |\n|------|------|\n| 值 | 描述 |"
    doc = markdown_to_tiptap(md)
    # 表头第一格应有 bold mark
    header_cell = doc["content"][0]["content"][0]["content"][0]
    text_node = header_cell["content"][0]["content"][0]
    assert text_node["text"] == "重点"
    assert any(m["type"] == "bold" for m in text_node.get("marks", []))


def test_table_followed_by_paragraph():
    md = """| A | B |
|---|---|
| 1 | 2 |

普通段落"""
    doc = markdown_to_tiptap(md)
    assert doc["content"][0]["type"] == "table"
    assert doc["content"][1]["type"] == "paragraph"


def test_table_single_row_no_header():
    """无分隔行的单行表格：整行作为 tableHeader。"""
    md = "| 字段 | 类型 | 说明 |"
    doc = markdown_to_tiptap(md)
    table = doc["content"][0]
    assert table["type"] == "table"
    # 无分隔行 → header_done 始终 False → 全部为 tableHeader
    assert table["content"][0]["content"][0]["type"] == "tableHeader"


def test_table_alignment_separator():
    """含对齐语法的分隔行（:---:）应被正确跳过。"""
    md = """| 左对齐 | 居中 | 右对齐 |
|:---|:---:|---:|
| a | b | c |"""
    doc = markdown_to_tiptap(md)
    table = doc["content"][0]
    # 分隔行被跳过，只有 header + 1 数据行
    assert len(table["content"]) == 2
    assert table["content"][0]["content"][0]["type"] == "tableHeader"
    assert table["content"][1]["content"][0]["type"] == "tableCell"


def test_inline_table_expanded():
    """单行压缩表格：| h1 | h2 | |---|---| | a | b | → 正常 table。"""
    md = "| 技能名称 | 用途 | |---|---| | patent-de-ai | 去 AI 味 | | patent-effect | 有益效果 |"
    doc = markdown_to_tiptap(md)
    table = doc["content"][0]
    assert table["type"] == "table"
    assert len(table["content"]) == 3  # header + 2 data rows
    # header
    assert table["content"][0]["content"][0]["type"] == "tableHeader"
    assert table["content"][0]["content"][0]["content"][0]["content"][0]["text"] == "技能名称"
    # data row 1
    assert table["content"][1]["content"][0]["type"] == "tableCell"
    assert table["content"][1]["content"][0]["content"][0]["content"][0]["text"] == "patent-de-ai"
