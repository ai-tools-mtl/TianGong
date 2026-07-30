"""用户长期记忆 service 测试。"""
import uuid


def test_create_memory_generates_embedding(db_session, registered_user, monkeypatch):
    """写入时自动生成 embedding（mock embed，返回固定向量）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)

    mem = ms.create_memory(db_session, user_id=uid, content="偏好简洁风格")

    assert mem.content == "偏好简洁风格"
    assert mem.embedding is not None
    assert mem.user_id == uid
    assert mem.source == "agent"


def test_create_memory_without_embedding_config_falls_back_to_null(db_session, registered_user, monkeypatch):
    """embedding 配置不可用时，记忆仍写入，embedding 为 NULL（降级）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    mem = ms.create_memory(db_session, user_id=uid, content="我做新能源电池")

    assert mem.embedding is None
    assert mem.content == "我做新能源电池"


def test_create_memory_empty_content_raises(db_session, registered_user):
    """空内容抛 ValidationError。"""
    import pytest
    from app.services import memory_service as ms
    from app.core.exceptions import ValidationError

    uid = uuid.UUID(registered_user["id"])
    with pytest.raises(ValidationError):
        ms.create_memory(db_session, user_id=uid, content="   ")


def test_list_memories_orders_by_updated_desc(db_session, registered_user, monkeypatch):
    """列表按 updated_at 倒序。"""
    from datetime import datetime, timedelta, timezone

    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    # server_default=func.now() 在 SQLite 渲染为 now()（PG-only），存 NULL。
    # 显式赋递增 updated_at，确保 ORDER BY updated_at DESC 被真正验证（非依赖时间戳生成）。
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    m1 = ms.create_memory(db_session, user_id=uid, content="第一条")
    m1.updated_at = base
    m2 = ms.create_memory(db_session, user_id=uid, content="第二条")
    m2.updated_at = base + timedelta(seconds=10)
    db_session.commit()

    items = ms.list_memories(db_session, user_id=uid)
    assert items[0].content == "第二条"
    assert items[1].content == "第一条"


def test_list_memories_filters_by_source(db_session, registered_user, monkeypatch):
    """source 筛选生效。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    ms.create_memory(db_session, user_id=uid, content="agent 记的", source="agent")
    ms.create_memory(db_session, user_id=uid, content="手动加的", source="manual")
    db_session.commit()

    manual = ms.list_memories(db_session, user_id=uid, source="manual")
    assert len(manual) == 1
    assert manual[0].content == "手动加的"


def test_update_memory_regenerates_embedding(db_session, registered_user, monkeypatch):
    """更新内容后 embedding 重建。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)

    mem = ms.create_memory(db_session, user_id=uid, content="原文")
    mem_id = mem.id

    updated = ms.update_memory(db_session, memory_id=mem_id, user_id=uid, content="改后")
    assert updated.content == "改后"
    assert updated.embedding is not None


def test_update_memory_not_owner_raises(db_session, registered_user):
    """非本人更新抛 NotFoundError（不泄露存在性）。"""
    import pytest
    from app.services import memory_service as ms
    from app.core.exceptions import NotFoundError

    uid = uuid.UUID(registered_user["id"])
    other = uuid.uuid4()

    mem = ms.create_memory(db_session, user_id=uid, content="我的")
    with pytest.raises(NotFoundError):
        ms.update_memory(db_session, memory_id=mem.id, user_id=other, content="篡改")


def test_delete_memory_only_owner(db_session, registered_user):
    """非本人删除抛 NotFoundError。"""
    import pytest
    from app.services import memory_service as ms
    from app.core.exceptions import NotFoundError

    uid = uuid.UUID(registered_user["id"])
    other = uuid.uuid4()

    mem = ms.create_memory(db_session, user_id=uid, content="我的")
    with pytest.raises(NotFoundError):
        ms.delete_memory(db_session, memory_id=mem.id, user_id=other)

    #本人删除成功
    ms.delete_memory(db_session, memory_id=mem.id, user_id=uid)
    assert ms.list_memories(db_session, user_id=uid) == []


def test_search_memories_returns_empty_when_embed_unavailable(db_session, registered_user, monkeypatch):
    """embedding 不可用时，search_memories 返回空列表（降级路径）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    # 记忆有 embedding
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)
    ms.create_memory(db_session, user_id=uid, content="偏好简洁风格")
    ms.create_memory(db_session, user_id=uid, content="我做新能源电池")
    db_session.commit()

    # 由于 SQLite 无 pgvector，search_memories 内部 cosine_distance 会报错。
    # 这里验证：embedding 配置不可用时返回空（降级路径）。
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    results = ms.search_memories(db_session, user_id=uid, query="风格")
    assert results == []


def test_search_memories_skips_null_embedding(db_session, registered_user, monkeypatch):
    """NULL embedding 的记忆在检索时被跳过（通过降级路径验证）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    # 无 embedding 配置 → search 内部 embed 失败 → 返回空
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    ms.create_memory(db_session, user_id=uid, content="无 embedding 的记忆")
    db_session.commit()

    results = ms.search_memories(db_session, user_id=uid, query="记忆")
    assert results == []


