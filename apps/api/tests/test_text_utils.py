"""text_utils 清洗工具测试（P0：NUL/控制字符/文件名清洗）。"""

from app.core.text_utils import sanitize_filename, sanitize_text_for_pg


# ── sanitize_text_for_pg ──


def test_sanitize_strips_nul():
    """NUL(\\x00) 是 PG text 列唯一硬拒绝的字符，必须剔除。"""
    assert sanitize_text_for_pg("正常\x00含NUL") == "正常含NUL"


def test_sanitize_strips_control_chars_but_keeps_whitespace():
    """C0 控制字符剔除，但保留 \\t \\n \\r（常见文本结构）。"""
    assert sanitize_text_for_pg("a\x07b\x01c") == "abc"
    assert sanitize_text_for_pg("a\tb\nc\rd") == "a\tb\nc\rd"


def test_sanitize_handles_none_and_empty():
    assert sanitize_text_for_pg(None) == ""
    assert sanitize_text_for_pg("") == ""


def test_sanitize_preserves_normal_text():
    """正常中文/英文/标点不受影响。"""
    assert sanitize_text_for_pg("专利技术方案 - abc 123") == "专利技术方案 - abc 123"


# ── sanitize_filename ──


def test_filename_strips_nul_and_path_separators():
    """去 NUL + 路径分隔符（防路径遍历/拼接异常）。"""
    assert sanitize_filename("a/../b\x00c.pdf") == "bc.pdf"
    assert sanitize_filename("a\\b/c.pdf") == "c.pdf"


def test_filename_truncates_to_255():
    """超长文件名截断到 255（PG varchar(255) 上限）。"""
    long_name = "x" * 300
    result = sanitize_filename(long_name)
    assert len(result) == 255


def test_filename_removes_illegal_chars():
    """去 Windows/Linux 文件名非法字符。"""
    result = sanitize_filename('a:b*c?"d<e>f|g.txt')
    for ch in '\\/:*?"<>|':
        assert ch not in result


def test_filename_empty_fallback():
    """空名/None 兜底为 upload。"""
    assert sanitize_filename("") == "upload"
    assert sanitize_filename(None) == "upload"


def test_filename_preserves_chinese():
    """中文文件名正常保留。"""
    assert sanitize_filename("区块链溯源报告.pdf") == "区块链溯源报告.pdf"
