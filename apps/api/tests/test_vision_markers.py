# apps/api/tests/test_vision_markers.py
"""vision 探测名单 admin 配置测试：resolve 合并/开关 + is_vision_model 注入 + admin 端点。"""
import pytest

from app.ai.vision import is_vision_model, resolve_vision_markers
from app.core.security import hash_password
from app.models import AuditLog, SystemSetting, User


@pytest.fixture
def admin_and_login(client, db_session):
    admin = User(
        username="admin",
        email="admin@example.com", password_hash=hash_password("Admin1234!"),
        name="管理员", role="admin", status="active",
    )
    db_session.add(admin)
    db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234!"})
    return admin


# ── resolve_vision_markers ────────────────────────────────────────────────────


def test_resolve_without_setting_returns_none(db_session):
    """无配置 → None（用内置名单，行为与历史版本一致）。"""
    assert resolve_vision_markers(db_session) is None


def test_resolve_extra_markers_merged(db_session):
    db_session.add(SystemSetting(key="vision_model_markers", value={
        "enabled": True, "extra_markers": ["MyModel-Vision", "  ", 123],
    }))
    db_session.commit()
    markers = resolve_vision_markers(db_session)
    assert markers is not None
    assert "mymodel-vision" in markers
    assert "gpt-4o" in markers  # 内置保留


def test_resolve_disabled_returns_empty(db_session):
    """enabled=False → 空元组（is_vision_model 恒 False，全部文字降级）。"""
    db_session.add(SystemSetting(key="vision_model_markers", value={
        "enabled": False, "extra_markers": ["gpt-4o"],
    }))
    db_session.commit()
    assert resolve_vision_markers(db_session) == ()


def test_resolve_dirty_setting_falls_back(db_session):
    db_session.add(SystemSetting(key="vision_model_markers", value="not-a-dict"))
    db_session.commit()
    assert resolve_vision_markers(db_session) is None


# ── is_vision_model 注入 ──────────────────────────────────────────────────────


def test_is_vision_model_with_injected_markers():
    # 注入名单不含内置条目 → 内置默认模型不再判 vision
    assert is_vision_model("gpt-4o") is True
    assert is_vision_model("gpt-4o", markers=("mymodel-vision",)) is False
    # 子串匹配：模型名包含注入标记即命中
    assert is_vision_model("acme-mymodel-vision-pro", markers=("mymodel-vision",)) is True
    # 空元组 = 禁用
    assert is_vision_model("gpt-4o", markers=()) is False


# ── admin 端点 ────────────────────────────────────────────────────────────────


def test_get_default_config(client, admin_and_login):
    res = client.get("/api/v1/admin/console/vision-markers")
    assert res.status_code == 200
    assert res.json() == {"enabled": True, "extra_markers": []}


def test_put_config_persists_and_audits(client, admin_and_login, db_session):
    res = client.put("/api/v1/admin/console/vision-markers", json={
        "enabled": True, "extra_markers": ["MyModel-Vision"],
    })
    assert res.status_code == 200
    # 保存时小写化
    assert res.json()["extra_markers"] == ["mymodel-vision"]

    db_session.expire_all()
    audit = db_session.query(AuditLog).filter_by(action="set_vision_markers").one()
    assert audit.detail["extra_markers"] == ["mymodel-vision"]

    # 生效：resolve 能读到
    assert "mymodel-vision" in (resolve_vision_markers(db_session) or ())


def test_non_admin_403(client, registered_user, db_session):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    assert client.get("/api/v1/admin/console/vision-markers").status_code == 403
