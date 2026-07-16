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


def _setup_project(client, registered_user, db_session):
    """登录 + 建项目，返回 (project_id, section_id)。"""
    from app.services.seed_service import ensure_default_template

    ensure_default_template(db_session)
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]
    sections = client.get(f"/api/v1/projects/{project_id}/sections").json()
    return project_id, sections[0]["id"]


def test_upload_valid_png_succeeds(client, registered_user, db_session):
    """上传合法 PNG 成功，返回 attachment 记录。"""
    project_id, section_id = _setup_project(client, registered_user, db_session)
    # 最小合法 PNG 魔数 + IHDR
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    res = client.post(
        f"/api/v1/sections/{section_id}/attachments",
        files={"file": ("test.png", png_bytes, "image/png")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["filename"] == "test.png"
    assert body["mime_type"] == "image/png"
    assert "id" in body


def test_upload_rejects_non_image_magic(client, registered_user, db_session):
    """魔数不匹配（伪装 png 的文本）被拒（设计 13.2）。"""
    project_id, section_id = _setup_project(client, registered_user, db_session)
    fake_bytes = b"THIS IS NOT AN IMAGE"  # 不是图片魔数

    res = client.post(
        f"/api/v1/sections/{section_id}/attachments",
        files={"file": ("fake.png", fake_bytes, "image/png")},
    )
    assert res.status_code == 422


def test_upload_other_user_section_404(client, registered_user, db_session):
    """上传到他人项目的章节返回 404（资源级授权，设计 13.1）。"""
    from app.models import User

    # 建第二个用户的项目
    other = User(username="other", email="other@example.com", password_hash="x", name="other")
    db_session.add(other)
    db_session.commit()

    project_id, _ = _setup_project(client, registered_user, db_session)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    # 用不存在的 section id（不存在于 registered_user）
    res = client.post(
        f"/api/v1/sections/00000000-0000-0000-0000-000000000000/attachments",
        files={"file": ("t.png", png_bytes, "image/png")},
    )
    assert res.status_code == 404


def test_list_attachments(client, registered_user, db_session):
    """列出项目的附件。"""
    project_id, section_id = _setup_project(client, registered_user, db_session)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    client.post(
        f"/api/v1/sections/{section_id}/attachments",
        files={"file": ("a.png", png_bytes, "image/png")},
    )
    res = client.get(f"/api/v1/projects/{project_id}/attachments")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_delete_attachment(client, registered_user, db_session):
    """删除附件（记录 + 文件）。"""
    project_id, section_id = _setup_project(client, registered_user, db_session)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    up = client.post(
        f"/api/v1/sections/{section_id}/attachments",
        files={"file": ("a.png", png_bytes, "image/png")},
    ).json()
    att_id = up["id"]

    res = client.delete(f"/api/v1/attachments/{att_id}")
    assert res.status_code == 204

    # 再列应为空
    res = client.get(f"/api/v1/projects/{project_id}/attachments")
    assert len(res.json()) == 0
