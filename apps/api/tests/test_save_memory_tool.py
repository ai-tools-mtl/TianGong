"""save_memory 工具行为测试：新建 / 去重合并 / 空内容。"""
import asyncio
import uuid


def test_save_memory_new_content(db_session, registered_user, monkeypatch):
    """新内容创建新记忆。"""
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: None)

    tools = asyncio.run(create_agent_tools(db=db_session, user_id=uid))
    result = tools[1].invoke({"content": "偏好简洁风格"})

    assert "已保存" in result
    memories = ms.list_memories(db_session, user_id=uid)
    assert len(memories) == 1
    assert memories[0].content == "偏好简洁风格"
    assert memories[0].source == "agent"


def test_save_memory_dedup_merges(db_session, registered_user, monkeypatch):
    """相似内容合并而非新增（find_similar_memory 返回已有记忆）。"""
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms
    from app.models import UserMemory

    uid = uuid.UUID(registered_user["id"])
    # 预置一条已有记忆
    existing = UserMemory(user_id=uid, content="偏好简洁风格", embedding=None, source="agent")
    db_session.add(existing)
    db_session.commit()

    # mock find_similar_memory 返回已有记忆
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: existing)
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)

    tools = asyncio.run(create_agent_tools(db=db_session, user_id=uid))
    result = tools[1].invoke({"content": "偏好简洁，多用短句"})

    assert "已合并" in result
    # 不应新增，仍是 1 条，且内容已更新
    memories = ms.list_memories(db_session, user_id=uid)
    assert len(memories) == 1
    assert memories[0].content == "偏好简洁，多用短句"


def test_save_memory_empty_returns_unsaved(db_session, registered_user):
    """空内容返回未保存提示。"""
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    tools = asyncio.run(create_agent_tools(db=db_session, user_id=uid))
    result = tools[1].invoke({"content": "   "})

    assert "未保存" in result
    assert ms.list_memories(db_session, user_id=uid) == []


# ===== S2-3：画像记忆写入（spec 2026-07-29-prompt-content-design §4 S2-3）=====

def test_save_memory_profile_type_writes_profile_source(db_session, registered_user, monkeypatch):
    """[S2-3] memory_type=profile 时写入 source=profile（供画像检索用）。"""
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: None)

    tools = asyncio.run(create_agent_tools(db=db_session, user_id=uid))
    result = tools[1].invoke({
        "content": "用户是专利代理人，机械领域",
        "memory_type": "profile",
    })

    assert "已保存" in result
    # profile source 的记忆被写入
    profiles = ms.list_memories(db_session, user_id=uid, source="profile")
    assert len(profiles) == 1
    assert profiles[0].content == "用户是专利代理人，机械领域"
    assert profiles[0].source == "profile"


def test_save_memory_default_type_writes_agent_source(db_session, registered_user, monkeypatch):
    """[S2-3] 不传 memory_type 时默认 source=agent（向后兼容，偏好类记忆）。"""
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: None)

    tools = asyncio.run(create_agent_tools(db=db_session, user_id=uid))
    tools[1].invoke({"content": "偏好简洁风格"})  # 不传 memory_type

    # 默认走 agent source（偏好类），不是 profile
    assert ms.list_memories(db_session, user_id=uid, source="profile") == []
    assert len(ms.list_memories(db_session, user_id=uid, source="agent")) == 1


# ===== Task 5：矛盾覆盖纠错（spec §5 NLI 集成）=====
# 说明：测试库是 SQLite，user_memories.embedding 列是 JSON（无 pgvector 的
# cosine_distance 算子），真实 find_similar_memory 的 <=> 查询在 SQLite 下
# 语法不通。故沿用既有测试范式——直接桩 find_similar_memory 返回预置记忆，
# 让 NLI 判别分支（本 Task 的核心改动）成为唯一被测对象。

def test_save_memory_contradiction_replaces_old(db_session, registered_user, monkeypatch):
    """NLI 判矛盾 → 删旧写新（矛盾覆盖纠错）。"""
    from app.ai.tools import create_agent_tools
    from app.models import UserMemory
    import uuid as _uuid

    uid = _uuid.UUID(registered_user["id"])

    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [1.0] * 1024)

    # 预置一条旧记忆
    ms.create_memory(db_session, user_id=uid, content="偏好简洁风格")
    db_session.commit()
    old = db_session.query(UserMemory).filter_by(user_id=uid).one()

    # 命中去重（真实 cosine 算子在 SQLite 不可用 → 直接桩）
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: old)

    # NLI 判矛盾
    monkeypatch.setattr("app.ai.tools.judge_relation", lambda p, h: "contradiction")

    tools = asyncio.run(create_agent_tools(db_session, user_id=uid))
    save_mem = next(t for t in tools if t.name == "save_memory")
    result = save_mem.invoke({"content": "偏好详尽风格"})

    assert "替换" in result or "更新" in result
    contents = [m.content for m in db_session.query(UserMemory).filter_by(user_id=uid).all()]
    assert "偏好详尽风格" in contents
    assert "偏好简洁风格" not in contents  # 旧记忆被删


def test_save_memory_entailment_merges(db_session, registered_user, monkeypatch):
    """NLI 判蕴含 → 走原合并逻辑（v1.0 行为）。"""
    from app.ai.tools import create_agent_tools
    from app.models import UserMemory
    import uuid as _uuid

    uid = _uuid.UUID(registered_user["id"])
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [1.0] * 1024)

    ms.create_memory(db_session, user_id=uid, content="偏好简洁")
    db_session.commit()
    old = db_session.query(UserMemory).filter_by(user_id=uid).one()

    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: old)
    monkeypatch.setattr("app.ai.tools.judge_relation", lambda p, h: "entailment")

    tools = asyncio.run(create_agent_tools(db_session, user_id=uid))
    save_mem = next(t for t in tools if t.name == "save_memory")
    save_mem.invoke({"content": "我喜欢简短"})

    contents = [m.content for m in db_session.query(UserMemory).filter_by(user_id=uid).all()]
    assert contents == ["我喜欢简短"]  # 合并更新，条数不变


def test_save_memory_nli_down_falls_back_to_merge(db_session, registered_user, monkeypatch):
    """NLI 故障 → 走合并不删（降级安全阀）。"""
    from app.ai.tools import create_agent_tools
    from app.models import UserMemory
    import uuid as _uuid

    uid = _uuid.UUID(registered_user["id"])
    from app.services import memory_service as ms
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [1.0] * 1024)

    ms.create_memory(db_session, user_id=uid, content="偏好简洁")
    db_session.commit()
    old = db_session.query(UserMemory).filter_by(user_id=uid).one()

    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: old)

    # NLI 抛异常 → judge_relation 内部降级 neutral
    def _raise(*args, **kwargs):
        raise Exception("down")
    monkeypatch.setattr("app.rag.nli.httpx.post", _raise)

    tools = asyncio.run(create_agent_tools(db_session, user_id=uid))
    save_mem = next(t for t in tools if t.name == "save_memory")
    save_mem.invoke({"content": "偏好详尽"})

    contents = [m.content for m in db_session.query(UserMemory).filter_by(user_id=uid).all()]
    assert len(contents) == 1  # 合并未删
