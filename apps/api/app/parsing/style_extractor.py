"""提取 Word 文档的样式信息（字体/字号/加粗，含继承解析与东亚字体）。"""

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def extract_styles(doc) -> dict:
    """提取各级标题和正文的样式。

    返回 {style_key: {font_name, font_size, bold, italic}, ...}
    style_key 如 "heading_1" / "normal"
    """
    result = {}
    for style in doc.styles:
        # 只处理有 font 属性的样式（跳过 _NumberingStyle 等无 font 的）
        font = getattr(style, "font", None)
        if font is None:
            continue
        name = (style.name or "").lower().replace(" ", "_")
        if not name:
            continue
        result[name] = {
            "font_name": _resolve_font_name(font),
            "font_size": font.size.pt if font.size else None,
            "bold": font.bold,
            "italic": font.italic,
        }
    return result


def _resolve_font_name(font) -> str | None:
    """解析字体名，含东亚字体（中文文档常见，详见设计 9.6.3）。"""
    if font.name:
        return font.name
    try:
        rpr = font.element
        if rpr is not None:
            rfonts = rpr.find(f"{{{_W_NS}}}rFonts")
            if rfonts is not None:
                return (
                    rfonts.get(f"{{{_W_NS}}}eastAsia")
                    or rfonts.get(f"{{{_W_NS}}}ascii")
                )
    except Exception:
        pass
    return None
