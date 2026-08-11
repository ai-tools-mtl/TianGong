"""PDF 导出测试。

weasyprint 需系统库 pango/cairo/gobject。Windows/无系统库环境自动跳过 PDF 生成测试。
纯 HTML 转换和转义测试不依赖 weasyprint，始终运行。
"""
import pytest

# weasyprint import 本身可能成功，但加载底层 GLib 库时 OSError。
try:
    import weasyprint  # noqa: F401
    _HAS_WEASYPRINT = True
except (ImportError, OSError, Exception):
    _HAS_WEASYPRINT = False

# 仅 PDF 端点测试需要系统库，用 marker 控制
needs_weasyprint = pytest.mark.skipif(
    not _HAS_WEASYPRINT,
    reason="weasyprint 系统库（pango/cairo/gobject）不可用，跳过 PDF 生成测试",
)


def _login(client, registered_user):
    r = client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert r.status_code == 200


def _create_project(db_session, registered_user):
    from app.models import Project, Section
    import uuid

    uid = uuid.UUID(registered_user["id"])
    p = Project(user_id=uid, title="PDF测试项目")
    db_session.add(p)
    db_session.commit()
    s = Section(
        project_id=p.id, template_section_id="bg", key="background",
        title="背景技术", order=1, status="drafting",
        content={
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "这是测试段落内容。"}
                ]},
                {"type": "heading", "attrs": {"level": 2}, "content": [
                    {"type": "text", "text": "子标题"}
                ]},
            ],
        },
    )
    db_session.add(s)
    db_session.commit()
    return str(p.id)


@needs_weasyprint
def test_export_pdf_endpoint(client, registered_user, db_session):
    """PDF 导出端点返回合法 PDF（需系统库）。"""
    _login(client, registered_user)
    pid = _create_project(db_session, registered_user)

    r = client.get(f"/api/v1/projects/{pid}/export/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 100


def test_tiptap_to_html_basic(db_session):
    """Tiptap JSON → HTML 转换正确（不依赖 weasyprint 系统库）。"""
    from app.services.pdf_service import _tiptap_to_html

    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "普通文本"},
                {"type": "text", "text": "加粗", "marks": [{"type": "bold"}]},
            ]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "列表项"}]}
                ]},
            ]},
        ],
    }
    html = _tiptap_to_html(db_session, doc)
    assert "<p>" in html
    assert "<strong>加粗</strong>" in html
    assert "<ul>" in html
    assert "<li>" in html
    assert "普通文本" in html


def test_tiptap_to_html_table(db_session):
    """表格节点转 HTML table。"""
    from app.services.pdf_service import _tiptap_to_html

    doc = {
        "type": "doc",
        "content": [
            {"type": "table", "content": [
                {"type": "tableRow", "content": [
                    {"type": "tableHeader", "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "表头"}]}
                    ]},
                    {"type": "tableCell", "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "单元格"}]}
                    ]},
                ]},
            ]},
        ],
    }
    html = _tiptap_to_html(db_session, doc)
    assert '<table class="data-table">' in html
    assert "<th>" in html
    assert "<td>" in html


def test_html_escape():
    """HTML 特殊字符转义。"""
    from app.services.pdf_service import _escape_html

    assert _escape_html("a<b>c&d") == "a&lt;b&gt;c&amp;d"
    assert _escape_html('"quote"') == "&quot;quote&quot;"
