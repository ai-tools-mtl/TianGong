"""list_provider_models 测试（mock httpx，不真实联网）。"""

from unittest.mock import MagicMock, patch

import httpx

from app.services import llm_config_service


def _ok_response(status_code=200, json_data=None):
    """构造假的 httpx.Response。"""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.json.return_value = json_data or {}
    return r


def test_openai_compatible_format():
    """OpenAI 兼容 /models：{data:[{id:...}]} → 取 id。"""
    fake = _ok_response(200, {"data": [
        {"id": "glm-4-plus"}, {"id": "glm-4-flash"}, {"id": "embedding-3"},
    ]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake) as m:
        res = llm_config_service.list_provider_models(
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key="sk-test",
            provider_template_id="zhipu",
        )
    assert res["error"] is None
    assert res["models"] == ["embedding-3", "glm-4-flash", "glm-4-plus"]  # 去重+排序
    assert res["truncated"] is False
    # 验证 URL 拼接：base_url + 模板的 models_endpoint("/models")
    called_url = m.call_args.args[0]
    assert called_url == "https://open.bigmodel.cn/api/paas/v4/models"


def test_ollama_tags_format():
    """Ollama /api/tags：{models:[{name:...}]} → 取 name。"""
    fake = _ok_response(200, {"models": [
        {"name": "qwen2.5:7b"}, {"name": "nomic-embed-text"},
    ]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake) as m:
        res = llm_config_service.list_provider_models(
            base_url="http://localhost:11434",
            api_key="x",
            provider_template_id="ollama",
        )
    assert res["error"] is None
    assert "qwen2.5:7b" in res["models"]
    assert "nomic-embed-text" in res["models"]
    # ollama base_url 无版本段，endpoint 是完整 /api/tags
    assert m.call_args.args[0] == "http://localhost:11434/api/tags"


def test_default_to_models_when_no_template():
    """未给 template_id 时默认走 /models（OpenAI 兼容假设）。"""
    fake = _ok_response(200, {"data": [{"id": "m1"}]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake) as m:
        llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    called_url = m.call_args.args[0]
    assert called_url == "https://x.com/v1/models"


def test_401_returns_error_not_raise():
    fake = _ok_response(401, {"error": "bad key"})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="bad", provider_template_id=None,
        )
    assert res["models"] == []
    assert "API Key" in res["error"] or "401" in res["error"]


def test_connection_error_returns_error():
    with patch("app.services.llm_config_service.httpx.get",
               side_effect=httpx.ConnectError("refused")):
        res = llm_config_service.list_provider_models(
            base_url="https://down.example.com", api_key="k", provider_template_id=None,
        )
    assert res["models"] == []
    assert "连接" in res["error"]


def test_timeout_returns_error():
    with patch("app.services.llm_config_service.httpx.get",
               side_effect=httpx.TimeoutException("slow")):
        res = llm_config_service.list_provider_models(
            base_url="https://slow.example.com", api_key="k", provider_template_id=None,
        )
    assert res["models"] == []
    assert "超时" in res["error"]


def test_truncation_at_100():
    fake = _ok_response(200, {"data": [{"id": f"m{i}"} for i in range(150)]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    assert len(res["models"]) == 100
    assert res["truncated"] is True


def test_dedup():
    fake = _ok_response(200, {"data": [{"id": "a"}, {"id": "a"}, {"id": "b"}]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    assert res["models"] == ["a", "b"]


def test_unexpected_format_returns_error():
    fake = _ok_response(200, {"weird": "shape"})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    assert res["models"] == []
    assert "格式" in res["error"] or "解析" in res["error"]


def test_generic_non_200_returns_error():
    """非 200 且非 401/403（如 500/429）→ 返回 HTTP 错误，不抛。"""
    fake = _ok_response(500, {})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    assert res["models"] == []
    assert "500" in res["error"]


def test_non_json_response_returns_error():
    """响应非 JSON（resp.json() 抛异常）→ 返回解析错误，不抛。"""
    fake = _ok_response(200, None)
    fake.json.side_effect = ValueError("not json")
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    assert res["models"] == []
    assert "JSON" in res["error"] or "解析" in res["error"]
