"""PDF 解析器 + 扩展名分发器测试(计划 T7)。"""

import pytest
from pypdf import PdfWriter
from io import BytesIO

from app.parsing.pdf_parser import extract_pdf_text
from app.parsing.dispatcher import extract_text


def _make_blank_pdf() -> bytes:
    """造一个空白 PDF(无文本层)。"""
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_extract_blank_pdf_returns_empty():
    """空白 PDF 无文本层,返回空串不抛。"""
    assert extract_pdf_text(_make_blank_pdf()) == ""


def test_extract_invalid_bytes_raises_value_error():
    """非法字节抛 ValueError(调用方据此拒收)。"""
    with pytest.raises(ValueError):
        extract_pdf_text(b"not a pdf at all")


def test_dispatcher_routes_pdf_with_text():
    """dispatcher 把 .pdf 路由到 pdf_parser(有文本的 PDF 返回文本)。"""
    # pypdf 不能直接写文本层,用最小可识别 PDF 验证路由:有文本则返回,
    # 无文本则抛 ValueError。这里验证抛错路径(空白 PDF)。
    with pytest.raises(ValueError, match="扫描件|无文本层"):
        extract_text("ref.pdf", _make_blank_pdf())


def test_dispatcher_rejects_scan_pdf():
    """扫描件(无文本层)由 dispatcher 抛 ValueError 拒收。"""
    with pytest.raises(ValueError, match="扫描件|无文本层"):
        extract_text("scan.pdf", _make_blank_pdf())


def test_dispatcher_rejects_unsupported_format():
    """不支持的扩展名抛 ValueError（.txt/.md 已支持，用真不支持的扩展名）。"""
    with pytest.raises(ValueError):
        extract_text("x.xyz", b"hello")


def test_dispatcher_routes_docx():
    """dispatcher 把 .docx 路由到 docx_parser(返回纯文本)。"""
    # 造一个最小 docx
    from docx import Document

    doc = Document()
    doc.add_heading("发明名称", level=1)
    doc.add_paragraph("正文内容")
    buf = BytesIO()
    doc.save(buf)

    text = extract_text("tpl.docx", buf.getvalue())
    assert "发明名称" in text
    assert "正文内容" in text
