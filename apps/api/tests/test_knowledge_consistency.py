"""知识库一致性修复的真实测试(P1-1)。

区别于 test_review_service(桩掉 chunk),这里让 chunk 写入/更新走真实路径
(conftest 的 knowledge_chunks 兼容版表),专门验证:
- 流 A 断链修复:归档上报后,project 的 disclosure chunk file_id 被关联,
  approve 能把它们升 global(之前 bug:file_id 永远 NULL,approve 改不到)
- 流 A 幂等:重复上报不重复生成 docx/工单
- 流 B approve 删旧 personal 对象:防 minio 存储泄漏
"""

import uuid

from sqlalchemy import select

import pytest

from app.core.security import hash_password
from app.models import KnowledgeChunk, KnowledgeFile, KnowledgeReview, User
from app.services import knowledge_service as ks
from app.services import knowledge_review_service as rs


@pytest.fixture
def fake_embed(monkeypatch):
    """只桩 embedding(返回固定向量,不调智谱)。chunk 读写走真实路径。

    注意:knowledge_service 顶部已 `from app.rag.embedding import embed_texts`,
    必须 patch knowledge_service 模块的引用,而非源模块(否则已绑定引用不更新)。
    """
    fake_vec = [0.0] * 2048
    monkeypatch.setattr(
        "app.services.knowledge_service.embed_texts",
        lambda texts: [fake_vec for _ in texts],
    )
    monkeypatch.setattr("app.rag.embedding.embed_text", lambda t: fake_vec)


@pytest.fixture
def normal_user(db_session, registered_user):
    return db_session.get(User, uuid.UUID(registered_user["id"]))


@pytest.fixture
def admin_user(db_session):
    u = User(
        email="admin@tiangong.dev",
        password_hash=hash_password("P1!"),
        name="admin", role="admin",
    )
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


def _make_project(db_session, user):
    """造一个归档状态的 project + 它的 disclosure chunk。"""
    from datetime import datetime, timezone

    from app.models import Project

    p = Project(user_id=user.id, title="测试交底书", status="archived")
    db_session.add(p); db_session.flush()

    # 造 2 个归档 chunk(scope=personal,source_id=project,file_id=NULL)
    for i in range(2):
        db_session.add(KnowledgeChunk(
            user_id=user.id, scope="personal", source_type="disclosure",
            source_id=p.id, source_section_key=f"sec-{i}", chunk_index=i,
            content=f"章节{i}内容", embedding=None, file_id=None,
        ))
    db_session.commit()
    return p


# ── 流 A 断链修复(最核心)──


def test_flow_a_submit_links_chunks_and_approve_promotes(
    db_session, normal_user, admin_user, fake_embed, _reset_storage
):
    """流 A:上报 → chunk file_id 被关联 → approve → chunk scope 升 global。

    这是 P1-1 最核心的回归:之前 file_id 永远 NULL,approve 改不到归档 chunk。
    """
    from app.core.storage import get_storage
    from unittest.mock import patch

    storage = get_storage()
    project = _make_project(db_session, normal_user)

    # 上报前:归档 chunk file_id 全是 NULL
    chunks_before = list(db_session.scalars(
        select(KnowledgeChunk).where((KnowledgeChunk.source_id == project.id) & (KnowledgeChunk.source_type == "disclosure"))
    ))
    assert all(c.file_id is None for c in chunks_before)
    assert all(c.scope == "personal" for c in chunks_before)

    # 桩 export_docx(避免依赖 Tiptap 渲染)
    with patch("app.services.export_service.export_docx", return_value=b"fake docx"):
        review = ks.submit_disclosure_for_review(
            db_session, storage=storage, submitter=normal_user, project=project,
        )

    # 断链修复:上报后,这些 chunk 的 file_id 应该被关联到新建的 kf
    chunks_after = list(db_session.scalars(
        select(KnowledgeChunk).where((KnowledgeChunk.source_id == project.id) & (KnowledgeChunk.source_type == "disclosure"))
    ))
    assert all(c.file_id == review.file_id for c in chunks_after), \
        "归档 chunk 应被关联到上报的 KnowledgeFile"
    # scope 仍是 personal(审核通过前)
    assert all(c.scope == "personal" for c in chunks_after)

    # approve
    rs.approve(db_session, storage=storage, reviewer=admin_user, review_id=str(review.id))

    # 关键断言:approve 后归档 chunk scope 升 global(之前 bug:仍是 personal)
    chunks_final = list(db_session.scalars(
        select(KnowledgeChunk).where((KnowledgeChunk.source_id == project.id) & (KnowledgeChunk.source_type == "disclosure"))
    ))
    assert len(chunks_final) == 2
    assert all(c.scope == "global" for c in chunks_final), \
        "approve 后归档 chunk 应升 global(这是断链修复的核心)"
    assert all(c.review_status == "approved" for c in chunks_final)


