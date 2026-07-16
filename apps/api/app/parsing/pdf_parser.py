"""PDF 文本提取(外部导入素材用,计划 T7)。

策略:用 pypdf 提取文本层。扫描件(无文本层)返回空串,
由 dispatcher 判定后拒收(关键约束非目标:OCR 不做)。
"""

from io import BytesIO

from pypdf import PdfReader


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """提取 PDF 全文。

    Returns:
        各页文本用换行拼接的纯文本(已 strip)。
    Raises:
        ValueError: 字节不是合法 PDF。
    """
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception as e:
        raise ValueError(f"无效 PDF: {e}") from e
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
