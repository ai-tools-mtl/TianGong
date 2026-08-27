# apps/api/tests/test_agent_store.py
"""CompositeAgentStore（红利③：Store 统一记忆）+ 热门记忆常驻测试。

sqlite 内存库直接建 user_memories 兼容表（conftest engine 已建），
记忆写路径 mock 掉 embedding（无推理服务）。
"""
import uuid
from datetime import datetime, timedelta, timezone


def _make_user(db_session):
    from app.core.security import hash_password
    from app.models import User

    u = User(
        username=f"test-{uuid.uuid4().hex[:8]}",
        email=f"test-{uuid.uuid4().hex[:8]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name="测试用户",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _no_embed(monkeypatch):
    from app.services import memory_service
    monkeypatch.setattr(memory_service, "_try_embed", lambda db, user_id, text: None)


def _seed_memory(db_session, user, content, *, hit_count=0, days_ago=0, last_hit_days_ago=None):
    from app.models import UserMemory

    now = datetime.now(timezone.utc)
    m = UserMemory(
        user_id=user.id, content=content, embedding=None,
        hit_count=hit_count,
        last_hit_at=(now - timedelta(days=last_hit_days_ago)) if last_hit_days_ago is not None else None,
        created_at=now - timedelta(days=days_ago),
        updated_at=now - timedelta(days=days_ago),
    )
    db_session.add(m)
    db_session.commit()
    return m


# ── CompositeAgentStore 路由 ──────────────────────────────────────────────────


def test_memory_namespace_put_get_roundtrip(db_session, monkeypatch):
    """("memories", uid) 命名空间 put → user_memories 落行；get 读回 content。"""
    from app.ai.store import CompositeAgentStore
    from app.models import UserMemory
    from app.skills.storage import MinIOSkillStore

    _no_embed(monkeypatch)
    user = _make_user(db_session)
    store = CompositeAgentStore(
        user_id=user.id, skill_store=MinIOSkillStore(bucket="global"), db=db_session)

    key = str(uuid.uuid4())
    store.put(("memories", str(user.id)), key, {"content": "偏好简洁的技术表述"})
    row = db_session.query(UserMemory).filter_by(id=uuid.UUID(key)).one()
    assert row.content == "偏好简洁的技术表述"

    item = store.get(("memories", str(user.id)), key)
    assert item is not None
    assert item.value["content"] == "偏好简洁的技术表述"


def test_memory_namespace_search_without_query_returns_hot(db_session, monkeypatch):
    """无 query 的 search → 热度 top-N 常驻视图（不回写命中计数）。"""
    from app.ai.store import CompositeAgentStore
    from app.skills.storage import MinIOSkillStore

    _no_embed(monkeypatch)
    user = _make_user(db_session)
    _seed_memory(db_session, user, "低频记忆", hit_count=0)
    _seed_memory(db_session, user, "高频偏好", hit_count=50, last_hit_days_ago=1)

    store = CompositeAgentStore(
        user_id=user.id, skill_store=MinIOSkillStore(bucket="global"), db=db_session)
    items = store.search(("memories", str(user.id)), limit=5)
    assert [i.value["content"] for i in items] == ["高频偏好", "低频记忆"]


def test_memory_namespace_delete(db_session, monkeypatch):
    _no_embed(monkeypatch)
    from app.ai.store import CompositeAgentStore
    from app.skills.storage import MinIOSkillStore

    user = _make_user(db_session)
    m = _seed_memory(db_session, user, "待删除")
    store = CompositeAgentStore(
        user_id=user.id, skill_store=MinIOSkillStore(bucket="global"), db=db_session)
    store.delete(("memories", str(user.id)), str(m.id))
    assert store.get(("memories", str(user.id)), str(m.id)) is None


def test_memory_get_rejects_other_user(db_session, monkeypatch):
    """跨用户 key 读取返回 None（Store 层归属校验）。"""
    _no_embed(monkeypatch)
    from app.ai.store import CompositeAgentStore
    from app.skills.storage import MinIOSkillStore

    owner = _make_user(db_session)
    other = _make_user(db_session)
    m = _seed_memory(db_session, owner, "别人的记忆")
    store = CompositeAgentStore(
        user_id=other.id, skill_store=MinIOSkillStore(bucket="global"), db=db_session)
    assert store.get(("memories", str(other.id)), str(m.id)) is None


def test_skill_namespace_passthrough(db_session, monkeypatch):
    """非 memories 命名空间原样透传 skill 存储（行为不变）。"""
    from app.ai.store import CompositeAgentStore

    put_calls: list = []

    class _FakeSkillStore:
        def batch(self, ops):
            put_calls.extend(o for o in ops)
            return [None] * len(list(ops))

    store = CompositeAgentStore(
        user_id=uuid.uuid4(), skill_store=_FakeSkillStore(), db=db_session)
    store.put(("skills", "global", "my-skill"), "SKILL.md", {"content": "x"})
    assert put_calls, "skills 命名空间应透传到 skill store"


def test_memory_ops_fail_open(db_session, monkeypatch):
    """memory 路径异常 fail-open：get → None、search → []，不抛出。"""
    from langgraph.store.base import GetOp, SearchOp

    from app.ai.store import CompositeAgentStore

    class _BoomSkillStore:
        def batch(self, ops):
            return [None] * len(list(ops))

    def _boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.services.memory_service.list_top_hot_memories", _boom)
    store = CompositeAgentStore(
        user_id=uuid.uuid4(), skill_store=_BoomSkillStore(), db=db_session)
    assert store.batch([GetOp(namespace=("memories", "u"), key="k")])[0] is None
    assert store.batch([SearchOp(namespace_prefix=("memories", "u"))])[0] == []


# ── list_top_hot_memories ─────────────────────────────────────────────────────


def test_list_top_hot_memories_orders_by_hot_and_excludes(db_session):
    """热度排序（hit_count × 30 天半衰）+ exclude_ids 去重。"""
    from app.services.memory_service import list_top_hot_memories

    user = _make_user(db_session)
    cold = _seed_memory(db_session, user, "冷记忆", hit_count=1, last_hit_days_ago=60)
    hot = _seed_memory(db_session, user, "热记忆", hit_count=20, last_hit_days_ago=1)
    _seed_memory(db_session, user, "中间", hit_count=5, last_hit_days_ago=5)

    top = list_top_hot_memories(db_session, user_id=user.id, limit=2)
    assert [m.content for m in top] == ["热记忆", "中间"]

    # exclude 命中的检索记忆：热记忆被排除后冷记忆补位
    top2 = list_top_hot_memories(db_session, user_id=user.id, limit=2, exclude_ids=[hot.id, cold.id])
    assert "热记忆" not in [m.content for m in top2]


# ── context_assembler 常驻注入 ────────────────────────────────────────────────


def test_hot_memories_injected_even_when_search_empty(db_session, monkeypatch):
    """检索无命中时，热门记忆仍常驻注入（两路互补的常驻路）。"""
    from app.ai.context_assembler import build_turn_reminder
    from app.models import Project, Section
    from app.services import memory_service

    user = _make_user(db_session)
    _seed_memory(db_session, user, "术语偏好用中文", hit_count=30, last_hit_days_ago=1)
    project = Project(title="测试项目", user_id=user.id)
    db_session.add(project)
    db_session.commit()
    section = Section(
        project_id=project.id, template_section_id="background",
        key="background", title="背景技术", order=1, content=None,
    )
    db_session.add(section)
    db_session.commit()

    monkeypatch.setattr(memory_service, "search_memories",
                        lambda db, *, user_id, query, top_k=5: [])
    # 批次 A：记忆属易变层，断言目标从静态 prompt 迁到逐轮快照
    reminder = build_turn_reminder(db_session, section)
    assert "关于这位用户的长期记忆" in reminder
    assert "术语偏好用中文" in reminder


def test_list_top_hot_memories_tie_breaks_by_id(db_session, monkeypatch):
    """同分热门记忆按 id 定序（批次 A prefix cache：防 DB 返回顺序抖动打碎快照稳定性）。"""
    from app.services import memory_service

    user = _make_user(db_session)
    a = _seed_memory(db_session, user, "同分甲", hit_count=0)
    b = _seed_memory(db_session, user, "同分乙", hit_count=0)

    # 热度分全部钉为 0——排序完全依赖二级键（id 定序），结果必须确定且跨查询一致
    monkeypatch.setattr(memory_service, "_compute_hot_score", lambda m, now: 0)
    first = [m.content for m in memory_service.list_top_hot_memories(db_session, user_id=user.id)]
    second = [m.content for m in memory_service.list_top_hot_memories(db_session, user_id=user.id)]
    expected = [m.content for m in sorted((a, b), key=lambda m: str(m.id))]
    assert first == expected
    assert second == expected
