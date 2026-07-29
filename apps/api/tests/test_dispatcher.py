"""parsing.dispatcher 测试：文本提取 + NUL 清洗。

NUL（\\x00）清洗：PDF/docx 解析出的文本偶尔含二进制残留的 NUL 字节，
PostgreSQL 的 text 类型不接受（psycopg 报 DataError），必须在提取后剔除。
"""

from unittest.mock import patch

from app.parsing.dispatcher import extract_text


def test_extract_pdf_text_strips_nul_bytes():
    """PDF 提取的文本含 NUL → extract_text 应剔除，避免后续 PG 入库 DataError。"""
    with patch("app.parsing.dispatcher.extract_pdf_text", return_value="正常\x00含NUL\x00文本"):
        text = extract_text("test.pdf", b"fake")
    assert "\x00" not in text
    assert text == "正常含NUL文本"


def test_extract_docx_text_strips_nul_bytes():
    """docx 提取的文本含 NUL → 同样剔除。"""
    with patch("app.parsing.dispatcher._docx_to_text", return_value="段落一\x00段落二"):
        text = extract_text("test.docx", b"fake")
    assert "\x00" not in text
    assert text == "段落一段落二"


def test_extract_text_rejects_unsupported_format():
    """不支持的格式 → ValueError。"""
    import pytest

    with pytest.raises(ValueError):
        extract_text("test.xyz", b"fake")
