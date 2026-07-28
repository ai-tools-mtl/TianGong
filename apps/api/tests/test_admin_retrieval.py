"""G2 admin 检索测试端点测试。"""
import pytest
import uuid


@pytest.fixture
def admin_user(db_session):
    from app.models import User
    from app.core.security import hash_password
    u = User(
        username="admin",
        email="admin@tiangong.dev",
        password_hash=hash_password("Admin1234!"),
        name="管理员",
        role="admin",
    )
    db_session.add(u)
    db_session.commit()
    return {"id": str(u.id), "username": u.username, "password": "Admin1234!"}


@pytest.fixture
def fake_embed(monkeypatch):
    """固定零向量 embedding + 假 embed_config（避免 .env env-fallback 真实调 API）。

    retriever 用 `from app.rag.embedding import embed_text` 把名字绑定到本模块,
    故必须 patch `app.rag.retriever.embed_text`(retriever 实际引用的名字),
    而非 `app.rag.embedding.embed_text`(那只会改源模块,retriever 已持有的引用不变)。

    另需 patch `is_postgres` 返回 False:测试库是 SQLite,但模块级 engine 按
    .env 的 database_url 解析(本机指向 PG),不 patch 会触发 `SET LOCAL` 在
    SQLite 上报语法错。这是 is_postgres 检查模块级 engine 的已知限制,非本任务
    引入。
    """
    dim = 2048

    def _fake_text(text, embed_config=None):
        return [0.0] * dim

    monkeypatch.setattr("app.rag.retriever.embed_text", _fake_text)
    monkeypatch.setattr("app.rag.retriever.is_postgres", lambda: False)
    monkeypatch.setattr(
        "app.rag.retriever.resolve_embedding_config",
        lambda db, user_id: type("C", (), {"model": "m", "source": "global"})(),
    )


def test_admin_retrieval_test_requires_admin(client, registered_user):
    """非 admin 访问 /admin/knowledge/retrieval-test 返回 403。"""
    client.post(
        "/api/v1/auth/login",
        json={"username": registered_user["username"], "password": registered_user["password"]},
    )
    resp = client.post("/api/v1/admin/knowledge/retrieval-test", json={"query": "测试", "top_k": 5})
    assert resp.status_code == 403


def test_admin_retrieval_test_returns_structure(client, admin_user, fake_embed, monkeypatch):
    """admin 发起检索测试，返回结构含 results/threshold/top_k/scope。

    SQLite 测试库不支持 pgvector 的 cosine_distance / halfvec 序列化，
    故 stub `db.execute`：拦截 retrieve 构造的 stmt，去掉 distance 投影与
    pgvector 适配，仅按真实 scope_filter 跑一个等价 select（结构/契约测试
    不依赖具体召回内容）。
    """
    _intercept_retrieve_query(monkeypatch, db_session_ref={"db": None})

    client.post(
        "/api/v1/auth/login",
        json={"username": admin_user["username"], "password": admin_user["password"]},
    )
    resp = client.post(
        "/api/v1/admin/knowledge/retrieval-test",
        json={"query": "权利要求", "top_k": 5, "scope": "global"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "threshold" in data
    assert "top_k" in data
    assert "scope" in data
    assert isinstance(data["results"], list)


def test_admin_retrieval_test_scope_global_excludes_personal(
    client, admin_user, fake_embed, db_session, monkeypatch
):
    """scope=global 时只命中 global chunk（不命中 personal）。

    验证 retriever 的 scope_filter：scope=global 时 WHERE 只筛 global，
    personal chunk 不进结果集。SQLite 不支持 pgvector cosine_distance，
    故拦截 retrieve 的 stmt，复用其 whereclause 跑一个等价 select
    （distance 用常量 0.0 替代——所有 chunk 距离相同，仅 WHERE 决定命中集）。
    """
    from app.models import KnowledgeChunk

    # embedding=None：conftest 的兼容表把 embedding 当 JSON 存,但 ORM 模型列
    # 仍是 HalfVec 类型,pgvector 绑定器不接受 list。测试只验证 scope_filter,
    # 不关心向量(distance 被拦截器换成常量 0.0),故 None 即可。
    # source_id 必须是 UUID(模型列类型 Mapped[uuid.UUID]),传字符串会破坏
    # Uuid bind processor 的 .hex 调用。
    g = KnowledgeChunk(
        user_id=uuid.uuid4(), scope="global", source_type="external_docx",
        source_id=uuid.uuid4(), content="全局内容", embedding=None, metadata={"title": "g"},
    )
    p = KnowledgeChunk(
        user_id=uuid.uuid4(), scope="personal", source_type="external_docx",
        source_id=uuid.uuid4(), content="私人内容", embedding=None, metadata={"title": "p"},
    )
    db_session.add_all([g, p])
    db_session.commit()

    _intercept_retrieve_query(monkeypatch, db_session_ref={"db": db_session})

    client.post(
        "/api/v1/auth/login",
        json={"username": admin_user["username"], "password": admin_user["password"]},
    )
    resp = client.post(
        "/api/v1/admin/knowledge/retrieval-test",
        json={"query": "内容", "top_k": 10, "scope": "global"},
    )
    assert resp.status_code == 200
    contents = [r["content"] for r in resp.json()["results"]]
    assert "全局内容" in contents
    assert "私人内容" not in contents  # scope=global 不漏 personal


def _intercept_retrieve_query(monkeypatch, db_session_ref):
    """拦截 retrieve 内的 db.execute(stmt)：去掉 pgvector 投影，复用 scope_filter。

    retrieve 构造的 stmt 形如:
        select(KnowledgeChunk, cosine_distance(HalfVec(...)).label('distance'))
        .where(scope_filter).order_by('distance').limit(top_k)

    SQLite 无法执行 cosine_distance / 序列化 HalfVec。这里 wrap Session.execute:
    若传入 stmt 含 distance label,则改写为等价查询——保留 .whereclause / .limit /
    .order_by,把 cosine_distance 列换成常量 0.0（所有行距离相同，命中集完全由
    scope_filter 决定）。这样真实验证了 scope 过滤语义，又绕过 pgvector 方言。
    """
    from sqlalchemy import select, literal
    from sqlalchemy.orm import Session
    from app.models import KnowledgeChunk

    real_execute = Session.execute

    def _patched_execute(self, statement, *args, **kwargs):
        # 仅拦截 retrieve 发出的、含 'distance' 列的 select
        try:
            cols = statement.selected_columns
        except Exception:
            cols = None
        if cols is not None and any(getattr(c, "name", None) == "distance" for c in cols):
            db = db_session_ref.get("db") or self
            whereclause = statement.whereclause
            limit = statement._limit
            order = [literal(0.0).label("distance")]
            new_stmt = (
                select(KnowledgeChunk, *order)
                .where(whereclause)
                .order_by("distance")
            )
            if limit is not None:
                new_stmt = new_stmt.limit(limit)
            return real_execute(db, new_stmt, *args, **kwargs)
        return real_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", _patched_execute)
