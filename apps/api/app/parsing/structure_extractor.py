"""从 Word 文档提取章节结构（基于 Heading 样式名）。"""

# 标题关键词 → 章节 key 映射（用于自动识别章节类型）
TITLE_KEY_MAP = {
    "发明名称": "name",
    "技术领域": "field",
    "背景技术": "background",
    "发明目的": "problem",
    "技术问题": "problem",
    "技术方案": "solution",
    "有益效果": "effect",
    "附图说明": "drawings",
    "具体实施方式": "embodiment",
}


def _guess_key(title: str) -> str:
    """根据标题文本猜测章节 key。"""
    for keyword, key in TITLE_KEY_MAP.items():
        if keyword in title:
            return key
    return "custom"


def extract_structure(doc) -> list[dict]:
    """从 python-docx Document 提取章节结构。

    遍历段落，按 Heading 样式名（Heading 1/2/3...）识别章节。
    返回 [{id, order, key, title, level}, ...]
    """
    sections = []
    order = 0
    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""
        level = _parse_heading_level(style_name)
        if level is None:
            continue
        title = para.text.strip()
        if not title:
            continue
        order += 1
        key = _guess_key(title)
        sections.append({
            "id": f"sec-{order}",
            "order": order,
            "key": key,
            "title": title,
            "level": level,
        })
    return sections


def _parse_heading_level(style_name: str) -> int | None:
    """从样式名解析 Heading 级别。返回 None 表示不是 Heading。"""
    name = style_name.lower().strip()
    for prefix in ("heading ", "标题 "):
        if name.startswith(prefix):
            try:
                return int(name[len(prefix):])
            except ValueError:
                return None
    return None
