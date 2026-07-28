"""G4 chunk 编辑端点测试。"""
import pytest
import uuid


@pytest.fixture
def admin_user(db_session):
    from app.models import User
    from app.core.security import hash_password
    u = User(username="admin", email="admin@tiangong.dev",
             password_hash=hash_password("Admin1234!"), name="管理员", role="admin")
    db_session.add(u)
    db_session.commit()
    return {"id": str(u.id), "username": u.username, "password": "Admin1234!"}


@pytest.fixture
def sample_file_and_chunk(db_session, admin_user):
    """构造一个 KnowledgeFile + 一个 chunk（source_id 指向 file_id）。"""
    from app.models import KnowledgeFile, KnowledgeChunk
    from app.core import storage
    f = KnowledgeFile(
        uploader_id=uuid.UUID(admin_user["id"]),
        scope="global",
        bucket="global",
        object_key="global/test.docx",
        filename="测试文件.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=len(b"fake"),
        source_type="external_docx",
        content_hash="sha256-test-" + uuid.uuid4().hex[:20],
    )
    db_session.add(f)
    db_session.commit()
    # 塞一点字节到 fake storage（download 时需要，list 不需要，但保险起见）
    storage.get_storage().put("global", "test.docx", b"fake", "application/octet-stream")
    c = KnowledgeChunk(
        user_id=uuid.UUID(admin_user["id"]), scope="global",
        source_type="external_docx", source_id=f.id, chunk_index=0,
        content="原始 chunk 内容", embedding=[0.0]*2048, metadata_={"title": "测试"},
    )
    db_session.add(c)
    db_session.commit()
    return f, c


def test_list_chunks_requires_admin(client, registered_user):
    """非 admin 访问返回 403。"""
    client.post("/api/v1/auth/login", json={"username": registered_user["username"], "password": registered_user["password"]})
    resp = client.get("/api/v1/admin/knowledge/files/00000000-0000-0000-0000-000000000000/chunks")
    assert resp.status_code == 403


def test_list_chunks_returns_list(client, admin_user, sample_file_and_chunk):
    """admin 列出 chunks。"""
    f, c = sample_file_and_chunk
    client.post("/api/v1/auth/login", json={"username": admin_user["username"], "password": admin_user["password"]})
    resp = client.get(f"/api/v1/admin/knowledge/files/{f.id}/chunks")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "content" in data[0]
    assert "keywords" in data[0]
    assert "weight" in data[0]
    assert "edited_text" in data[0]
    assert "locked" in data[0]


def test_update_chunk_edits_fields(client, admin_user, sample_file_and_chunk, monkeypatch):
    """admin 编辑 keywords/questions/weight。

    mock is_postgres=False 避免 tsv 在 SQLite 跑 to_tsvector 报错（is_postgres
    判全局 engine，环境 DATABASE_URL 指向 PG 时测试仍会走 PG 分支）。
    """
    f, c = sample_file_and_chunk
    monkeypatch.setattr("app.services.knowledge_service.is_postgres", lambda: False)
    client.post("/api/v1/auth/login", json={"username": admin_user["username"], "password": admin_user["password"]})
    resp = client.patch(f"/api/v1/admin/knowledge/chunks/{c.id}", json={
        "keywords": ["权利要求1", "技术特征"],
        "questions": ["什么是技术特征?"],
        "weight": 1.5,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["keywords"] == ["权利要求1", "技术特征"]
    assert data["questions"] == ["什么是技术特征?"]
    assert data["weight"] == 1.5


def test_update_chunk_edited_text_triggers_reembed(client, admin_user, sample_file_and_chunk, monkeypatch):
    """edited_text 变更应触发重新 embed（D8）。"""
    f, c = sample_file_and_chunk
    reembed_called = []
    # mock embed_texts 记录调用（不真实调）
    monkeypatch.setattr("app.services.knowledge_service.embed_texts",
                        lambda texts, embed_config=None: (reembed_called.append(texts), [[0.1]*2048 for _ in texts])[1])
    # mock resolve_embedding_config 返回假配置（避免 None 早退）
    monkeypatch.setattr("app.services.knowledge_service.resolve_embedding_config",
                        lambda db, user_id: __import__("types").SimpleNamespace(model="m", source="global"))
    # mock is_postgres 避免 tsv 在 SQLite 报错
    monkeypatch.setattr("app.services.knowledge_service.is_postgres", lambda: False)

    client.post("/api/v1/auth/login", json={"username": admin_user["username"], "password": admin_user["password"]})
    resp = client.patch(f"/api/v1/admin/knowledge/chunks/{c.id}", json={"edited_text": "编辑后的内容"})
    assert resp.status_code == 200
    assert len(reembed_called) > 0  # 触发了 reembed


def test_update_locked_chunk_rejects(client, admin_user, sample_file_and_chunk, db_session, monkeypatch):
    """locked chunk 不允许编辑 edited_text（除非 force_unlock）。

    mock is_postgres=False 避免 tsv 报错；mock resolve_embedding_config 返回 None
    避免 force_unlock 那次 edited_text 变更真调 openai embed。
    """
    f, c = sample_file_and_chunk
    monkeypatch.setattr("app.services.knowledge_service.is_postgres", lambda: False)
    monkeypatch.setattr("app.services.knowledge_service.resolve_embedding_config",
                        lambda db, user_id: None)
    c.locked = True
    db_session.commit()
    client.post("/api/v1/auth/login", json={"username": admin_user["username"], "password": admin_user["password"]})
    # 不带 force_unlock，应 409
    resp = client.patch(f"/api/v1/admin/knowledge/chunks/{c.id}", json={"edited_text": "尝试改"})
    assert resp.status_code == 409
    # 带 force_unlock，应 200
    resp2 = client.patch(f"/api/v1/admin/knowledge/chunks/{c.id}", json={"edited_text": "强制改", "force_unlock": True})
    assert resp2.status_code == 200


def test_update_chunk_nonexistent_returns_404(client, admin_user):
    """不存在的 chunk_id 返回 404。"""
    client.post("/api/v1/auth/login", json={"username": admin_user["username"], "password": admin_user["password"]})
    resp = client.patch("/api/v1/admin/knowledge/chunks/00000000-0000-0000-0000-000000000000", json={"weight": 2.0})
    assert resp.status_code == 404
