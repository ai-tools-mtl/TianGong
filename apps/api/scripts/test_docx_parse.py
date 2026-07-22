"""本地测试 docx 解析流水线（不经过 HTTP 上传 / Minio）。

Usage:
    uv run python scripts/test_docx_parse.py path/to/file.docx
"""
import sys
from io import BytesIO

from docx import Document

from app.parsing.docx_parser import parse_docx
from app.services.parse_service import _normalize_docx_namespaces


def main(filepath: str) -> int:
    with open(filepath, "rb") as f:
        raw = f.read()

    print(f"[1] 文件大小：{len(raw)} 字节")
    print(f"[2] 魔数：{raw[:2]}")

    normalized = _normalize_docx_namespaces(raw)
    if normalized is not raw:
        print(f"[3] 已归一化 purl.oclc.org 命名空间")
    else:
        print("[3] 无需归一化")

    try:
        doc = Document(BytesIO(normalized))
        print(f"[4] python-docx 加载成功 ✓")
    except Exception as e:
        print(f"[4] python-docx 加载失败 ✗：{e}")
        return 1

    try:
        parsed = parse_docx(doc)
        print(f"[5] 解析成功 ✓")
        print(f"    章节数：{len(parsed.structure)}")
        for s in parsed.structure:
            print(f"      {s['order']}. [{s['key']}] {s['title']} (L{s['level']})")
        print(f"    样式数：{len(parsed.styles)}")
        print(f"    编号信息：{'有' if parsed.numbering else '无'}")
    except Exception as e:
        print(f"[5] 解析失败 ✗：{e}")
        return 1

    print("\n✓ 全部通过")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/test_docx_parse.py <file.docx>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
