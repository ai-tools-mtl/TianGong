# apps/api/app/skills/storage.py
"""MinIO-backed LangGraph BaseStore 适配器。

deepagents 的 StoreBackend 包装本实现，SkillsMiddleware 通过它加载 skill。
namespace tuple 映射到 MinIO 对象 key：("skills","global","my-skill") + "SKILL.md"
→ "skills/global/my-skill/SKILL.md"。

复用 app/core/storage.py 的 MinioStorage（已验证），不重复造存储轮子。
"""
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

from app.core import storage as _storage_mod


def namespace_to_minio_key(namespace: tuple[str, ...], key: str) -> str:
    """namespace tuple + 文件名 → MinIO 对象 key。"""
    return "/".join((*namespace, key))


class MinIOSkillStore(BaseStore):
    """把 skill 文件存到 MinIO 的 BaseStore 实现。

    每个 (namespace, key) = MinIO 里的一个对象。value dict 序列化为 JSON bytes。
    bucket 别名传 'global' / 'personal'（由 Settings 映射）。

    BaseStore 的抽象方法是 batch/abatch（接受 GetOp/PutOp/SearchOp/ListNamespacesOp），
    单项的同步 put/get/search/delete/list_namespaces 由 BaseStore 默认实现转发到 batch；
    单项的 async aget/aput/asearch/adelete 同样由 BaseStore 默认实现转发到 abatch。
    本类只显式实现同步单项方法 + batch/abatch（+ alist_namespaces 直测），
    async 路径全部委托 BaseStore 默认实现。

    历史坑：曾把 aget/aput/asearch/adelete 重写成同步 def（假冒 async），
    导致 deepagents StoreBackend.awrite 执行 `await store.aget(...)` 时
    await 了普通返回值 → 'NoneType' object can't be awaited。删除重写后，
    async 路径走 BaseStore 默认实现 → abatch（真 async def）→ batch，正常。
    """

    def __init__(self, *, bucket: str = "global"):
        self._bucket_alias = bucket

    # ---- 存储访问 / 序列化 ----------------------------------------------

    def _storage(self):
        # 通过模块属性取单例，不绑定函数引用本身——
        # 这样测试 monkeypatch storage.get_storage 才能注入假实现。
        return _storage_mod.get_storage()

    def _serialize(self, value: dict[str, Any]) -> bytes:
        return json.dumps(value, ensure_ascii=False).encode("utf-8")

    def _deserialize(self, raw: bytes) -> dict[str, Any]:
        """反序列化 MinIO 对象值 → dict。

        skill 目录下同时存在两种对象：
        - JSON 元数据（通过 store.put 写入的 value dict → json.dumps）
        - 原始文本文件（SKILL.md / scripts / references 通过 skill_service
          直接 st.put(..., "text/plain") 写入，非 JSON）

        对 JSON 解析失败的对象：降级包装为 {"content": <原文>} 返回，
        不阻断 search() 列举（SkillsMiddleware 需遍历所有文件）。
        """
        if not raw:
            return {}
        text = raw.decode("utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 非 JSON 文件（SKILL.md / 脚本等）：包装原文
            return {"content": text}

    # ---- 单项同步 API（BaseStore 契约） ---------------------------------

    def put(self, namespace, key, value, index=None, *, ttl=None) -> None:
        st = self._storage()
        minio_key = namespace_to_minio_key(namespace, key)
        st.put(self._bucket_alias, minio_key, self._serialize(value), "application/json")

    def get(self, namespace, key, *, refresh_ttl=None) -> Item | None:
        st = self._storage()
        minio_key = self._resolve_key(namespace, key)
        if not st.stat(self._bucket_alias, minio_key):
            return None
        raw = st.get(self._bucket_alias, minio_key)
        value = self._deserialize(raw)
        now = datetime.now(timezone.utc)
        return Item(
            value=value, key=key, namespace=tuple(namespace),
            created_at=now, updated_at=now,
        )

    def _resolve_key(self, namespace, key: str) -> str:
        """把 store 协议 (namespace, key) 解析为 MinIO 对象 key。

        StoreBackend 调用 store.get(namespace, key) 时，key 可能是：
        - 完整 MinIO 路径（如 "skills/builtin/patent-de-ai/SKILL.md"）
          → 直接用，避免 namespace_to_minio_key 导致双前缀
        - 纯文件名（如 "SKILL.md"）→ 拼接 namespace + key

        启发式判断：key 以 namespace 首段 + "/" 开头 = 已含前缀。
        """
        if namespace and key.startswith(namespace[0] + "/"):
            return key
        return namespace_to_minio_key(namespace, key)

    def search(
        self, namespace_prefix, /, *,
        query=None, filter=None, limit=10, offset=0, refresh_ttl=None,
    ) -> list[SearchItem]:
        """按 namespace_prefix 列出该前缀下所有对象。

        MinIO 无原生 namespace 查询，用 minio client list_objects（前缀匹配）模拟。
        每个 skill 的文件（SKILL.md/scripts/*）各成一个 SearchItem。
        query/filter 在 skill 文件场景不适用，忽略。

        key 用完整 MinIO 对象路径：StoreBackend.ls() 会用 item.key 做前缀匹配 +
        构造结果 path 字段，需要全路径而非纯文件名。
        """
        st = self._storage()
        prefix_str = "/".join(namespace_prefix) + "/"
        client = st._client  # noqa: SLF001（复用已建连的 client）
        real_bucket = st._resolve(self._bucket_alias)  # noqa: SLF001
        items: list[SearchItem] = []
        now = datetime.now(timezone.utc)
        for obj in client.list_objects(real_bucket, prefix=prefix_str, recursive=True):
            parts = obj.object_name.split("/")
            if len(parts) < 2:
                continue
            file_key = parts[-1]
            ns = tuple(parts[:-1])
            raw = st.get(self._bucket_alias, obj.object_name)
            value = self._deserialize(raw)
            items.append(SearchItem(
                value=value,
                key=obj.object_name,  # 完整 MinIO 路径：StoreBackend 做前缀匹配需要
                namespace=ns,
                created_at=now, updated_at=now,
            ))
            if len(items) >= limit + offset:
                break
        return items[offset:offset + limit]

    def delete(self, namespace, key) -> None:
        st = self._storage()
        minio_key = namespace_to_minio_key(namespace, key)
        st.delete(self._bucket_alias, minio_key)  # 幂等

    def list_namespaces(
        self, *, prefix=None, suffix=None, max_depth=None,
        limit=100, offset=0,
    ) -> list[tuple[str, ...]]:
        """列出 MinIO 下所有已存在 skill 的 namespace（前缀匹配）。

        扫描本 bucket 下对象的 key，按 "/" 切出 namespace 去重。
        max_depth 截断每个 namespace 的层数；offset/limit 分页。
        """
        st = self._storage()
        client = st._client  # noqa: SLF001
        real_bucket = st._resolve(self._bucket_alias)  # noqa: SLF001
        prefix_str = "/".join(prefix) + "/" if prefix else None
        seen: list[tuple[str, ...]] = []
        seen_set: set[tuple[str, ...]] = set()
        for obj in client.list_objects(real_bucket, prefix=prefix_str, recursive=True):
            ns = tuple(obj.object_name.split("/")[:-1])
            if max_depth is not None:
                ns = ns[:max_depth]
            if suffix and not ns.endswith(tuple(suffix)):
                continue
            if ns and ns not in seen_set:
                seen_set.add(ns)
                seen.append(ns)
        return seen[offset:offset + limit]

    async def alist_namespaces(
        self, *, prefix=None, suffix=None, max_depth=None,
        limit=100, offset=0,
    ) -> list[tuple[str, ...]]:
        return self.list_namespaces(
            prefix=prefix, suffix=suffix, max_depth=max_depth,
            limit=limit, offset=offset,
        )

    # ---- 批处理（BaseStore 真正的抽象方法） -----------------------------

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        """同步批处理：按 op 类型分发到对应单项方法。"""
        results: list[Result] = []
        for op in ops:
            if isinstance(op, PutOp):
                # value=None 表示删除（BaseStore 约定）
                if op.value is None:
                    self.delete(op.namespace, op.key)
                    results.append(None)
                else:
                    self.put(
                        op.namespace, op.key, op.value,
                        index=op.index, ttl=op.ttl,
                    )
                    results.append(None)
            elif isinstance(op, GetOp):
                results.append(
                    self.get(op.namespace, op.key, refresh_ttl=op.refresh_ttl)
                )
            elif isinstance(op, SearchOp):
                results.append(self.search(
                    op.namespace_prefix, query=op.query, filter=op.filter,
                    limit=op.limit, offset=op.offset, refresh_ttl=op.refresh_ttl,
                ))
            elif isinstance(op, ListNamespacesOp):
                # match_conditions 是高级过滤语法，skill 场景用 prefix/suffix 足够，
                # 这里退化为返回全部 namespace（不做 match 解析）。
                results.append(self.list_namespaces(limit=op.limit, offset=op.offset))
            else:  # pragma: no cover - 防御未来新增 op 类型
                raise ValueError(f"不支持的 op 类型: {type(op).__name__}")
        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        """异步批处理：直接委托同步实现（本用例无需真异步）。"""
        return self.batch(ops)
