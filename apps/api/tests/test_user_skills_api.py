# apps/api/tests/test_user_skills_api.py
"""用户个人技能 API 测试。

模式（沿用 Task 17 经验）：
- 登录用 "username" 字段（非 "account"）。
- TestClient 持久化 cookie：登录一次，后续请求不传 cookies=。
- registered_user 返回字符串 ID；DB 查询需 UUID() 包裹。
"""
from uuid import UUID


def _login(client, registered_user):
    """登录（cookie 自动存在 client 上）。"""
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })


def _patch_fake_storage(monkeypatch):
    """注入内存假 storage（支持 put/get/delete/stat）。

    create/update 路由会写 MinIO SKILL.md，read 详情会读，故需 fake。
    返回内部 dict 便于断言（与 test_admin_skills_api.py 一致）。
    """
    from app.core import storage as storage_mod
    fake = {}

    class _FakeStorage:
        def __init__(self): self._client = None
        def put(self, b, k, c, ct): fake[(b, k)] = c
        def get(self, b, k): return fake.get((b, k), b"")
        def delete(self, b, k): fake.pop((b, k), None)
        def stat(self, b, k): return (b, k) in fake
        def _resolve(self, a): return a

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())
    return fake


def test_user_create_personal_skill(client, registered_user, monkeypatch):
    """用户创建个人 skill。"""
    _patch_fake_storage(monkeypatch)
    _login(client, registered_user)

    resp = client.post(
        "/api/v1/skills/mine",
        json={"name": "my-style", "description": "个人风格", "skill_md": "## 简洁"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"] == "personal"
    assert data["owner_id"] == registered_user["id"]
    assert data["status"] == "draft"


def test_user_list_visible_skills(client, registered_user, db_session):
    """用户列可见 skill（global active + 自己的 personal active）。"""
    from app.models import Skill
    db_session.add(Skill(
        name="g1", description="d", scope="global", status="active",
        minio_prefix="skills/global/g1/",
    ))
    db_session.commit()

    _login(client, registered_user)

    resp = client.get("/api/v1/skills/visible")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert "g1" in names


def test_user_cannot_access_others_personal(client, registered_user, db_session, monkeypatch):
    """用户不能访问别人的 personal skill（归属校验防探测）。"""
    _patch_fake_storage(monkeypatch)
    import uuid
    from app.models import Skill

    # 另一个用户的 personal skill（draft，避免被 visible 命中）
    other = uuid.uuid4()
    skill = Skill(
        name="other-p", description="d", scope="personal", owner_id=other,
        status="draft", minio_prefix=f"skills/personal/{other}/other-p/",
    )
    db_session.add(skill)
    db_session.commit()

    _login(client, registered_user)

    # 尝试访问别人的 skill 详情 → 应被拒（403 或 404）
    resp = client.get(f"/api/v1/skills/mine/{skill.id}")
    assert resp.status_code in (403, 404)
