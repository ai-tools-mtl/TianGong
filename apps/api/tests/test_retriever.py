"""retriever 逻辑测试（SQLite 跳过真实 Vector 列，只测业务逻辑）。"""
import uuid

from unittest.mock import patch

from app.rag.retriever import retrieve, RetrievalResult


def test_retriever_has_ef_search_set():
    """D1：retriever 查询前应 SET LOCAL hnsw.ef_search（HNSW 动态探测参数）。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert 'hnsw.ef_search' in src, "retrieve 缺少 SET LOCAL hnsw.ef_search"
    assert 'top_k' in src and 'ef_search' in src, "ef_search 应随 top_k 动态调整"


def test_retriever_adapts_halfvec():
    """D1.1：retriever 应将 query_vec 转 halfvec（列类型已改 halfvec）。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert 'halfvec' in src.lower() or 'HalfVec' in src, "retrieve 缺少 halfvec 适配（D1.1）"


def test_retriever_returns_empty_when_no_embed_config(db_session, registered_user):
    """无 embedding 配置时返回空列表（向后兼容）。"""
    # registered_user fixture 返回 str id；retrieve 内部 db.get(User, user_id)
    # 在 SQLite native UUID 列上需 UUID 对象，故转一下（仅测试侧）。
    # patch resolve_embedding_config 返回 None，模拟「无可用配置」分支——
    # 否则本机 env 里若有 embedding key 会走真实网络调用（不可重复）。
    with patch("app.rag.retriever.resolve_embedding_config", return_value=None):
        results = retrieve(
            db_session,
            user_id=uuid.UUID(registered_user["id"]),
            query="测试",
        )
    assert results == []


def test_database_has_is_postgres_helper():
    """core.database 应有 is_postgres() helper（G1/G3 SQLite 兼容判断）。"""
    from app.core import database
    assert hasattr(database, 'is_postgres'), "core.database 缺少 is_postgres()"
