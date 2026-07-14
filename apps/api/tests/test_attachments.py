"""附图附件测试。"""


def test_attachment_model_fields():
    """Attachment 实体有设计 3.2 定义的字段。"""
    from app.models.attachment import Attachment

    a = Attachment(
        project_id=None,
        section_id=None,
        filename="test.png",
        storage_path="uploads/abc.png",
        mime_type="image/png",
        size=1024,
    )
    assert a.filename == "test.png"
    assert a.storage_path == "uploads/abc.png"
    assert a.mime_type == "image/png"
    assert a.size == 1024