def test_flow_a_submit_idempotent(
    db_session, normal_user, fake_embed, _reset_storage
):
    """流 A 幂等:同一 project 重复上报不重复生成 docx/工单。"""
    from unittest.mock import patch

    storage = __import__("app.core.storage", fromlist=["get_storage"]).get_storage()
    project = _make_project(db_session, normal_user)

    call_count = {"n": 0}
    def counting_export(db, *, project):
        call_count["n"] += 1
        return b"docx"

    with patch("app.services.export_service.export_docx", side_effect=counting_export):
        r1 = ks.submit_disclosure_for_review(
            db_session, storage=storage, submitter=normal_user, project=project,
        )
        r2 = ks.submit_disclosure_for_review(
            db_session, storage=storage, submitter=normal_user, project=project,
        )

    assert r1.id == r2.id, "重复上报应返回同一工单"
    assert call_count["n"] == 1, "export_docx 只应被调一次(幂等)"


# ── 流 B approve 删旧 personal 对象(P1-1 存储泄漏)──


def test_flow_b_approve_deletes_old_personal_object(
    db_session, normal_user, admin_user, fake_embed, _reset_storage
):
    """流 B:approve 后旧 personal 对象应被删除(防 minio 存储泄漏)。"""
    from app.core.storage import get_storage

    storage = get_storage()
    # 上传个人素材(走真实 _ingest_chunks,写 chunk)
    kf = ks.upload_external(
        db_session, storage=storage, user=normal_user,
        filename="ref.docx", content=b"docx bytes",
        mime="application/docx", text="参考资料",
    )
    review = ks.submit_for_review(
        db_session, submitter_id=str(normal_user.id), file_id=str(kf.id),
    )
    personal_key = kf.object_key
    assert storage.stat("personal", personal_key) is True

    rs.approve(db_session, storage=storage, reviewer=admin_user, review_id=str(review.id))

    # 旧 personal 对象应被清理
    db_session.refresh(kf)
    assert storage.stat("personal", personal_key) is False, "旧 personal 对象应被删除"
    assert storage.stat("global", kf.object_key) is True, "新 global 对象应存在"
    assert kf.scope == "global"
    assert kf.bucket == "global"


def test_flow_b_approve_promotes_chunks_to_global(
    db_session, normal_user, admin_user, fake_embed, _reset_storage
):
    """流 B:approve 后关联的 chunk scope 升 global(走真实 _update_chunks_scope)。"""
    from app.core.storage import get_storage

    storage = get_storage()
    kf = ks.upload_external(
        db_session, storage=storage, user=normal_user,
        filename="ref.docx", content=b"docx",
        mime="application/docx", text="参考资料内容足够长",
    )
    # upload_external 已通过真实 _ingest_chunks 写了 chunk
    chunks = list(db_session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.file_id == kf.id)))
    assert len(chunks) >= 1
    assert all(c.scope == "personal" for c in chunks)

    review = ks.submit_for_review(
        db_session, submitter_id=str(normal_user.id), file_id=str(kf.id),
    )
    rs.approve(db_session, storage=storage, reviewer=admin_user, review_id=str(review.id))

    chunks_after = list(db_session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.file_id == kf.id)))
    assert all(c.scope == "global" for c in chunks_after)
    assert all(c.review_status == "approved" for c in chunks_after)
