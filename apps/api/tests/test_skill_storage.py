# apps/api/tests/test_skill_storage.py
"""MinIO BaseStore 适配器测试。

用内存假实现 mock MinioStorage，不真实连 minio。
测试 namespace ↔ MinIO key 的映射 + BaseStore 方法契约。
"""
import pytest

from app.skills.storage import MinIOSkillStore, namespace_to_minio_key


def test_namespace_to_minio_key_global():
    """global skill namespace 映射 MinIO key。"""
    key = namespace_to_minio_key(("skills", "global", "my-skill"), "SKILL.md")
    assert key == "skills/global/my-skill/SKILL.md"


def test_namespace_to_minio_key_personal():
    """personal skill namespace 映射 MinIO key。"""
    key = namespace_to_minio_key(("skills", "personal", "user-uuid", "my-skill"), "SKILL.md")
    assert key == "skills/personal/user-uuid/my-skill/SKILL.md"


def _make_fake_storage():
    """构造内存假 storage + fake minio client（支持 list_objects）。"""
    fake = {}  # (bucket, key) -> bytes

    class _FakeObj:
        def __init__(self, name): self.object_name = name

    class _FakeClient:
        def list_objects(self, bucket, prefix=None, recursive=False):
            return [_FakeObj(k) for (b, k) in fake if (b == bucket and k.startswith(prefix or ""))]
        def remove_object(self, bucket, key): fake.pop((bucket, key), None)

    class _FakeStorage:
        def __init__(self):
            self._client = _FakeClient()
        def put(self, bucket, key, content, content_type):
            fake[(bucket, key)] = content
        def get(self, bucket, key):
            return fake.get((bucket, key), b"")
        def delete(self, bucket, key):
            fake.pop((bucket, key), None)
        def stat(self, bucket, key):
            return (bucket, key) in fake
        def _resolve(self, alias):
            return alias  # passthrough for test

    return _FakeStorage(), fake


def test_put_and_get_skill_md(monkeypatch):
    """put 写入 MinIO，get 读回，value 含 content 字段。"""
    from app.core import storage as storage_mod
    fake_storage, fake = _make_fake_storage()
    monkeypatch.setattr(storage_mod, "get_storage", lambda: fake_storage)

    store = MinIOSkillStore(bucket="global")
    ns = ("skills", "global", "my-skill")
    store.put(ns, "SKILL.md", {"content": "# My Skill\ninstructions here", "encoding": "utf-8"})

    item = store.get(ns, "SKILL.md")
    assert item is not None
    assert item.value["content"] == "# My Skill\ninstructions here"
    assert item.key == "SKILL.md"
    assert item.namespace == ("skills", "global", "my-skill")


def test_get_missing_returns_none(monkeypatch):
    """get 不存在的 key 返回 None。"""
    from app.core import storage as storage_mod
    fake_storage, _ = _make_fake_storage()
    monkeypatch.setattr(storage_mod, "get_storage", lambda: fake_storage)

    store = MinIOSkillStore(bucket="global")
    assert store.get(("skills", "global", "nope"), "SKILL.md") is None


def test_delete_skill(monkeypatch):
    """delete 幂等删除。"""
    from app.core import storage as storage_mod
    fake_storage, _ = _make_fake_storage()
    monkeypatch.setattr(storage_mod, "get_storage", lambda: fake_storage)

    store = MinIOSkillStore(bucket="global")
    ns = ("skills", "global", "x")
    store.put(ns, "SKILL.md", {"content": "test"})
    store.delete(ns, "SKILL.md")
    assert store.get(ns, "SKILL.md") is None
    # 二次删除不报错（幂等）
    store.delete(ns, "SKILL.md")


def test_search_by_namespace_prefix(monkeypatch):
    """search 按 namespace_prefix 列出该前缀下所有 skill 文件。"""
    from app.core import storage as storage_mod
    fake_storage, _ = _make_fake_storage()
    monkeypatch.setattr(storage_mod, "get_storage", lambda: fake_storage)

    store = MinIOSkillStore(bucket="global")
    base = ("skills", "global")
    store.put((*base, "skill-a"), "SKILL.md", {"content": "a"})
    store.put((*base, "skill-b"), "SKILL.md", {"content": "b"})

    results = store.search(base, limit=10)
    namespaces = {r.namespace for r in results}
    assert ("skills", "global", "skill-a") in namespaces
    assert ("skills", "global", "skill-b") in namespaces
