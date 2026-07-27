"""content_filter 三层规则测试。"""

from app.parsing.content_filter import filter_content


# ── 规则 2:长度阈值 ─────────────────────────────────────────

def test_rejects_short_content():
    """低于阈值被拒。"""
    assert filter_content("太短", title="x") is None
    assert filter_content("a" * 199, title="x") is None


def test_accepts_chinese_above_threshold():
    """中文 100 字以上接受。"""
    md = "专利" * 50  # 100 个中文字
    result = filter_content(md, title="测试")
    assert result is not None
    assert result.word_count >= 100


def test_accepts_english_above_threshold():
    """英文 200 字符以上接受。"""
    md = "This patent describes a method " * 10  # ~310 字符
    result = filter_content(md, title="Patent")
    assert result is not None


# ── 规则 1:Markdown 去噪 ────────────────────────────────────

def test_strips_navigation_links():
    """连续 5+ 链接行被移除。"""
    nav = "\n".join(f"[item{i}](/page{i})" for i in range(10))
    body = "专利正文" * 100
    result = filter_content(nav + "\n\n" + body, title="x")
    assert result is not None
    assert "item0" not in result.markdown  # 导航被移除
    assert "专利正文" in result.markdown


def test_keeps_few_links():
    """4 个以下链接行保留(可能是正文引用)。"""
    few_links = "\n".join(f"[ref{i}](/r{i})" for i in range(3))
    body = "专利正文" * 100
    result = filter_content(few_links + "\n\n" + body, title="x")
    assert result is not None
    assert "ref0" in result.markdown  # 保留


def test_strips_boilerplate_keywords():
    """boilerplate 关键词区块被移除。"""
    body = "专利正文" * 100
    md = "Subscribe to our newsletter\n\n" + body + "\n\nAccept all cookies"
    result = filter_content(md, title="x")
    assert result is not None
    assert "Subscribe" not in result.markdown
    assert "Accept all" not in result.markdown


def test_strips_html_comments():
    """HTML 注释残留被移除。"""
    md = "<!-- tracking code -->\n" + "专利正文" * 100
    result = filter_content(md, title="x")
    assert result is not None
    assert "<!--" not in result.markdown


def test_collapses_blank_lines():
    """3+ 连续空行压缩为 2。"""
    md = "段一" + "\n\n\n\n\n" + "段二" * 100
    result = filter_content(md, title="x")
    assert result is not None
    assert "\n\n\n" not in result.markdown


def test_strips_hr_separators():
    """整行 --- 分隔线被移除(页脚装饰),但表格分隔行保留。"""
    md = "专利正文" * 50 + "\n\n---\n\n更多内容" + "正文" * 50
    result = filter_content(md, title="x")
    assert result is not None
    # 整行 --- 被移除(注意:filter 后内容里不应有单独一行的 ---)
    lines = result.markdown.split("\n")
    assert not any(line.strip() == "---" for line in lines)


# ── 规则 3:语言检测 ─────────────────────────────────────────

def test_rejects_pure_russian():
    """纯俄文页面被拒(>30% 非中英脚本)。"""
    russian = "Привет мир " * 50
    assert filter_content(russian, title="x") is None


def test_rejects_pure_arabic():
    """纯阿拉伯文页面被拒。"""
    arabic = "مرحبا بالعالم " * 50
    assert filter_content(arabic, title="x") is None


def test_accepts_mixed_chinese_english():
    """中英混排页面接受(中文页带英文术语)。"""
    md = "本 patent 涉及 " * 50  # 中文为主,带英文
    result = filter_content(md, title="x")
    assert result is not None


# ── 标题规范化 ───────────────────────────────────────────────

def test_preserves_title():
    """标题被保留。"""
    md = "正文" * 100
    result = filter_content(md, title="测试专利标题")
    assert result is not None
    assert result.title == "测试专利标题"


def test_empty_title_falls_back_to_default():
    """空标题给一个默认值。"""
    md = "正文" * 100
    result = filter_content(md, title="")
    assert result is not None
    assert result.title  # 非空
