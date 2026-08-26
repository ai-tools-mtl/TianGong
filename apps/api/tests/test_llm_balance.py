"""LLM 余额探测与低额告警测试（优化计划批次 2b）。

probe 的网络层全 mock（httpx.get 打桩），无真实外呼。
"""

from unittest.mock import MagicMock, patch

import pytest

from app.core.security import encrypt_value, hash_password
from app.models import SystemSetting, User
from app.services import llm_balance_service as lbs
from app.services import llm_config_service


@pytest.fixture
def admin_user(db_session):
    u = User(
        username="admin", email="admin@example.com",
        password_hash=hash_password("Admin1234!"), name="管理员",
        role="admin", status="active",
    )
    db_session.add(u)
    db_session.commit()
    return u


def _set_global_deepseek(db_session):
    llm_config_service.set_global_chat_settings(
        db_session, enabled=True,
        base_url="https://api.deepseek.com", api_key="sk-test", model="deepseek-chat",
    )


def _mock_balance_resp(payload: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.side_effect = (
        None if status_code < 400
        else __import__("httpx").HTTPStatusError("err", request=MagicMock(), response=resp)
    )
    return resp


_OK_PAYLOAD = {
    "is_available": True,
    "balance_infos": [
        {"currency": "CNY", "total_balance": "110.50",
         "granted_balance": "10.50", "topped_up_balance": "100.00"},
    ],
}


# ── 阈值 ──


def test_threshold_default_and_roundtrip(db_session):
    assert lbs.get_threshold(db_session) == lbs.DEFAULT_THRESHOLD
    lbs.set_threshold(db_session, threshold=25.0)
    assert lbs.get_threshold(db_session) == 25.0


def test_threshold_rejects_negative(db_session):
    from app.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        lbs.set_threshold(db_session, threshold=-1)


# ── probe 分支 ──


def test_probe_unconfigured(db_session):
    result = lbs.probe_balance(db_session)
    assert result["supported"] is False
    assert result["status"] == "unconfigured"
    # 结果落库可回读
    assert lbs.get_last_status(db_session)["status"] == "unconfigured"


def test_probe_unsupported_provider(db_session):
    llm_config_service.set_global_chat_settings(
        db_session, enabled=True,
        base_url="https://api.openai.com/v1", api_key="sk-x", model="gpt-4o",
    )
    result = lbs.probe_balance(db_session)
    assert result["supported"] is False
    assert result["status"] == "unsupported"


def test_probe_deepseek_ok(db_session):
    _set_global_deepseek(db_session)
    with patch("app.services.llm_balance_service.httpx.get",
               return_value=_mock_balance_resp(_OK_PAYLOAD)):
        result = lbs.probe_balance(db_session)
    assert result["status"] == "ok"
    assert result["amount"] == 110.5
    assert result["is_low"] is False
    assert result["threshold"] == lbs.DEFAULT_THRESHOLD


def test_probe_deepseek_low_balance(db_session):
    _set_global_deepseek(db_session)
    lbs.set_threshold(db_session, threshold=200.0)
    with patch("app.services.llm_balance_service.httpx.get",
               return_value=_mock_balance_resp(_OK_PAYLOAD)):
        result = lbs.probe_balance(db_session)
    assert result["status"] == "low"
    assert result["is_low"] is True


def test_probe_deepseek_auth_error(db_session):
    _set_global_deepseek(db_session)
    with patch("app.services.llm_balance_service.httpx.get",
               return_value=_mock_balance_resp({}, status_code=401)):
        result = lbs.probe_balance(db_session)
    assert result["status"] == "error"
    assert "Key" in result["error"]


def test_probe_deepseek_timeout(db_session):
    import httpx as _httpx
    _set_global_deepseek(db_session)
    with patch("app.services.llm_balance_service.httpx.get",
               side_effect=_httpx.ConnectTimeout("timeout")):
        result = lbs.probe_balance(db_session)
    assert result["status"] == "error"
    assert "超时" in result["error"]


def test_parse_balance_prefers_cny():
    data = {"balance_infos": [
        {"currency": "USD", "total_balance": "5.00"},
        {"currency": "CNY", "total_balance": "42.00"},
    ]}
    assert lbs._parse_balance(data) == 42.0


def test_parse_balance_rejects_empty():
    with pytest.raises(ValueError):
        lbs._parse_balance({"balance_infos": []})


# ── API 层 ──


def test_llm_balance_api_admin_only(client, db_session, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    res = client.get("/api/v1/admin/llm-balance")
    assert res.status_code == 403
    res = client.post("/api/v1/admin/llm-balance/probe")
    assert res.status_code == 403


def test_llm_balance_api_roundtrip(client, db_session, admin_user):
    client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "Admin1234!",
    })
    # 默认阈值 + 无探测记录
    res = client.get("/api/v1/admin/llm-balance")
    assert res.status_code == 200
    assert res.json()["threshold"] == lbs.DEFAULT_THRESHOLD
    assert res.json()["last"] is None

    # 探测（未配置全局 → unconfigured，无网络外呼）
    res = client.post("/api/v1/admin/llm-balance/probe")
    assert res.status_code == 200
    assert res.json()["status"] == "unconfigured"

    # 设阈值 + 回读
    res = client.put("/api/v1/admin/llm-balance/threshold",
                     json={"threshold": 30})
    assert res.status_code == 200
    assert client.get("/api/v1/admin/llm-balance").json()["threshold"] == 30

    # 负数被 pydantic ge=0 拦（422）
    res = client.put("/api/v1/admin/llm-balance/threshold",
                     json={"threshold": -5})
    assert res.status_code == 422
