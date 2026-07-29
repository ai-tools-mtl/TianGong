"""save_memory 工具行为测试：新建 / 去重合并 / 空内容。"""
import uuid


def test_save_memory_new_content(db_session, registered_user, monkeypatch):
    """新内容创建新记忆。"""
    from app.ai.tools import create_agent_tools
    from app.services import memory_service as ms

    uid = uuid.UUID(registered_user["id"])
    monkeypatch.setattr(ms, "_try_embed", lambda db, user_id, text: [0.1] * 2048)
    monkeypatch.setattr(ms, "find_similar_memory", lambda db, *, user_id, content: None)

    tools = create_agent_tools(db=db_session, user_id=uid)
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

    tools = create_agent_tools(db=db_session, user_id=uid)
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
    tools = create_agent_tools(db=db_session, user_id=uid)
    result = tools[1].invoke({"content": "   "})

    assert "未保存" in result
    assert ms.list_memories(db_session, user_id=uid) == []
