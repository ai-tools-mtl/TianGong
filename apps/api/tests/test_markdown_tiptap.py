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