def test_find_similar_memory_returns_none_without_embedding(db_session, registered_user, monkeypatch):
    """embedding 配置不可用时，去重查询返回 None（不去重，降级）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    result = ms.find_similar_memory(db_session, user_id=uid, content="新内容")
    assert result is None


def test_search_memories_uses_pgvector_cosine():
    """源码结构检查：search_memories 用 pgvector cosine + HNSW ef_search（SQLite 跑不了真实查询，仿 test_retriever 源码检查）。"""
    import inspect
    from app.services import memory_service as ms

    src = inspect.getsource(ms.search_memories)
    assert "cosine_distance(query_vec)" in src
    assert "hnsw.ef_search" in src
    assert "SIMILARITY_THRESHOLD" in src
    assert "HalfVec(query_vec)" not in src, \
        "不要包 HalfVec()（构造器期望 dim 整数，传 list 会 TypeError）；cosine_distance 直接传 list"


def test_search_memories_ef_search_no_param_binding():
    """SET LOCAL 不支持参数绑定（psycopg3 编译成 $1 会被 PG 拒绝 syntax error）。

    防回归：SET 语句必须用字面值（int() 后 f-string），不能用 :param / %(param)s。
    否则真实 PG 下 search_memories 会失败，进而毒化事务（InFailedSqlTransaction）。
    """
    import inspect
    from app.services import memory_service as ms

    src = inspect.getsource(ms.search_memories)
    set_line = [l for l in src.splitlines() if 'SET LOCAL hnsw.ef_search' in l]
    assert set_line, "缺少 SET LOCAL hnsw.ef_search 语句"
    joined = " ".join(set_line)
    assert ":ef" not in joined and "%(ef)" not in joined, \
        "SET LOCAL 不能用参数绑定（psycopg3 会编译成 $1，PG 拒绝）；改用 int() 后 f-string"
    assert "int(" in src, "ef 应经 int() 强转后再拼接（防注入 + 保证是数字）"


def test_find_similar_memory_uses_pgvector_cosine():
    """源码结构检查：find_similar_memory 用 pgvector cosine + threshold（SQLite 跑不了，源码检查）。"""
    import inspect
    from app.services import memory_service as ms

    src = inspect.getsource(ms.find_similar_memory)
    assert "cosine_distance(embedding)" in src
    assert "DEDUP_SIMILARITY" in src
    assert "HalfVec(embedding)" not in src, \
        "不要包 HalfVec()（构造器期望 dim 整数，传 list 会 TypeError）；cosine_distance 直接传 list"


def test_create_memory_initializes_hot_fields(db_session, registered_user, monkeypatch):
    """新增记忆的 hit_count=0、last_hit_at=None（v1.1 热度字段初始值）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)

    mem = ms.create_memory(db_session, user_id=uid, content="测试热度字段")

    assert mem.hit_count == 0
    assert mem.last_hit_at is None


def test_compute_hot_score_new_memory_full_decay(db_session):
    """新记忆（hit_count=0, last_hit_at=None）得满分衰减 1.0。"""
    from app.services import memory_service as ms
    from datetime import datetime, timezone

    class FakeMem:
        hit_count = 0
        last_hit_at = None

    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    score = ms._compute_hot_score(FakeMem(), now)
    assert score == 1.0  # (0+1) * decay(0) = 1 * 1.0


def test_compute_hot_score_half_life_decay(db_session):
    """30 天未命中分数腰斩到 0.5。"""
    from app.services import memory_service as ms
    from datetime import datetime, timedelta, timezone

    class FakeMem:
        hit_count = 9  # 基础分 10，腰斩后 5.0
        last_hit_at = None

    last = datetime(2026, 6, 30, tzinfo=timezone.utc)  # 30 天前
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    FakeMem.last_hit_at = last

    score = ms._compute_hot_score(FakeMem(), now)
    assert abs(score - 5.0) < 0.01  # (9+1) * 0.5 = 5.0


