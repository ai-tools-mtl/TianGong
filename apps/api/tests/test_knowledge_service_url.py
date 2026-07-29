"""knowledge_service upload_* 函数的 url 参数测试。"""

import uuid
from unittest.mock import MagicMock, patch

from app.models import KnowledgeFile
from app.services import knowledge_service


def _mock_storage():
    storage = MagicMock()
    return storage


def _mock_user(uid=None):
    user = MagicMock()
    user.id = uid or uuid.uuid4()
    user.is_admin = False
    return user


@patch("app.services.knowledge_service._write_chunks_unembedded")
def test_upload_external_with_url(mock_ingest, db_session):
    """upload_external 的 url 参数被写入 KnowledgeFile.url。"""
    storage = _mock_storage()
    user = _mock_user()
    kf = knowledge_service.upload_external(
        db_session, storage=storage, user=user,
        filename="page.md", content="正文".encode() * 100,
        mime="text/markdown",
        url="https://example.com/page",
    )
    assert kf.url == "https://example.com/page"


@patch("app.services.knowledge_service._write_chunks_unembedded")
def test_upload_external_without_url(mock_ingest, db_session):
    """url 默认 None,不影响现有 docx/pdf 上传。"""
    storage = _mock_storage()
    user = _mock_user()
    kf = knowledge_service.upload_external(
        db_session, storage=storage, user=user,
        filename="doc.docx", content=b"content",
        mime="application/octet-stream",
    )
    assert kf.url is None


@patch("app.services.knowledge_service._write_chunks_unembedded")
def test_upload_to_global_with_url(mock_ingest, db_session):
    """upload_to_global 的 url 参数被写入。"""
    storage = _mock_storage()
    admin = _mock_user()
    admin.is_admin = True
    kf = knowledge_service.upload_to_global(
        db_session, storage=storage, uploader=admin,
        filename="page.md", content=b"unique-content-for-url-test-1",
        mime="text/markdown",
        url="https://example.com/global",
    )
    assert kf.url == "https://example.com/global"
