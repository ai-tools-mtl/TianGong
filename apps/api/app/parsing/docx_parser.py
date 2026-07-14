"""Word 文档解析编排：调用结构/样式/编号提取器，组装成 Template 数据。"""

from dataclasses import dataclass

from app.parsing.numbering_resolver import NumberingResolver, extract_numbering_from_text
from app.parsing.structure_extractor import extract_structure
from app.parsing.style_extractor import extract_styles


@dataclass
class ParsedTemplate:
    structure: list[dict]
    styles: dict
    numbering: dict


def parse_docx(doc) -> ParsedTemplate:
    """解析 python-docx Document，返回结构化模板数据。"""
    structure = extract_structure(doc)
    styles = extract_styles(doc)
    numbering = _extract_numbering(doc, structure)
    return ParsedTemplate(structure=structure, styles=styles, numbering=numbering)


def _extract_numbering(doc, structure: list[dict]) -> dict:
    """提取编号规则：尝试 numbering.xml，正则兜底。"""
    resolver = None
    try:
        numbering_part = doc.part.numbering_part
        resolver = (
            NumberingResolver(numbering_part.element)
            if numbering_part
            else NumberingResolver(None)
        )
    except Exception:
        resolver = NumberingResolver(None)

    section_numbers = {}
    para_idx = 0
    for section in structure:
        for p in doc.paragraphs[para_idx:]:
            para_idx += 1
            if p.text.strip() == section["title"]:
                num = resolver.resolve_for_paragraph(p)
                if num is None:
                    num = extract_numbering_from_text(p.text)
                if num:
                    section_numbers[section["id"]] = num
                break

    return {
        "section_numbers": section_numbers,
        "resolver_available": resolver._element is not None,
    }