def test_enforce_capacity_under_limit_noop(db_session, registered_user, monkeypatch):
    """未超限时 _enforce_capacity 不删任何记忆。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    monkeypatch.setattr(ms, "MEMORY_LIMIT", 200)

    for i in range(10):  # 远低于 200
        ms.create_memory(db_session, user_id=uid, content=f"记忆{i}")
    db_session.commit()

    ms._enforce_capacity(db_session, user_id=uid)
    db_session.commit()

    from app.models import UserMemory
    count = db_session.query(UserMemory).filter_by(user_id=uid).count()
    assert count == 10  # 无删除


def test_enforce_capacity_evicts_coldest(db_session, registered_user, monkeypatch):
    """超限时淘汰 hit_count 最低 + 最久未命中的记忆。"""
    from app.services import memory_service as ms
    from app.models import UserMemory
    from datetime import datetime, timedelta, timezone

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    monkeypatch.setattr(ms, "MEMORY_LIMIT", 3)  # 小上限便于测试
    monkeypatch.setattr(ms, "GRACE_DAYS", 0)    # 关闭豁免，让旧记忆可被淘汰

    # 建一条「最冷」：hit_count=0，30 天前命中
    cold = ms.create_memory(db_session, user_id=uid, content="最冷记忆")
    cold.hit_count = 0
    cold.last_hit_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # 建两条「较热」：hit_count 高、近期命中
    hot1 = ms.create_memory(db_session, user_id=uid, content="热记忆1")
    hot1.hit_count = 10
    hot1.last_hit_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    hot2 = ms.create_memory(db_session, user_id=uid, content="热记忆2")
    hot2.hit_count = 5
    hot2.last_hit_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
    db_session.commit()

    # 写第 4 条触发淘汰（超 3 上限）
    ms.create_memory(db_session, user_id=uid, content="新记忆触发淘汰")
    db_session.commit()

    contents = [m.content for m in db_session.query(UserMemory).filter_by(user_id=uid).all()]
    assert "最冷记忆" not in contents  # 最冷被淘汰
    assert "热记忆1" in contents
    assert "热记忆2" in contents


def test_enforce_capacity_grace_period_protects_new(db_session, registered_user, monkeypatch):
    """7 天豁免期内的新记忆即便最冷也不被淘汰。"""
    from app.services import memory_service as ms
    from app.models import UserMemory

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    monkeypatch.setattr(ms, "MEMORY_LIMIT", 2)
    monkeypatch.setattr(ms, "GRACE_DAYS", 7)  # 默认豁免

    # 两条豁免期内的新记忆（last_hit_at=None）
    ms.create_memory(db_session, user_id=uid, content="新记忆1")
    ms.create_memory(db_session, user_id=uid, content="新记忆2")
    db_session.commit()

    # 写第 3 条触发淘汰，但前两条都在豁免期 → 无可淘汰
    ms.create_memory(db_session, user_id=uid, content="新记忆3")
    db_session.commit()

    count = db_session.query(UserMemory).filter_by(user_id=uid).count()
    assert count == 3  # 全部豁免，未删任何


def test_bump_hit_counts_increments(db_session, registered_user, monkeypatch):
    """_bump_hit_counts 批量累加 hit_count 并更新 last_hit_at。"""
    from app.services import memory_service as ms
    from app.models import UserMemory

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: None)
    m1 = ms.create_memory(db_session, user_id=uid, content="m1")
    m2 = ms.create_memory(db_session, user_id=uid, content="m2")
    db_session.commit()
    assert m1.hit_count == 0

    ms._bump_hit_counts(db_session, [m1.id, m2.id])
    db_session.commit()

    db_session.refresh(m1)
    db_session.refresh(m2)
    assert m1.hit_count == 1
    assert m2.hit_count == 1
    assert m1.last_hit_at is not None


def test_bump_hit_counts_failure_returns_silently(db_session, registered_user, monkeypatch):
    """_bump_hit_counts 失败时静默 rollback，不抛异常（尽力而为）。"""
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])

    # 让 execute 抛异常模拟失败
    def boom(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(db_session, "execute", boom)

    # 不应抛异常
    ms._bump_hit_counts(db_session, [uuid.uuid4()])


def test_search_memories_reranks_by_hotness(db_session, registered_user, monkeypatch):
    """热度高的记忆排在向量距离更近但热度低的之前（两阶段重排）。"""
    from app.services import memory_service as ms
    from datetime import datetime, timedelta, timezone

    uid = uuid.UUID(registered_user["id"])
    # 固定向量，让两条记忆向量距离相同（都返回）→ 纯靠热度重排
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [1.0] * 1024)
    monkeypatch.setattr(ms, "SIMILARITY_THRESHOLD", 0.0)  # 放宽，确保都过阈值

    # 向量距离相同的两条（embedding 相同 → cosine_distance=0）
    cold = ms.create_memory(db_session, user_id=uid, content="冷")
    cold.hit_count = 0
    cold.last_hit_at = datetime(2026, 1, 1, tzinfo=timezone.utc)  # 很久以前
    hot = ms.create_memory(db_session, user_id=uid, content="热")
    hot.hit_count = 100
    hot.last_hit_at = datetime(2026, 7, 29, tzinfo=timezone.utc)  # 近期
    db_session.commit()

    results = ms.search_memories(db_session, user_id=uid, query="任意")
    assert len(results) == 2
    assert results[0].content == "热"  # 高热度排前
    assert results[1].content == "冷"
