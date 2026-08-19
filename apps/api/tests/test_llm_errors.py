"""friendly_llm_error 友好映射测试（从 api/ai.py 抽出，供 test_llm_connection 复用）。"""

from app.ai.llm_errors import friendly_llm_error


def _exc(msg: str) -> Exception:
    return Exception(msg)


def test_model_empty_1214():
    assert "模型名" in friendly_llm_error(_exc("1214 model code cannot be empty"))


def test_model_empty_value_error_wording():
    """get_llm 抛的 ValueError 含「缺少 model」，应映射到「模型名」提示。"""
    assert "模型名" in friendly_llm_error(ValueError("LLM 配置缺少 model"))


def test_bad_key_1002():
    assert "API Key" in friendly_llm_error(_exc("1002 Authorization failed"))


def test_bad_key_401():
    assert "API Key" in friendly_llm_error(_exc("401 Invalid API Key"))


def test_insufficient_balance_402_deepseek():
    """DeepSeek 402 英文报错应映射到「余额不足」提示，而非原始 JSON 透传。"""
    msg = "Error code: 402 - {'error': {'message': 'Insufficient Balance', 'type': 'unknown_error'}}"
    assert "余额不足" in friendly_llm_error(_exc(msg))


def test_timeout():
    assert "超时" in friendly_llm_error(_exc("Request timed out after 30s"))


def test_connection_error():
    assert "连接" in friendly_llm_error(_exc("Connection refused unreachable host"))


def test_json_decode_empty_response():
    """空响应 / 非 JSON 响应 → 提示检查 API 地址和密钥。"""
    assert "无效响应" in friendly_llm_error(_exc("Expecting value: line 1 column 1 (char 0)"))


def test_json_decode_html_response():
    """base_url 返回 HTML 时 httpx 抛 JSONDecodeError。"""
    assert "无效响应" in friendly_llm_error(_exc("JSONDecodeError: Expecting value: line 1 column 1 (char 0)"))


def test_json_decode_property_name():
    """JSON 格式错误 → 同属无效响应。"""
    assert "无效响应" in friendly_llm_error(_exc("Expecting property name enclosed in double quotes: line 2 column 5 (char 10)"))


def test_unmatched_keeps_original_truncated():
    long = "x" * 500
    out = friendly_llm_error(_exc(long))
    assert out == long[:200]


def test_unmatched_short_kept_as_is():
    assert friendly_llm_error(_exc("some weird error")) == "some weird error"
