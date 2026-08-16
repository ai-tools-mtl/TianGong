# apps/api/app/ai/store.py
"""复合 LangGraph BaseStore：按 namespace 路由到 skill 存储 / 用户记忆。

「Store 统一记忆」（设计 v1.3 附录 A 红利③）的落地形态：
- `("memories", <user_id>, ...)` 命名空间 → user_memories 表（经 memory_service），
  user_memories 保持唯一真源（热度淘汰/NLI 去重/embedding 检索全保留）；
- 其余命名空间（("skills", ...) 等）→ MinIOSkillStore 原样透传，行为不变。

这样 agent 的任何 LangGraph 原生组件（中间件 / 子代理 / MCP 工具 / 未来的
ReviewGraph）都能经标准 BaseStore API 读写用户记忆，而不必各自直连 DB 服务。

db 会话：复用 build_agent 的请求级 session（与 create_agent_tools 的闭包 db 同源，
生命周期 = 单次 agent 运行）。所有 memory 路径操作 fail-open——异常记日志返回
空/None，绝不阻断 agent loop（记忆是增强，不是依赖）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

from app.skills.storage import MinIOSkillStore

logger = logging.getLogger("tiangong.ai")

MEMORIES_ROOT = "memories"


def _to_api_ts(dt: datetime | None) -> datetime:
    """ORM 时间戳 → Item 时间字段（None 兜底 now）。"""
    return dt or datetime.now(timezone.utc)


class CompositeAgentStore(BaseStore):
    """namespace 路由的复合 Store：memories → user_memories 表；其余 → skill 存储。

    实现 batch/abatch（BaseStore 真正的抽象方法）+ 覆写单项方法以走 memory_service
    的完整链路（embedding / 热度 / 容量淘汰）。async 单项由 BaseStore 默认实现
    转发到 abatch（同 MinIOSkillStore 的做法，勿把 async 方法写成同步 def——
    历史坑见 skills/storage.py docstring）。
    """

    def __init__(self, *, user_id, skill_store: MinIOSkillStore, db):
        # DB 路径一律用 UUID 对象（UserMemory 的 id/user_id 列是 Uuid 类型，
        # 绑定 str 会炸 'str' object has no attribute 'hex'）；namespace 段仍是 str。
        import uuid as _uuid

        self._user_id = _uuid.UUID(str(user_id))
        self._skill_store = skill_store
        self._db = db

    @staticmethod
    def _as_uuid(key: str):
        """Store key(str) → UUID。非 UUID 形态的 key 在 memory 表无对应行 → None。"""
        import uuid as _uuid

        try:
            return _uuid.UUID(str(key))
        except (ValueError, AttributeError, TypeError):
            return None

    # ---- 路由 -------------------------------------------------------------

    @staticmethod
    def _is_memory_ns(namespace: tuple[str, ...]) -> bool:
        return bool(namespace) and namespace[0] == MEMORIES_ROOT

    def _mem_ns(self, namespace: tuple[str, ...]) -> tuple[str, ...]:
        """归一化 memory 命名空间：去掉 "memories" 根，保留 (user_id, ...)。"""
        return tuple(namespace[1:]) or (self._user_id,)

    # ---- memory 路径单项操作（fail-open） --------------------------------

    def _mem_put(self, namespace, key, value) -> None:
        from app.models import UserMemory
        from app.services import memory_service

        content = (value or {}).get("content") if isinstance(value, dict) else value
        if not isinstance(content, str) or not content.strip():
            raise ValueError("memories 命名空间的 value 必须含非空 content")
        row_id = self._as_uuid(key)
        if row_id is None:
            raise ValueError(f"memories 命名空间的 key 必须是 UUID，收到: {key!r}")
        mem = self._db.get(UserMemory, row_id)
        if mem is not None and mem.user_id == self._user_id:
            memory_service.update_memory(
                self._db, memory_id=row_id, user_id=self._user_id, content=content)
        else:
            # Store key 语义 = 行主键：显式传 id 建行（create_memory 不接受外部 id，
            # 这里直接构造 ORM 以保 key 语义；embedding / 容量淘汰逻辑抽出来复用）。
            embedding = memory_service._try_embed(self._db, self._user_id, content)  # noqa: SLF001
            row = UserMemory(
                id=row_id, user_id=self._user_id,
                content=content.strip(), embedding=embedding,
            )
            self._db.add(row)
            self._db.flush()
            memory_service._enforce_capacity(self._db, user_id=self._user_id)  # noqa: SLF001

    def _mem_get(self, namespace, key) -> Item | None:
        from app.models import UserMemory

        row_id = self._as_uuid(key)
        if row_id is None:
            return None
        mem = self._db.get(UserMemory, row_id)
        if mem is None or mem.user_id != self._user_id:
            return None
        return Item(
            value={"content": mem.content},
            key=str(mem.id),
            namespace=tuple(namespace),
            created_at=_to_api_ts(mem.created_at),
            updated_at=_to_api_ts(mem.updated_at),
        )

    def _mem_search(self, namespace_prefix, *, query=None, limit=10, offset=0) -> list[SearchItem]:
        from app.services import memory_service

        now = datetime.now(timezone.utc)
        ns = tuple(namespace_prefix)
        if query:
            hits = memory_service.search_memories(
                self._db, user_id=self._user_id, query=str(query),
                top_k=limit + offset,
            )
            rows = [
                SearchItem(value={"content": h.content}, key=str(h.id), namespace=ns,
                           created_at=now, updated_at=now)
                for h in hits
            ]
        else:
            # 无 query：热度 top-N 常驻视图（不回写命中计数——常驻不该刷热度）
            mems = memory_service.list_top_hot_memories(
                self._db, user_id=self._user_id, limit=limit + offset)
            rows = [
                SearchItem(value={"content": m.content}, key=str(m.id), namespace=ns,
                           created_at=_to_api_ts(m.created_at), updated_at=_to_api_ts(m.updated_at))
                for m in mems
            ]
        return rows[offset:offset + limit]

    def _mem_delete(self, namespace, key) -> None:
        from app.services import memory_service

        row_id = self._as_uuid(key)
        if row_id is None:
            return
        memory_service.delete_memory(self._db, memory_id=row_id, user_id=self._user_id)

    # ---- 批处理（BaseStore 抽象方法；memory 路径 fail-open） --------------

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        results: list[Result] = []
        for op in ops:
            if isinstance(op, PutOp) and self._is_memory_ns(op.namespace):
                if op.value is None:
                    results.append(self._memory_guard(
                        lambda: self._mem_delete(op.namespace, op.key)))
                else:
                    results.append(self._memory_guard(
                        lambda: self._mem_put(op.namespace, op.key, op.value)))
            elif isinstance(op, GetOp) and self._is_memory_ns(op.namespace):
                results.append(self._memory_guard(
                    lambda: self._mem_get(op.namespace, op.key)))
            elif isinstance(op, SearchOp) and self._is_memory_ns(op.namespace_prefix):
                results.append(self._memory_guard(
                    lambda: self._mem_search(
                        op.namespace_prefix, query=op.query,
                        limit=op.limit, offset=op.offset),
                    empty=[]))
            else:
                # skills / files / 未来其它命名空间：透传 skill 存储，异常不吞
                #（保持 MinIOSkillStore 原行为——skill 加载失败应如实上抛）
                results.append(self._skill_store.batch([op])[0])
        return results

    def _memory_guard(self, fn, *, empty=None):
        """执行 memory 路径操作，异常 fail-open（Get→None / Search→[] / Put→None）。"""
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — memory 是增强不是依赖，绝不阻断 agent loop
            logger.warning("CompositeAgentStore memory op 失败（fail-open）: %s", e)
            return empty

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        return self.batch(ops)
