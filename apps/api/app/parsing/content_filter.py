"""网页内容质量过滤(三层规则)。

规则 1:Markdown 去噪(移除导航/boilerplate/HTML 注释/连续空行)
规则 2:长度阈值(中文 100 字 / 英文 200 字符)
规则 3:语言检测(只接受中文/英文,拒其他脚本)

返回 None 表示该页被拒绝入库。
spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 6 节。
"""

import re
from dataclasses import dataclass

MIN_CONTENT_CHARS = 200       # 英文阈值
MIN_CONTENT_CHARS_ZH = 100    # 中文阈值(信息密度高,放宽)
MAX_NAV_LINK_RUN = 5          # 连续链接行阈值(>= 此值视为导航)
DEFAULT_TITLE = "无标题网页"

BOILERPLATE_KEYWORDS = [
    "Cookie", "Subscribe", "Newsletter", "Sign up", "Related posts",
    "Share this", "Skip to content", "Back to top", "Accept all",
]

# 连续 N+ 行 markdown 链接(典型导航菜单)
_NAV_LINK_BLOCK = re.compile(
    r"((?:\[.+?\]\(.+?\)\s*\n){" + re.escape(str(MAX_NAV_LINK_RUN)) + r",})",
    re.MULTILINE,
)
# 整行只有连字符(页脚分隔线),但不含管道符(避免误删表格)
_HR_SEPARATOR = re.compile(r"^[ \t]*-{3,}[ \t]*$", re.MULTILINE)
# HTML 注释
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# 连续 3+ 空行
_MULTI_BLANK = re.compile(r"\n{3,}")


@dataclass
class FilteredContent:
    markdown: str   # 去噪后的干净正文
    title: str      # 规范化标题
    word_count: int # 字数(过滤判断 + 配额展示用)


def filter_content(raw_markdown: str, title: str = "") -> FilteredContent | None:
    """规则质量过滤。返回 None 表示该页被拒绝入库。"""
    if not raw_markdown:
        return None

    # 规则 1:去噪
    cleaned = _denoise(raw_markdown)

    # 规则 2:长度阈值
    total, cjk = _count_chars(cleaned)
    threshold = MIN_CONTENT_CHARS_ZH if cjk > 0 else MIN_CONTENT_CHARS
    if total < threshold:
        return None

    # 规则 3:语言检测
    if not _is_supported_language(cleaned, cjk):
        return None

    normalized_title = title.strip() if title else DEFAULT_TITLE
    return FilteredContent(
        markdown=cleaned,
        title=normalized_title,
        word_count=total,
    )


def _denoise(markdown: str) -> str:
    """规则 1:去 boilerplate。"""
    # 移除 HTML 注释
    text = _HTML_COMMENT.sub("", markdown)
    # 移除连续 5+ 链接行(导航菜单)
    text = _NAV_LINK_BLOCK.sub("", text)
    # 移除整行 --- 分隔线(页脚装饰),保留表格分隔行(|---|)
    text = _HR_SEPARATOR.sub("", text)
    # 移除 boilerplate 关键词所在整行
    lines = text.split("\n")
    kept = []
    for line in lines:
        if any(kw.lower() in line.lower() for kw in BOILERPLATE_KEYWORDS):
            continue
        kept.append(line)
    text = "\n".join(kept)
    # 压缩连续空行
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def _count_chars(markdown: str) -> tuple[int, int]:
    """返回 (总字符数, 中文字符数)。"""
    cjk = sum(1 for c in markdown if '\u4e00' <= c <= '\u9fff')
    return len(markdown), cjk


def _is_supported_language(markdown: str, cjk_count: int) -> bool:
    """判定页面是否中文/英文为主。

    宽松策略(避免误杀专利领域英文内容):
    - CJK 占比 >= 5% → 中文,接受
    - 拉丁字母占比 >= 50%(且 CJK < 5%)→ 英文,接受
    - 否则(CJK < 5% 且拉丁字母 < 50%,即以其他脚本为主)→ 拒绝
    """
    if not markdown:
        return False
    # CJK 占比 >= 5% → 中文
    if cjk_count / len(markdown) >= 0.05:
        return True
    # 统计拉丁字母 + 数字 + 常见标点
    latin = sum(
        1 for c in markdown
        if c.isascii() and (c.isalnum() or c in " \n\t.,;:!?-_'\"()[]{}@#$%^&*+=/\\|<>`~")
    )
    if latin / len(markdown) >= 0.5:
        return True  # 以拉丁为主 → 英文
    return False
