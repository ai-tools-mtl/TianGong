"""按文件扩展名分发到对应解析器,返回统一纯文本(计划 T7)。

供 knowledge_service 的 upload 流程调用:外部素材上传 → 提取文本 → 分块 → 向量化。
- pdf → 优先 MinerU（保留表格/标题的 Markdown，含 OCR 扫描件）；未配置降级 pypdf（扫描件拒收）
- docx → 直接抽段落文本(不造 structure,这里只要文本供分块)
- 其他 → 拒收
"""

from io import BytesIO

from app.core.text_utils import sanitize_text_for_pg
from app.parsing.pdf_parser import extract_pdf_text


def extract_text(filename: str, content: bytes, db=None) -> str:
    """根据扩展名提取文本。

    PDF 解析优先级：
    1. 传了 db 且 MinerU 已配置 → 走 MinerU（结构化 Markdown，含 OCR，扫描件可处理）
    2. 否则 → pypdf 纯文本（扫描件无文本层则拒收）

    统一用 sanitize_text_for_pg 清洗 NUL + C0 控制字符。

    Args:
        db: 数据库 session（用于解析 MinerU 配置）。None 时走 pypdf fallback。
    Raises:
        ValueError: 不支持的格式,或 PDF 为扫描件(无文本层,且未配 MinerU)。
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "pdf":
        text = _extract_pdf(filename, content, db)
    elif ext == "docx":
        text = _docx_to_text(content)
    else:
        raise ValueError(f"不支持的格式: .{ext}")

    return sanitize_text_for_pg(text)


def _extract_pdf(filename: str, content: bytes, db) -> str:
    """PDF 提取：MinerU 优先（结构化 Markdown），降级 pypdf（纯文本）。"""
    if db is not None:
        try:
            from app.services.mineru_client import resolve_mineru_config, parse_pdf_to_markdown

            if resolve_mineru_config(db) is not None:
                return parse_pdf_to_markdown(db, content=content, filename=filename)
        except Exception as e:
            # MinerU 失败时降级到 pypdf（不阻断上传，记日志）
            from loguru import logger
            logger.warning(f"MinerU 解析失败，降级 pypdf：{e}")
    # pypdf fallback
    text = extract_pdf_text(content)
    if not text:
        raise ValueError("PDF 无文本层(疑似扫描件)；配置 MinerU 可解析扫描件")
    return text


def _docx_to_text(content: bytes) -> str:
    """从 docx 抽取所有段落文本(用于分块,不关心 structure)。"""
    from docx import Document

    doc = Document(BytesIO(content))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n".join(parts)
