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
    from app.services import memory_service as ms
    from app.core.exceptions import ValidationError

    uid = uuid.UUID(registered_user["id"])
    try:
        ms.create_memory(db_session, user_id=uid, content="   ")
        assert False, "应抛 ValidationError"
    except ValidationError:
        pass


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
    from app.services import memory_service as ms
    from app.core.exceptions import NotFoundError

    uid = uuid.UUID(registered_user["id"])
    other = uuid.uuid4()

    mem = ms.create_memory(db_session, user_id=uid, content="我的")
    try:
        ms.update_memory(db_session, memory_id=mem.id, user_id=other, content="篡改")
        assert False, "应抛 NotFoundError"
    except NotFoundError:
        pass


def test_delete_memory_only_owner(db_session, registered_user):
    """非本人删除抛 NotFoundError。"""
    from app.services import memory_service as ms
    from app.core.exceptions import NotFoundError

    uid = uuid.UUID(registered_user["id"])
    other = uuid.uuid4()

    mem = ms.create_memory(db_session, user_id=uid, content="我的")
    try:
        ms.delete_memory(db_session, memory_id=mem.id, user_id=other)
        assert False, "应抛 NotFoundError"
    except NotFoundError:
        pass

    #本人删除成功
    ms.delete_memory(db_session, memory_id=mem.id, user_id=uid)
    assert ms.list_memories(db_session, user_id=uid) == []
