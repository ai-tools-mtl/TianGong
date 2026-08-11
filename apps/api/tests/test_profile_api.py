"""写作画像 API + service 测试。

覆盖：空读、upsert 新建、upsert 更新（部分字段）、proficiency 校验、归属隔离。
"""


def _login(client, registered_user):
    """helper：登录拿 cookie。"""
    r = client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert r.status_code == 200


# ── API 层 ──


def test_get_profile_empty(client, registered_user):
    """无画像时返回全 None 字段（不是 404）。"""
    _login(client, registered_user)
    r = client.get("/api/v1/settings/profile")
    assert r.status_code == 200
    data = r.json()
    assert data["profession"] is None
    assert data["tech_domain"] is None
    assert data["proficiency"] is None
    assert data["writing_style"] is None
    assert data["terminology"] is None


def test_upsert_create(client, registered_user):
    """首次 PUT 新建画像。"""
    _login(client, registered_user)
    r = client.put("/api/v1/settings/profile", json={
        "profession": "专利代理人",
        "tech_domain": "机械工程",
        "proficiency": "expert",
        "writing_style": "简洁直接",
        "terminology": "用「所述」",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["profession"] == "专利代理人"
    assert data["tech_domain"] == "机械工程"
    assert data["proficiency"] == "expert"
    assert data["writing_style"] == "简洁直接"
    assert data["terminology"] == "用「所述」"
    assert data["updated_at"] is not None


def test_upsert_partial_update(client, registered_user):
    """二次 PUT 仅改部分字段（留空=不改）。"""
    _login(client, registered_user)
    # 首次：全量
    client.put("/api/v1/settings/profile", json={
        "profession": "发明人",
        "tech_domain": "电子",
        "proficiency": "novice",
        "writing_style": "详尽",
        "terminology": "",
    })
    # 二次：只改 writing_style
    r = client.put("/api/v1/settings/profile", json={"writing_style": "简洁"})
    assert r.status_code == 200
    data = r.json()
    assert data["writing_style"] == "简洁"
    # 其余字段保持不变
    assert data["profession"] == "发明人"
    assert data["tech_domain"] == "电子"
    assert data["proficiency"] == "novice"


def test_upsert_idempotent_empty(client, registered_user):
    """空 PUT（全 None）不报错，保持已有画像不变。"""
    _login(client, registered_user)
    client.put("/api/v1/settings/profile", json={"profession": "代理人"})
    r = client.put("/api/v1/settings/profile", json={})
    assert r.status_code == 200
    assert r.json()["profession"] == "代理人"


def test_invalid_proficiency(client, registered_user):
    """proficiency 非法值报 422（pydantic 校验）。"""
    _login(client, registered_user)
    r = client.put("/api/v1/settings/profile", json={"proficiency": "guru"})
    assert r.status_code == 422


def test_profile_isolation(client, registered_user, db_session):
    """用户 A 的画像用户 B 读不到（一对一隔离）。"""
    from app.core.security import hash_password
    from app.models import User

    # 用户 B
    user_b = User(
        username="userb", email="b@test.com",
        password_hash=hash_password("Pass1234!"), name="B",
    )
    db_session.add(user_b)
    db_session.commit()

    _login(client, registered_user)
    client.put("/api/v1/settings/profile", json={"profession": "代理人A"})

    # B 登录读画像，应为空
    client.post("/api/v1/auth/login", json={
        "username": "userb", "password": "Pass1234!",
    })
    r = client.get("/api/v1/settings/profile")
    assert r.status_code == 200
    assert r.json()["profession"] is None  # B 没填


# ── service 层 ──


def test_service_upsert_then_get(db_session, registered_user):
    from app.services.profile_service import get_profile, upsert_profile
    from app.schemas.profile import WritingProfileUpdate
    import uuid

    uid = uuid.UUID(registered_user["id"])
    data = WritingProfileUpdate(profession="代理人", proficiency="expert")
    upsert_profile(db_session, user_id=uid, data=data)

    got = get_profile(db_session, user_id=uid)
    assert got is not None
    assert got.profession == "代理人"
    assert got.proficiency == "expert"


def test_context_assembler_injects_profile(db_session, registered_user):
    """build_system_prompt 注入结构化画像（非 user_memory fallback）。"""
    from app.services.profile_service import upsert_profile
    from app.schemas.profile import WritingProfileUpdate
    from app.ai.context_assembler import build_system_prompt
    from app.models import Project, Section
    import uuid

    uid = uuid.UUID(registered_user["id"])
    upsert_profile(db_session, user_id=uid, data=WritingProfileUpdate(
        profession="专利代理人", tech_domain="半导体",
        proficiency="expert", writing_style="简洁", terminology="用 5G",
    ))

    project = Project(user_id=uid, title="测试项目")
    db_session.add(project)
    db_session.commit()
    section = Section(
        project_id=project.id, template_section_id="background",
        key="background", title="背景技术",
        order=1, status="empty",
    )
    db_session.add(section)
    db_session.commit()

    prompt = build_system_prompt(db_session, section=section)
    assert "专利代理人" in prompt
    assert "半导体" in prompt
    assert "高密度专利术语" in prompt  # expert → 高密度指令
