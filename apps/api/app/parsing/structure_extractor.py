"""从 Word 文档提取章节结构（基于 Heading 样式名 + 文本模式兜底）。"""

import re

# 标题关键词 → 章节 key 映射（用于自动识别章节类型）
TITLE_KEY_MAP = {
    "发明名称": "name",
    "名称": "name",
    "技术领域": "field",
    "所属技术领域": "field",
    "背景技术": "background",
    "发明目的": "problem",
    "技术问题": "problem",
    "现有技术": "problem",
    "技术方案": "solution",
    "发明内容": "solution",
    "有益效果": "effect",
    "附图说明": "drawings",
    "附图": "drawings",
    "关键点": "key_points",
    "保护点": "key_points",
    "保护范围": "key_points",
    "欲保护": "key_points",
    # 兼容旧版模板的「具体实施方式」标题（旧文档导入时仍能识别，但新模板已用 key_points）
    "具体实施方式": "key_points",
    "实施方式": "key_points",
}

# 中文序号模式："一、"/"二、" 等
_CN_NUM = re.compile(r"^[一二三四五六七八九十]、")
# 括号序号："（一）"/"（1）" 等
_PAREN_NUM = re.compile(r"^[（(][一二三四五1-9][)）]")
# 数字序号："1."/"2." 等
_ARABIC_NUM = re.compile(r"^\d+[.、]")


def _guess_key(title: str) -> str:
    """根据标题文本猜测章节 key。"""
    for keyword, key in TITLE_KEY_MAP.items():
        if keyword in title:
            return key
    return "custom"


def extract_structure(doc) -> list[dict]:
    """从 python-docx Document 提取章节结构。

    两阶段：
    1. 按 Heading 样式名识别（标准做法）
    2. 无 Heading 时兜底：靠文本模式（中文序号 / 关键词 / 括号编号）识别

    返回 [{id, order, key, title, level}, ...]
    """
    # 阶段 1：样式识别
    sections = _extract_by_styles(doc)
    if sections:
        return sections

    # 阶段 2：文本模式兜底
    return _extract_by_text_patterns(doc)


def _extract_by_styles(doc) -> list[dict]:
    """按 Heading 样式名提取。"""
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
        sections.append({
            "id": f"sec-{order}",
            "order": order,
            "key": _guess_key(title),
            "title": title,
            "level": level,
        })
    return sections


def _extract_by_text_patterns(doc) -> list[dict]:
    """文本模式兜底：靠中文序号/括号编号/关键词识别段落为章节。

    只对短段落（≤80 字）做匹配，避免正文长段落被误判为标题。
    排除说明性段落（以"注："开头）、纯内容子项（如"动态权限管理：..."）。
    """
    sections = []
    order = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text or len(text) > 80:
            continue

        # 排除说明/注释段落
        if re.match(r"^注[：:\s]", text):
            continue
        # 排除指导语段落
        if text.startswith("技术交底书是"):
            continue

        level = _detect_text_level(text)
        if level is None:
            continue

        # 关键词+冒号模式（如"动态权限管理：..."）通常是段内小标题，
        # 不是顶层章节，降为 L2
        if level == 1 and re.match(r"^.{2,10}：.{10,}", text):
            # 但不是主章节关键词（名称/技术领域等）
            is_main = any(kw in text[:8] for kw in ("名称", "技术领域", "背景技术", "发明内容", "有益效果", "附图", "关键点", "保护点", "实施方式"))
            if not is_main:
                level = 2

        order += 1
        sections.append({
            "id": f"sec-{order}",
            "order": order,
            "key": _guess_key(text),
            "title": text,
            "level": level,
        })
    return sections


def _detect_text_level(text: str) -> int | None:
    """从文本模式推断标题层级。返回 None 表示不是标题。

    L1：中文大写序号开头（一、二、...）或含"："的关键词短段落
    L2：括号序号或英文数字序号开头
    """
    stripped = text.lstrip()

    # 中文序号 "一、"/"二、" → L1
    if _CN_NUM.match(stripped):
        return 1

    # 括号序号 "（一）"/"（1）" → L2
    if _PAREN_NUM.match(stripped):
        return 2

    # 数字序号 "1."/"2、" → L2
    if _ARABIC_NUM.match(stripped):
        return 2

    # 关键词匹配 → L1，但要求像标题（短文本 或 含冒号）
    for keyword in TITLE_KEY_MAP:
        if keyword in stripped and len(keyword) >= 2:
            # 超短文本（<20字）很可能是标题 → 直接接受
            if len(stripped) <= 20:
                return 1
            # 含"："的段落 → 标题模式（如"名称：（技术人员填写）"）
            if "：" in stripped:
                return 1
            # 不含冒号的长文本 → 可能是内容段落，跳过
            return None

    return None


def _parse_heading_level(style_name: str) -> int | None:
    """从样式名解析 Heading 级别。返回 None 表示不是 Heading。"""
    import re

    name = style_name.lower().strip()
    # 标准英文 Heading： "heading 1" / "heading 2"
    # 中文标题（带空格）："标题 1" / "标题 2"
    # 中文标题（无空格）："标题1" / "标题2"
    for prefix in ("heading ", "标题 "):
        if name.startswith(prefix):
            try:
                return int(name[len(prefix):])
            except ValueError:
                return None
    # "标题N" 无空格变体
    m = re.match(r"^标题(\d+)$", name)
    if m:
        return int(m.group(1))
    return None
