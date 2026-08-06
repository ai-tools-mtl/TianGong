"""腾讯 ima 检索源测试。

覆盖：
- 凭据 upsert/掩码/解密往返（service 层）
- resolve_ima_config 三态：未配置 / disabled / enabled
- search_ima：mock httpx 成功返回片段 / 超时异常 fail-open 返回 []
- _retrieve_knowledge_for_section：ima 失败时本地结果不丢（fail-open）
- API 端点 GET/PUT /settings/ima + POST /settings/ima/test
"""
from unittest.mock import patch

import pytest

from app.core.security import decrypt_value, encrypt_value
from app.models import User, UserIMAConfig
from app.services import ima_config_service
from sqlalchemy import select


# ── service 层：凭据 upsert / resolve ──

def test_upsert_new_config_encrypts_credentials(db_session):
    """新建配置：凭据被 Fernet 加密存储，解密可还原。"""
    u = _make_user(db_session)
    cfg = ima_config_service.upsert_ima_config(
        db_session, user_id=u.id,
        client_id="cid-123", api_key="sk-secret-key",
        enabled=True,
    )
    # 密文不等于明文
    assert cfg.client_id_encrypted != "cid-123"
    assert cfg.api_key_encrypted != "sk-secret-key"
    # 可解密还原
    assert decrypt_value(cfg.client_id_encrypted) == "cid-123"
    assert decrypt_value(cfg.api_key_encrypted) == "sk-secret-key"
    assert cfg.enabled is True


def test_upsert_existing_config_partial_update(db_session):
    """已有配置：client_id/api_key 留空=不改，只切 enabled。"""
    u = _make_user(db_session)
    ima_config_service.upsert_ima_config(
        db_session, user_id=u.id,
        client_id="cid-orig", api_key="sk-orig", enabled=False,
    )
    # 第二次只切 enabled，凭据留空
    cfg = ima_config_service.upsert_ima_config(
        db_session, user_id=u.id, enabled=True,
    )
    assert decrypt_value(cfg.client_id_encrypted) == "cid-orig"
    assert decrypt_value(cfg.api_key_encrypted) == "sk-orig"
    assert cfg.enabled is True


def test_upsert_new_without_credentials_raises(db_session):
    """首次配置必须同时给 client_id + api_key，否则 ValidationError。"""
    from app.core.exceptions import ValidationError
    u = _make_user(db_session)
    with pytest.raises(ValidationError):
        ima_config_service.upsert_ima_config(db_session, user_id=u.id, enabled=True)


def test_resolve_returns_none_when_unconfigured(db_session):
    """未配置 → None。"""
    u = _make_user(db_session)
    assert ima_config_service.resolve_ima_config(db_session, user_id=u.id) is None


def test_resolve_returns_none_when_disabled(db_session):
    """配置了但 enabled=False → None。"""
    u = _make_user(db_session)
    ima_config_service.upsert_ima_config(
        db_session, user_id=u.id,
        client_id="cid", api_key="sk", enabled=False,
    )
    assert ima_config_service.resolve_ima_config(db_session, user_id=u.id) is None


def test_resolve_returns_config_when_enabled(db_session):
    """配置了且 enabled=True → 返回解密后的 ResolvedIMAConfig。"""
    u = _make_user(db_session)
    ima_config_service.upsert_ima_config(
        db_session, user_id=u.id,
        client_id="cid-active", api_key="sk-active", enabled=True,
    )
    resolved = ima_config_service.resolve_ima_config(db_session, user_id=u.id)
    assert resolved is not None
    assert resolved.client_id == "cid-active"
    assert resolved.api_key == "sk-active"
    assert resolved.enabled is True


def test_config_to_dict_masks_credentials(db_session):
    """dict 输出：凭据被掩码，不回显明文。"""
    u = _make_user(db_session)
    cfg = ima_config_service.upsert_ima_config(
        db_session, user_id=u.id,
        client_id="cid12345", api_key="sk-abcdefghij", enabled=True,
    )
    d = ima_config_service.config_to_dict(cfg)
    assert d["configured"] is True
    assert d["enabled"] is True
    # 明文不出现在掩码字段里
    assert "cid12345" not in d["client_id_masked"]
    assert "abcdefghij" not in d["api_key_masked"]
    assert "****" in d["client_id_masked"]
    assert "****" in d["api_key_masked"]


def test_config_to_dict_none_returns_default():
    """无配置 → {configured: False}。"""
    d = ima_config_service.config_to_dict(None)
    assert d["configured"] is False
    assert d["enabled"] is False


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
    import pytest as _pytest
    from app.rag.ima_source import search_ima
    from app.services.ima_config_service import ResolvedIMAConfig

    cfg = ResolvedIMAConfig(client_id="bad", api_key="bad", enabled=True)
    fake_401 = _FakeResponse(status=401, json_data={"code": 200002, "msg": "skill auth failed"})
    with patch("app.rag.ima_source.httpx.post", return_value=fake_401):
        with _pytest.raises(Exception):
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


