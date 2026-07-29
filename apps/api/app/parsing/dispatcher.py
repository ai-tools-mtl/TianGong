"""按文件扩展名分发到对应解析器,返回统一纯文本(计划 T7)。

供 knowledge_service 的 upload 流程调用:外部素材上传 → 提取文本 → 分块 → 向量化。
- pdf → pdf_parser(扫描件拒收)
- docx → 直接抽段落文本(不造 structure,这里只要文本供分块)
- 其他 → 拒收
"""

from io import BytesIO

from app.core.text_utils import sanitize_text_for_pg
from app.parsing.pdf_parser import extract_pdf_text


def extract_text(filename: str, content: bytes) -> str:
    """根据扩展名提取文本。

    统一用 sanitize_text_for_pg 清洗 NUL + C0 控制字符：PDF/docx 解析出的文本
    偶尔含二进制残留的 NUL，PostgreSQL 的 text 类型不接受（psycopg 报 DataError），
    会导致后续 chunk 入库失败。

    Raises:
        ValueError: 不支持的格式,或 PDF 为扫描件(无文本层)。
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "pdf":
        text = extract_pdf_text(content)
        if not text:
            raise ValueError("PDF 无文本层(疑似扫描件),暂不支持")
    elif ext == "docx":
        text = _docx_to_text(content)
    else:
        raise ValueError(f"不支持的格式: .{ext}")

    return sanitize_text_for_pg(text)


def _docx_to_text(content: bytes) -> str:
    """从 docx 抽取所有段落文本(用于分块,不关心 structure)。"""
    from docx import Document

    doc = Document(BytesIO(content))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n".join(parts)
