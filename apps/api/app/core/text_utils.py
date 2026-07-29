"""文本清洗工具：统一处理写入 PG text/JSONB 列前的脏数据。

根因：PostgreSQL 的 text/varchar 列不接受 NUL(\\x00)字节（psycopg 报 DataError），
JSONB 的字符串值同样禁止 NUL。PDF/docx 解析、网页抓取、Tiptap 编辑器内容、
用户上传的文件名等都可能含 NUL 或 C0 控制字符，导致入库失败。

本模块提供统一清洗入口，所有写 Text/JSONB 的汇聚点都应调用，避免每个提取器
各修一遍（曾发生 dispatcher 修了但 summary_service._extract_text 漏修的同类 bug）。
"""

import os
import re

# C0 控制字符，保留 \t(\x09) \n(\x0a) \r(\x0d)。NUL(\x00) 单独 replace 先处理。
_TEXT_CTL_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f]")

# 文件名非法字符（Windows/Linux）+ 控制字符 + 路径分隔
_FILENAME_ILLEGAL = set('\\/:*?"<>|')


def sanitize_text_for_pg(s: str | None) -> str:
    """清洗 PG text/JSONB 列不接受或不友好的字符。

    - 剔除 NUL(\\x00)：PG text/JSONB 都拒绝
    - 剔除其余 C0 控制字符(\\x01-\\x1f 除 \\t\\n\\r)：PG 接受但干扰分词/embedding/渲染

    保留 \\t\\n\\r（常见文本结构）。None/空串返回空串。
    """
    if not s:
        return ""
    return _TEXT_CTL_RE.sub("", s.replace("\x00", ""))


def sanitize_filename(name: str | None) -> str:
    """清洗文件名：去 NUL/控制符/路径分隔符 + 截断到 255 字符。

    - 去路径分隔符（\\ /）防路径遍历/拼接异常
    - 取 basename（防 a/../../b 这类）
    - 截断 255（PG varchar(255) 上限，UTF-8 字节更宽松但字符数对齐）
    - 空名兜底为 "upload"
    """
    if not name:
        return "upload"
    # 先去 NUL，再做 basename（basename 对含 NUL 的输入行为不稳）
    cleaned = name.replace("\x00", "")
    # 统一路径分隔后取 basename，防路径遍历
    base = os.path.basename(cleaned.replace("\\", "/"))
    # 去文件系统非法字符 + 控制字符
    safe = "".join(
        c for c in base
        if c not in _FILENAME_ILLEGAL and (c >= " " or c in "\t")
    ).strip()
    return (safe[:255] or "upload")
