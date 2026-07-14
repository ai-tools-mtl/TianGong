"""导出 image 节点渲染测试。"""


def test_tiptap_to_markdown_renders_image():
    from app.services.export_service import _tiptap_to_markdown

    doc_json = {"type": "doc", "content": [
        {"type": "image", "attrs": {"src": "/api/v1/x/file", "alt": "图 1 示意图"}}
    ]}
    md = _tiptap_to_markdown(doc_json)
    assert "![图 1 示意图](/api/v1/x/file)" in md


def test_render_tiptap_to_docx_handles_image(monkeypatch, tmp_path):
    from docx import Document
    from app.services import export_service

    # python-docx 的 add_picture 在 docx.document.Document 类上（docx.api.Document 是工厂函数）
    from docx.document import Document as DocClass

    called = {"add_picture": False}

    def fake_add_picture(self, *a, **kw):
        called["add_picture"] = True

    monkeypatch.setattr(DocClass, "add_picture", fake_add_picture)
    doc = Document()
    # 提供一个真实存在的本地路径，触发 add_picture 分支
    img_path = tmp_path / "local_path.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    doc_json = {"type": "doc", "content": [
        {"type": "image", "attrs": {"src": str(img_path), "alt": "图1"}}
    ]}
    export_service._render_tiptap_to_docx(doc, doc_json)
    assert called["add_picture"] is True
