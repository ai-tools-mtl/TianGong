"""腾讯 ima 检索源测试（admin 全局配置模式）。

覆盖：
- service: set/get 往返（加密存储）、get 脱敏、set 空串不改、resolve 三态（全局/enabled=False/env/None）
- search_ima: 成功返回片段、fail-open 返回空、strict 抛错、鉴权 header 格式
- admin API: GET/PUT /admin/console/ima、POST /admin/console/ima/test、鉴权（非 admin 403）
"""
from unittest.mock import patch

import pytest

from app.core.security import decrypt_value
from app.models import SystemSetting, User
from app.services import ima_config_service
from sqlalchemy import select


# ── service 层：set/get/resolve ──

def test_set_then_get_masks_credentials(db_session):
    """set 写入后 get 返回脱敏配置，明文不出现在响应里。"""
    ima_config_service.set_ima_settings(
        db_session, enabled=True,
        client_id="cid-global-12345", api_key="sk-global-secret",
    )
    d = ima_config_service.get_ima_settings(db_session)
    assert d["enabled"] is True
    assert "cid-global" not in d["client_id_masked"]
    assert "sk-global" not in d["api_key_masked"]
    assert "****" in d["client_id_masked"]
    assert "****" in d["api_key_masked"]


def test_set_encrypts_credentials_in_systemsetting(db_session):
    """SystemSetting 里存的是 Fernet 密文，不是明文。"""
    ima_config_service.set_ima_settings(
        db_session, enabled=True, client_id="cid-enc", api_key="sk-enc",
    )
    cfg = db_session.scalar(select(SystemSetting).where(SystemSetting.key == "ima_config"))
    assert cfg is not None
    # 密文不含明文
    assert "cid-enc" not in cfg.value["client_id_encrypted"]
    assert "sk-enc" not in cfg.value["api_key_encrypted"]
    # 可解密还原
    assert decrypt_value(cfg.value["client_id_encrypted"]) == "cid-enc"
    assert decrypt_value(cfg.value["api_key_encrypted"]) == "sk-enc"


def test_set_empty_credentials_keeps_existing(db_session):
    """set 传空 client_id/api_key → 保留已有凭据不变。"""
    ima_config_service.set_ima_settings(
        db_session, enabled=True, client_id="cid-orig", api_key="sk-orig",
    )
    # 第二次只切 enabled，凭据留空
    ima_config_service.set_ima_settings(db_session, enabled=False)
    d = ima_config_service.get_ima_settings(db_session)
    assert d["enabled"] is False
    # 凭据仍可解密（掩码非空）
    assert d["client_id_masked"] != ""
    assert d["api_key_masked"] != ""
    # 解出来还是原值
    cfg = db_session.scalar(select(SystemSetting).where(SystemSetting.key == "ima_config"))
    assert decrypt_value(cfg.value["client_id_encrypted"]) == "cid-orig"


def test_resolve_returns_none_when_unconfigured(db_session):
    """未配置（无 SystemSetting）→ None。"""
    assert ima_config_service.resolve_ima_config(db_session) is None


def test_resolve_returns_none_when_disabled(db_session, monkeypatch):
    """配置了但 enabled=False → None。"""
    monkeypatch.setattr("app.services.ima_config_service.get_settings", lambda: _FakeSettings())
    ima_config_service.set_ima_settings(
        db_session, enabled=False, client_id="cid", api_key="sk",
    )
    assert ima_config_service.resolve_ima_config(db_session) is None


def test_resolve_returns_config_when_enabled(db_session, monkeypatch):
    """配置了且 enabled=True 且 env 无兜底 → 返回解密配置。"""
    monkeypatch.setattr("app.services.ima_config_service.get_settings", lambda: _FakeSettings())
    ima_config_service.set_ima_settings(
        db_session, enabled=True, client_id="cid-active", api_key="sk-active",
    )
    resolved = ima_config_service.resolve_ima_config(db_session)
    assert resolved is not None
    assert resolved.client_id == "cid-active"
    assert resolved.api_key == "sk-active"
    assert resolved.enabled is True


def test_resolve_falls_back_to_env(db_session, monkeypatch):
    """无 SystemSetting 但 env 有凭据 → 走 env 兜底。"""
    monkeypatch.setattr(
        "app.services.ima_config_service.get_settings",
        lambda: _FakeSettings(ima_client_id="cid-env", ima_api_key="sk-env"),
    )
    resolved = ima_config_service.resolve_ima_config(db_session)
    assert resolved is not None
    assert resolved.client_id == "cid-env"
    assert resolved.api_key == "sk-env"


# ── search_ima：httpx mock ──

