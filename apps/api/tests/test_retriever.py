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


def test_retriever_ef_search_no_param_binding():
    """SET LOCAL 不支持参数绑定（psycopg3 编译成 $1 会被 PG 拒绝 syntax error）。

    防回归：SET 语句必须用字面值（int() 后 f-string），不能用 :param / %(param)s。
    """
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    # 找到 SET LOCAL 那一行附近，确认是 f-string 字面拼接而非参数绑定
    set_line = [l for l in src.splitlines() if 'SET LOCAL hnsw.ef_search' in l]
    assert set_line, "缺少 SET LOCAL hnsw.ef_search 语句"
    # SET LOCAL 行不应包含参数绑定语法
    joined = " ".join(set_line)
    assert ":ef" not in joined and "%(ef)" not in joined, \
        "SET LOCAL 不能用参数绑定（psycopg3 会编译成 $1，PG 拒绝）；改用 int() 后 f-string"
    assert "int(" in src, "ef 应经 int() 强转后再拼接（防注入 + 保证是数字）"


def test_retriever_adapts_halfvec():
    """D1.1：retriever 向量检索应正确适配 halfvec 列。

    正确写法：cosine_distance(query_vec) 直接传 list，由 HALFVEC 类型的
    bind_processor（HalfVector._to_db）自动转。不能包 HalfVec(query_vec)——
    HALFVEC(dim) 期望维度整数，传 list 会让 get_col_spec 的 'HALFVEC(%d)' 炸掉。
    """
    import inspect
    from app.rag import retriever
    src = inspect.getsource(retriever.retrieve)
    assert "cosine_distance(query_vec)" in src, \
        "retrieve 应 cosine_distance(query_vec) 直接传 list（HALFVEC bind_processor 自动转 halfvec）"
    assert "HalfVec(query_vec)" not in src, \
        "不要包 HalfVec(query_vec)（HALFVEC 构造器期望 dim 整数，传 list 会 TypeError）"


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
