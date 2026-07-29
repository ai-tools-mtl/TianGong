"""确认内部 caller 调用了正确的 resolve 函数（chat caller → resolve_chat_config）。"""

from unittest.mock import patch, MagicMock


def test_review_service_calls_resolve_chat_config(db_session):
    """review_service.run_review 应调 resolve_chat_config（不是 resolve_llm_config）。"""
    from app.services import review_service
    fake_cfg = MagicMock()
    fake_cfg.model = "glm-4"
    with patch("app.services.review_service.resolve_chat_config", return_value=fake_cfg) as m, \
         patch("app.services.review_service.get_llm") as m_llm, \
         patch("app.services.review_service.get_effective_rubric"), \
         patch("app.services.review_service._get_section_texts", return_value={}), \
         patch("app.services.review_service._get_last_review"):
        m_llm.return_value.invoke.return_value = MagicMock(content='{"score":5,"reason":"r","evidence":"e"}')
        from app.models import User, Project
        import uuid
        u = User(username="rv", password_hash="x", name="R")
        db_session.add(u); db_session.commit(); db_session.refresh(u)
        p = Project(id=uuid.uuid4(), user_id=u.id, title="t")
        db_session.add(p); db_session.commit()
        try:
            review_service.run_review(db_session, user_id=u.id, project_id=str(p.id))
        except Exception:
            pass  # 只关心 resolve 被调对
    m.assert_called()


def test_summary_service_calls_resolve_chat_config(db_session):
    """summary_service.generate_summary 应调 resolve_chat_config（不是 resolve_llm_config）。

    注意：
    - content 必须是 Tiptap dict 且含 text 节点，否则 _extract_text 返回空串、
      在 reach resolve 之前就 early return，测不到 resolve 调用。
    - summary_service 把 resolve_chat_config 放在函数内惰性 import（try 块），
      非模块级属性，故 patch 其源模块。
    """
    from app.services import summary_service
    from app.models import Section, Project
    import uuid
    fake_cfg = MagicMock()
    with patch("app.services.llm_config_service.resolve_chat_config", return_value=fake_cfg) as m:
        u_proj = Project(id=uuid.uuid4(), user_id=uuid.uuid4(), title="t")
        db_session.add(u_proj); db_session.commit()
        s = Section(
            id=uuid.uuid4(),
            project_id=u_proj.id,
            template_section_id="ts-1",
            order=1,
            key="k",
            title="t",
            # Tiptap doc：含 text 节点，_extract_text 才能提取出非空文本
            content={"type": "doc", "content": [{"type": "text", "text": "内容"}]},
        )
        db_session.add(s); db_session.commit()
        # generate_summary 内部 get_llm(fake_cfg) 可能抛错，但被其 except 吞掉走降级；
        # 本测试只关心 resolve_chat_config 被调到，不在乎最终摘要。
        summary_service.generate_summary(db_session, s)
    m.assert_called()


def test_archiver_calls_resolve_embedding_config():
    """异步化后 run_archive_embed_standalone（而非 archive_project）调 resolve_embedding_config。

    archive_project 只落库不 embed；向量化在 standalone 后台任务，它解析配置。
    """
    import inspect
    from app.rag import archiver

    # archive_project 不再调 resolve_embedding_config（异步化）
    archive_src = inspect.getsource(archiver.archive_project)
    assert "resolve_embedding_config" not in archive_src, (
        "archive_project 异步化后不应调 resolve_embedding_config"
    )
    # run_archive_embed_standalone 调 resolve_embedding_config
    standalone_src = inspect.getsource(archiver.run_archive_embed_standalone)
    assert "resolve_embedding_config" in standalone_src, (
        "run_archive_embed_standalone 应调 resolve_embedding_config"
    )


def test_retriever_calls_resolve_embedding_config(db_session):
    from app.rag import retriever
    with patch("app.rag.retriever.resolve_embedding_config", return_value=None) as m:
        retriever.retrieve(db_session, user_id="00000000-0000-0000-0000-000000000000", query="q")
    m.assert_called()