def test_search_ima_success_returns_snippets():
    """成功响应 → 返回统一片段结构。"""
    from app.rag.ima_source import search_ima
    from app.services.ima_config_service import ResolvedIMAConfig

    cfg = ResolvedIMAConfig(client_id="cid", api_key="sk", enabled=True)
    fake_resp = _FakeResponse(
        status=200, json_data={"results": [
            {"title": "专利A", "highlight_content": "片段A", "url": "http://a"},
            {"title": "专利B", "highlight_content": "片段B"},
        ]},
    )
    with patch("app.rag.ima_source.httpx.post", return_value=fake_resp):
        hits = search_ima("query", cfg, top_k=2)
    assert len(hits) == 2
    assert hits[0]["content"] == "片段A"
    assert hits[0]["title"] == "专利A"
    assert hits[1]["url"] is None  # 第二条无 url


def test_search_ima_failure_returns_empty():
    """异常（超时/网络）→ fail-open 返回 []，不抛错。"""
    from app.rag.ima_source import search_ima
    from app.services.ima_config_service import ResolvedIMAConfig

    cfg = ResolvedIMAConfig(client_id="cid", api_key="sk", enabled=True)
    with patch("app.rag.ima_source.httpx.post", side_effect=Exception("timeout")):
        hits = search_ima("query", cfg)
    assert hits == []


def test_search_ima_strict_raises_on_failure():
    """strict=True 时失败必须抛错（供连通性测试，区分失败与空命中）。"""
    from app.rag.ima_source import search_ima
    from app.services.ima_config_service import ResolvedIMAConfig

    cfg = ResolvedIMAConfig(client_id="bad", api_key="bad", enabled=True)
    fake_401 = _FakeResponse(status=401, json_data={"code": 200002, "msg": "skill auth failed"})
    with patch("app.rag.ima_source.httpx.post", return_value=fake_401):
        with pytest.raises(Exception):
            search_ima("query", cfg, strict=True)


def test_search_ima_build_headers_uses_official_format():
    """鉴权 header 用 ima 官方自定义格式（非 Authorization Bearer）。"""
    from app.rag.ima_source import _build_headers
    from app.services.ima_config_service import ResolvedIMAConfig

    cfg = ResolvedIMAConfig(client_id="cid-x", api_key="sk-y", enabled=True)
    h = _build_headers(cfg)
    assert h["ima-openapi-clientid"] == "cid-x"
    assert h["ima-openapi-apikey"] == "sk-y"
    assert "Authorization" not in h  # 不走 Bearer


# ── admin API 端点 ──

@pytest.fixture
def admin_client(client, db_session):
    """登录 admin 用户。"""
    _make_admin(db_session)
    client.post("/api/v1/auth/login", json={"username": "ima_admin", "password": "Pass1234!"})
    return client


def test_api_get_ima_unconfigured(admin_client):
    """无配置时 GET /admin/console/ima → {enabled: False, 空掩码}。"""
    r = admin_client.get("/api/v1/admin/console/ima")
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["client_id_masked"] == ""


def test_api_put_then_get(admin_client):
    """PUT 写配置 → GET 能读到脱敏配置。"""
    r = admin_client.put("/api/v1/admin/console/ima", json={
        "enabled": True, "client_id": "cid-api", "api_key": "sk-api-secret",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = admin_client.get("/api/v1/admin/console/ima")
    assert r.json()["enabled"] is True
    assert "cid-api" not in r.text  # 明文不回显


def test_api_requires_admin(client, db_session):
    """普通用户访问 admin 端点 → 403。"""
    _make_user(db_session)
    client.post("/api/v1/auth/login", json={"username": "ima_plain", "password": "Pass1234!"})
    r = client.get("/api/v1/admin/console/ima")
    assert r.status_code == 403


def test_api_test_endpoint_success(admin_client):
    """POST /admin/console/ima/test → 测连通性（mock httpx 成功）。"""
    fake_resp = _FakeResponse(200, {"results": [{"highlight_content": "x"}]})
    with patch("app.rag.ima_source.httpx.post", return_value=fake_resp):
        r = admin_client.post("/api/v1/admin/console/ima/test", json={
            "client_id": "cid", "api_key": "sk",
        })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["hit_count"] == 1


def test_api_requires_auth(client):
    """未登录 → 401。"""
    assert client.get("/api/v1/admin/console/ima").status_code == 401


# ── helpers ──

class _FakeSettings:
    """Settings 桩：默认无 ima env，可注入。"""
    def __init__(self, ima_client_id="", ima_api_key=""):
        self.ima_client_id = ima_client_id
        self.ima_api_key = ima_api_key


class _FakeResponse:
    """httpx.Response 最小桩。"""
    def __init__(self, status: int, json_data, text=""):
        self.status_code = status
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def _make_admin(db_session):
    from app.core.security import hash_password
    u = User(
        username="ima_admin", email="ima_admin@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="ima管理员",
        role="admin", status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _make_user(db_session):
    from app.core.security import hash_password
    u = User(
        username="ima_plain", email="ima_plain@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name="普通用户",
        role="user", status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u
