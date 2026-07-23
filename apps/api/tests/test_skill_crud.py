# apps/api/tests/test_skill_crud.py
"""Skill CRUD 测试：DB + MinIO 协同。"""
import uuid
import pytest


@pytest.fixture
def fake_storage(monkeypatch):
    """内存假 storage + fake minio client（支持 list_objects/remove_object）。"""
    from app.core import storage as storage_mod
    fake = {}

    class _FakeObj:
        def __init__(self, name): self.object_name = name

    class _FakeClient:
        def list_objects(self, bucket, prefix=None, recursive=False):
            return [_FakeObj(k)
                    for (b, k) in fake if b == bucket and k.startswith(prefix or "")]
        def remove_object(self, bucket, key):
            fake.pop((bucket, key), None)

    class _FakeStorage:
        def __init__(self): self._client = _FakeClient()
        def put(self, b, k, c, ct): fake[(b, k)] = c
        def get(self, b, k): return fake.get((b, k), b"")
        def delete(self, b, k): fake.pop((b, k), None)
        def stat(self, b, k): return (b, k) in fake
        def _resolve(self, alias): return alias

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())
    return fake


def test_create_global_skill(db_session, fake_storage):
    """创建全局 skill：写 DB + MinIO 目录。"""
    from app.skills.service import create_skill
    from app.models.skill import SCOPE_GLOBAL

    skill = create_skill(
        db_session,
        scope=SCOPE_GLOBAL, owner_id=None,
        name="prior-art-search", description="检索现有技术",
        body="## Steps\n1. 分析技术领域",
    )
    assert skill.id is not None
    assert skill.scope == "global"
    assert skill.status == "draft"  # 默认 draft
    # MinIO 有 SKILL.md（所有 skill 都在 global bucket）
    assert ("global", "skills/global/prior-art-search/SKILL.md") in fake_storage


def test_create_personal_skill(db_session, fake_storage):
    """创建个人 skill：minio_prefix 含 owner_id，仍在 global bucket。"""
    from app.skills.service import create_skill
    from app.models.skill import SCOPE_PERSONAL

    owner = uuid.uuid4()
    skill = create_skill(
        db_session, scope=SCOPE_PERSONAL, owner_id=owner,
        name="my-writer", description="个人撰写偏好",
        body="## 风格\n简洁",
    )
    assert skill.scope == "personal"
    assert f"skills/personal/{owner}/my-writer/" in skill.minio_prefix
    # personal skill 也在 global bucket（C1 决定）
    assert ("global", f"skills/personal/{owner}/my-writer/SKILL.md") in fake_storage


def test_create_duplicate_name_raises(db_session, fake_storage):
    """同 scope+owner 下 name 唯一。"""
    from app.skills.service import create_skill
    from app.core.exceptions import ConflictError

    create_skill(db_session, scope="global", owner_id=None,
                 name="dup", description="d", body="b")
    with pytest.raises(ConflictError):
        create_skill(db_session, scope="global", owner_id=None,
                     name="dup", description="d", body="b")


def test_update_skill_status(db_session, fake_storage):
    """更新状态 draft→active。"""
    from app.skills.service import create_skill, update_skill

    skill = create_skill(db_session, scope="global", owner_id=None,
                         name="s1", description="d", body="b")
    updated = update_skill(db_session, skill_id=skill.id, status="active")
    assert updated.status == "active"


def test_delete_skill_removes_db_and_minio(db_session, fake_storage):
    """删除 skill：DB 行 + MinIO 目录都清。"""
    from app.skills.service import create_skill, delete_skill, get_skill
    from app.core.exceptions import NotFoundError

    skill = create_skill(db_session, scope="global", owner_id=None,
                         name="del", description="d", body="b")
    key = "skills/global/del/SKILL.md"
    assert ("global", key) in fake_storage

    delete_skill(db_session, skill_id=skill.id)
    with pytest.raises(NotFoundError):
        get_skill(db_session, skill_id=skill.id)
    assert ("global", key) not in fake_storage


def test_list_skills_by_scope(db_session, fake_storage):
    """按 scope + owner 列出 skill。"""
    from app.skills.service import create_skill, list_skills

    create_skill(db_session, scope="global", owner_id=None, name="g1", description="d", body="b")
    owner = uuid.uuid4()
    create_skill(db_session, scope="personal", owner_id=owner, name="p1", description="d", body="b")

    global_skills = list_skills(db_session, scope="global", owner_id=None)
    assert [s.name for s in global_skills] == ["g1"]

    personal_skills = list_skills(db_session, scope="personal", owner_id=owner)
    assert [s.name for s in personal_skills] == ["p1"]


def test_read_skill_detail(db_session, fake_storage):
    """读详情：skill 元数据 + SKILL.md 正文。"""
    from app.skills.service import create_skill, read_skill_detail

    skill = create_skill(db_session, scope="global", owner_id=None,
                         name="detail", description="详细技能", body="## 正文内容")
    result_skill, md = read_skill_detail(db_session, skill_id=skill.id)
    assert result_skill.name == "detail"
    assert "## 正文内容" in md
    assert "name: detail" in md  # frontmatter
