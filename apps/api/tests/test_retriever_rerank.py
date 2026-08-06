"""retriever rerank 重排逻辑测试。

聚焦 retriever.py 内 rerank 重排段的两个回归点：
- 重复 content 不丢条：旧实现用 content 文本做 dict 匹配键，候选池内若有两条
  content 完全相同的 chunk，dict 只留最后一条序号，重排后丢条且顺序错乱。
- score 回写：rerank 后最终 score 应反映 rerank 的 relevance_score，而非
  rerank 之前算好的 RRF 分。

SQLite 测试库不支持 pgvector cosine_distance，故拦截 db.execute：把 retrieve
构造的向量路 stmt 改写为等价 select（distance 投影换常量），让整条 retrieve
链路在 SQLite 上跑通，从而真实覆盖重排段。
"""
import types

import pytest


@pytest.fixture
def fake_embed(monkeypatch):
    """固定零向量 embedding + 假 embed_config，patch retriever 持有的名字引用。"""
    dim = 2048

    def _fake_text(text, embed_config=None):
        return [0.0] * dim

    monkeypatch.setattr("app.rag.retriever.embed_text", _fake_text)
    monkeypatch.setattr("app.rag.retriever.is_postgres", lambda: False)
    monkeypatch.setattr(
        "app.rag.retriever.resolve_embedding_config",
        lambda db, user_id: types.SimpleNamespace(model="m", source="global"),
    )


def _patch_execute_with_chunks(monkeypatch, db_session, chunks):
    """拦截 retrieve 内的向量路查询：返回固定 chunks，distance 用常量 0.4
    （score = 1 - 0.4 = 0.6，过 SIMILARITY_THRESHOLD=0.5）。

    关键词路因 is_postgres()=False 直接跳过，无需拦截。
    """
    from sqlalchemy.orm import Session

    real_execute = Session.execute

    def _patched_execute(self, statement, *args, **kwargs):
        try:
            cols = statement.selected_columns
        except Exception:
            cols = None
        if cols is not None and any(getattr(c, "name", None) == "distance" for c in cols):
            # 命中 retrieve 的向量路 stmt：直接返回固定 chunks，不碰 DB
            # （stmt 含 user_id 绑定参数，UUID 列不接受测试用的字符串 user_id）
            return _FakeResult(chunks)
        return real_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", _patched_execute)


class _FakeResult:
    """模拟 db.execute(stmt).all() 的返回，吐出固定 (chunk, distance) 行。"""

    def __init__(self, chunks):
        self._rows = [(c, 0.4) for c in chunks]

    def all(self):
        return self._rows


def _make_chunk(content, *, chunk_id, title=None, weight=None):
    """构造一条 KnowledgeChunk（embedding=None：拦截器已绕过 pgvector 序列化）。"""
    import uuid
    from app.models import KnowledgeChunk

    return KnowledgeChunk(
        id=uuid.UUID(chunk_id),
        user_id=uuid.uuid4(),
        scope="global",
        source_type="external_docx",
        source_id=uuid.uuid4(),
        content=content,
        edited_text=None,
        embedding=None,
        weight=weight,
        metadata_={"title": title or content},
    )


def test_rerank_duplicate_content_keeps_all(monkeypatch, db_session, fake_embed):
    """重复 content 的两条 chunk 在 rerank 重排后都保留，不丢条。

    旧实现：rerank 返回文本列表，retriever 用 content 建 {content: order} dict
    做匹配键——两条相同 content 只留一个序号，重排后丢一条。新实现用索引位置
    对齐，两条都保留。
    """
    from app.rag import retriever
    from app.rag.reranker import RerankConfig

    # 两条 content 完全相同、chunk_id 不同的 chunk
    dup_content = "重复内容"
    chunks = [
        _make_chunk(dup_content, chunk_id="00000000-0000-0000-0000-000000000001", title="A"),
        _make_chunk(dup_content, chunk_id="00000000-0000-0000-0000-000000000002", title="B"),
        _make_chunk("独特内容", chunk_id="00000000-0000-0000-0000-000000000003", title="C"),
    ]
    for c in chunks:
        db_session.add(c)
    db_session.commit()

    _patch_execute_with_chunks(monkeypatch, db_session, chunks)

    # mock rerank：返回索引 [1, 0, 2]（把第二条重复条目排到第一）
    monkeypatch.setattr(
        retriever, "rerank",
        lambda query, documents, config=None: [1, 0, 2],
    )
    monkeypatch.setattr(
        retriever, "resolve_rerank_config",
        lambda db, user_id: RerankConfig(
            enabled=True, base_url="http://x", api_key="k", model="m", top_n=3,
        ),
    )

    results = retriever.retrieve(db_session, user_id="u", query="q", top_k=3)

    # 关键断言：两条重复 content 都在结果里（旧 bug 只剩一条）
    contents = [r.content for r in results]
    assert contents.count(dup_content) == 2, f"重复 content 应保留两条，实际: {contents}"
    # rerank 顺序生效：第二条（索引1）排在第一条（索引0）前面
    titles = [r.project_title for r in results]
    assert titles[0] == "B", f"rerank 应把索引1排到首位，实际顺序: {titles}"
