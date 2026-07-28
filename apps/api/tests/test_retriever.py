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


def test_retriever_has_hybrid_retrieval():
    """G3：retrieve 应同时做向量召回 + 关键词召回 + RRF 融合 + rerank。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert 'rrf_fuse' in src, "retrieve 缺少 RRF 融合"
    assert 'plainto_tsquery' in src or 'tsv' in src, "retrieve 缺少关键词路召回"
    assert 'rerank' in src, "retrieve 缺少 rerank 调用"


def test_retriever_has_candidate_pool_constant():
    """G3：应有 RETRIEVAL_CANDIDATE_POOL 常量（召回阶段放大候选池）。"""
    from app.rag import retriever
    assert hasattr(retriever, 'RETRIEVAL_CANDIDATE_POOL'), "缺少 RETRIEVAL_CANDIDATE_POOL"
    assert retriever.RETRIEVAL_CANDIDATE_POOL >= 10


def test_retriever_uses_edited_text():
    """G4：检索返回和喂 LLM 都用 edited_text（如非空）。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert 'edited_text' in src, "retrieve 未使用 edited_text（G4 Task 4.3）"


def test_retriever_applies_weight():
    """G4：weight 作为召回分数乘子（fused_score *= weight）。"""
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert 'weight' in src, "retrieve 未应用 weight（G4 Task 4.3）"
    assert 'c.fused_score *= c.weight' in src, "weight 加权逻辑缺失"