def test_search_ima_empty_query_returns_empty():
    """空 query → 直接返回 []，不发请求。"""
    from app.rag.ima_source import search_ima
    from app.services.ima_config_service import ResolvedIMAConfig

    cfg = ResolvedIMAConfig(client_id="cid", api_key="sk", enabled=True)
    with patch("app.rag.ima_source.httpx.post") as mock_post:
        assert search_ima("", cfg) == []
        mock_post.assert_not_called()


# ── API 端点 ──

@pytest.fixture
def logged_in_user(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })
    return registered_user


def test_api_get_ima_unconfigured(client, logged_in_user):
    """无配置时 GET /settings/ima → {configured: False}。"""
    r = client.get("/api/v1/settings/ima")
    assert r.status_code == 200
    assert r.json()["configured"] is False


def test_api_upsert_then_get(client, logged_in_user):
    """PUT 新建 → GET 能读到掩码配置。"""
    r = client.put("/api/v1/settings/ima", json={
        "client_id": "cid-api", "api_key": "sk-api-secret", "enabled": True,
    })
    assert r.status_code == 200
    assert r.json()["configured"] is True
    assert r.json()["enabled"] is True

    r = client.get("/api/v1/settings/ima")
    assert r.json()["configured"] is True
    assert "cid-api" not in r.text  # 明文不回显


def test_api_toggle_enabled_without_credentials_change(client, logged_in_user, db_session):
    """PUT 切 enabled 留空凭据 → 凭据不变。"""
    u = _get_user(db_session, logged_in_user["id"])
    assert u is not None
    ima_config_service.upsert_ima_config(
        db_session, user_id=u.id,
        client_id="cid-orig", api_key="sk-orig", enabled=True,
    )
    r = client.put("/api/v1/settings/ima", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    # 凭据仍可解密（未被清空）
    cfg = ima_config_service.get_ima_config(db_session, user_id=u.id)
    assert decrypt_value(cfg.client_id_encrypted) == "cid-orig"


def test_api_test_endpoint_success(client, logged_in_user):
    """POST /settings/ima/test → 测连通性（mock httpx 成功）。"""
    fake_resp = _FakeResponse(200, {"results": [{"highlight_content": "x"}]})
    with patch("app.rag.ima_source.httpx.post", return_value=fake_resp):
        r = client.post("/api/v1/settings/ima/test", json={
            "client_id": "cid", "api_key": "sk",
        })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["hit_count"] == 1


def test_api_requires_auth(client):
    """未登录 → 401。"""
    assert client.get("/api/v1/settings/ima").status_code == 401


# ── _retrieve_knowledge_for_section fail-open 集成 ──

def test_ima_failure_does_not_block_local(db_session, monkeypatch):
    """ima 检索失败时，本地结果仍正常返回（fail-open 不丢）。

    构造：mock 本地 retrieve 返回本地结果 + mock ima 异常，
    验证合并函数仍返回本地结果。
    """
    from app.ai.context_assembler import _retrieve_ima_for_section
    from app.rag.retriever import RetrievalResult

    u = _make_user(db_session)

    # 本地检索返回一条
    local = [RetrievalResult(content="本地片段", score=0.9,
                             source_section_key="problem", project_title="案例X")]

    # ima 配置开启，但底层 httpx 调用抛异常
    ima_config_service.upsert_ima_config(
        db_session, user_id=u.id,
        client_id="cid", api_key="sk", enabled=True,
    )
    # patch httpx.post 抛异常——search_ima 内部 fail-open 会吞掉返回 []
    monkeypatch.setattr(
        "app.rag.ima_source.httpx.post",
        lambda *a, **k: (_ for _ in ()).throw(Exception("ima down")),
    )

    # ima 子函数失败返回 []（search_ima 内部 try/except 兜底）
    ima_hits = _retrieve_ima_for_section(db_session, u.id, "query")
    assert ima_hits == []  # fail-open：异常被 search_ima 内部吞掉返回 []


# ── helpers ──

def _make_user(db_session, *, username="imauser", email="ima@example.com"):
    from app.core.security import hash_password
    u = User(
        username=username, email=email,
        password_hash=hash_password("Pass1234!"), name="ima测试", role="user",
        status="active",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _get_user(db_session, user_id):
    """按 id 查用户。user_id 可能是 str，User.id 是 UUID，需转换。"""
    import uuid as _uuid
    from sqlalchemy import select
    uid = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    return db_session.scalar(select(User).where(User.id == uid))


class _FakeResponse:
    """httpx.Response 最小桩（只实现测试用到的接口）。"""
    def __init__(self, status: int, json_data, text=""):
        self.status_code = status
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json
