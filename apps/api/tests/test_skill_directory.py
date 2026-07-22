# apps/api/tests/test_skill_directory.py
"""skill 目录管理：SKILL.md 组装 + 资源文件 CRUD。"""
import pytest


def test_assemble_skill_md():
    """frontmatter + 正文拼成完整 SKILL.md。"""
    from app.skills.service import assemble_skill_md
    md = assemble_skill_md(name="my-skill", description="does X", body="## Steps\n1. foo")
    assert md.startswith("---\n")
    assert "name: my-skill" in md
    assert "description: does X" in md
    assert "## Steps\n1. foo" in md


def _make_fake_storage():
    """内存假 storage + fake minio client（支持 list_objects + remove_object）。"""
    fake = {}  # (bucket, key) -> bytes

    class _FakeObj:
        def __init__(self, name): self.object_name = name

    class _FakeClient:
        def list_objects(self, bucket, prefix=None, recursive=False):
            return [_FakeObj(k) for (b, k) in list(fake.keys()) if b == bucket and k.startswith(prefix or "")]
        def remove_object(self, bucket, key):
            fake.pop((bucket, key), None)

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
            return alias

    return _FakeStorage(), fake


def test_write_and_read_skill_directory(monkeypatch):
    """写一个完整 skill 目录，读回 SKILL.md。"""
    from app.core import storage as storage_mod
    from app.skills.service import write_skill_directory, read_skill_md

    fake_storage, fake = _make_fake_storage()
    monkeypatch.setattr(storage_mod, "get_storage", lambda: fake_storage)

    prefix = "skills/global/my-skill/"
    write_skill_directory(
        bucket="global", prefix=prefix,
        name="my-skill", description="does X", body="## Steps",
        scripts={"analyze.py": "print('hi')"},
    )
    md = read_skill_md(bucket="global", prefix=prefix)
    assert "name: my-skill" in md
    # scripts 也写入了
    assert ("global", "skills/global/my-skill/scripts/analyze.py") in fake


def test_read_missing_skill_raises(monkeypatch):
    """读不存在的 skill 抛 NotFoundError。"""
    from app.core import storage as storage_mod
    from app.skills.service import read_skill_md
    from app.core.exceptions import NotFoundError

    fake_storage, _ = _make_fake_storage()
    monkeypatch.setattr(storage_mod, "get_storage", lambda: fake_storage)

    with pytest.raises(NotFoundError):
        read_skill_md(bucket="global", prefix="skills/global/nope/")


def test_delete_skill_directory(monkeypatch):
    """删 skill 目录：清空该 prefix 下所有对象。"""
    from app.core import storage as storage_mod
    from app.skills.service import write_skill_directory, delete_skill_directory, read_skill_md
    from app.core.exceptions import NotFoundError

    fake_storage, fake = _make_fake_storage()
    monkeypatch.setattr(storage_mod, "get_storage", lambda: fake_storage)

    prefix = "skills/global/my-skill/"
    write_skill_directory(
        bucket="global", prefix=prefix,
        name="my-skill", description="d", body="b",
        scripts={"foo.py": "x"}, references={"note.md": "y"},
    )
    assert ("global", "skills/global/my-skill/SKILL.md") in fake
    assert ("global", "skills/global/my-skill/scripts/foo.py") in fake

    delete_skill_directory(bucket="global", prefix=prefix)
    # 删除后所有对象都没了
    assert not any(k.startswith("skills/global/my-skill/") for (b, k) in fake)
    with pytest.raises(NotFoundError):
        read_skill_md(bucket="global", prefix=prefix)
