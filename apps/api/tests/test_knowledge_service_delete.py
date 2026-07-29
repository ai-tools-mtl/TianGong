"""knowledge_service.delete_global_file 测试。"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.models import KnowledgeChunk, KnowledgeFile
from app.services import knowledge_service


@pytest.fixture(autouse=True)
def _mock_ingest(monkeypatch):
    """跳过 chunk 入库的 embedding 调用(SQLite 测试库不跑 pgvector)。"""
    monkeypatch.setattr(
        "app.services.knowledge_service._write_chunks_unembedded",
        lambda *args, **kwargs: [],
    )


def test_delete_global_file_removes_record_and_storage(db_session):
    """删 global 文件:KnowledgeFile 记录删 + minio 对象删 + 关联 chunk 删。"""
    storage = MagicMock()
    admin = MagicMock()
    admin.id = uuid.uuid4()

    kf = knowledge_service.upload_to_global(
        db_session, storage=storage, uploader=admin,
        filename="test.md", content=b"unique-delete-test-content",
        mime="text/markdown", text="正文内容" * 50,
    )
    chunk = KnowledgeChunk(
        user_id=admin.id, scope="global", file_id=kf.id,
        source_type="external_md", source_id=kf.id,
        chunk_index=0, content="正文内容" * 50,
    )
    db_session.add(chunk)
    db_session.commit()

    object_key = kf.object_key
    bucket = kf.bucket
    kf_id = kf.id

    knowledge_service.delete_global_file(db_session, storage=storage, file_id=str(kf_id))

    assert db_session.get(KnowledgeFile, kf_id) is None
    storage.delete.assert_called_once_with(bucket, object_key)
    remaining = db_session.query(KnowledgeChunk).filter_by(file_id=kf_id).all()
    assert len(remaining) == 0


def test_delete_global_file_404_on_missing(db_session):
    """删不存在的文件 → NotFoundError。"""
    from app.core.exceptions import NotFoundError
    storage = MagicMock()
    with pytest.raises(NotFoundError):
        knowledge_service.delete_global_file(
            db_session, storage=storage, file_id=str(uuid.uuid4()),
        )


def test_delete_global_file_refuses_personal(db_session):
    """拒绝删 personal 文件。"""
    from app.core.exceptions import ValidationError
    storage = MagicMock()
    user = MagicMock()
    user.id = uuid.uuid4()

    kf = knowledge_service.upload_external(
        db_session, storage=storage, user=user,
        filename="personal.md", content=b"personal-content",
        mime="text/markdown", text="text",
    )
    with pytest.raises(ValidationError):
        knowledge_service.delete_global_file(
            db_session, storage=storage, file_id=str(kf.id),
        )
