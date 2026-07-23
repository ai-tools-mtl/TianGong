# apps/api/tests/test_admin_skills_api.py
"""admin 全局技能 API 测试。"""


def _login(client, registered_user):
    """登录（cookie 自动存在 client 上）。"""
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })


def _make_admin(client, registered_user, db_session):
    """把 registered_user 升级为 admin。"""
    from uuid import UUID
    from app.models import User
    user = db_session.query(User).filter_by(id=UUID(registered_user["id"])).first()
    user.role = "admin"
    db_session.commit()


def _patch_fake_storage(monkeypatch):
    """注入内存假 storage（支持 list_objects/remove_object，返回全 key）。"""
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
        def _resolve(self, a): return a

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())
    return fake


def test_admin_create_global_skill(client, registered_user, db_session, monkeypatch):
    """admin 能创建全局 skill。"""
    _patch_fake_storage(monkeypatch)

    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)
    resp = client.post(
        "/api/v1/admin/skills",
        json={"name": "global-writer", "description": "全局撰写技能", "skill_md": "## 步骤"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"] == "global"
    assert data["status"] == "draft"


def test_non_admin_cannot_create_global(client, registered_user):
    """普通用户不能创建全局 skill（403）。"""
    _login(client, registered_user)
    resp = client.post(
        "/api/v1/admin/skills",
        json={"name": "x", "description": "d", "skill_md": "b"},
    )
    assert resp.status_code == 403


def test_admin_list_global_skills(client, registered_user, db_session):
    """admin 列全局 skill。"""
    from app.models import Skill
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)
    db_session.add(Skill(name="g1", description="d", scope="global", status="draft", minio_prefix="skills/global/g1/"))
    db_session.commit()

    resp = client.get("/api/v1/admin/skills")
    assert resp.status_code == 200
    assert any(s["name"] == "g1" for s in resp.json())


def test_admin_delete_skill(client, registered_user, db_session, monkeypatch):
    """admin 删除全局 skill。"""
    _patch_fake_storage(monkeypatch)

    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)
    # 先创建
    resp = client.post(
        "/api/v1/admin/skills",
        json={"name": "to-delete", "description": "d", "skill_md": "b"},
    )
    skill_id = resp.json()["id"]
    # 再删除
    resp = client.delete(f"/api/v1/admin/skills/{skill_id}")
    assert resp.status_code == 200
