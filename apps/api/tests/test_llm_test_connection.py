"""test_llm_connection 测试（mock ChatOpenAI，不真实联网）。

embedding 已改走固定 bge-m3 微服务，test_llm_connection 收窄为只测 chat；
embedding 字段恒为 None。原 embedding 双测用例已删。
"""

from unittest.mock import MagicMock, patch

from app.services import llm_config_service


def _fake_chat_resp(content="hi there"):
    m = MagicMock()
    m.content = content
    return m


def test_chat_ok():
    with patch("langchain_openai.ChatOpenAI") as MC:
        MC.return_value.invoke.return_value = _fake_chat_resp("ok")
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1",
        )
    assert res["ok"] is True
    assert res["chat"]["ok"] is True
    assert res["chat"]["error"] is None
    assert res["chat"]["sample"] == "ok"
    assert res["embedding"] is None  # embedding 不再经此函数测
    assert res["error"] is None
    # 超时参数透传
    _, kwargs = MC.call_args
    assert kwargs["request_timeout"] == 15


def test_chat_fail():
    """chat 抛异常 → ok=False，错误经 friendly_llm_error 友好化。"""
    with patch("langchain_openai.ChatOpenAI") as MC:
        MC.return_value.invoke.side_effect = Exception("1214 model code cannot be empty")
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1",
        )
    assert res["ok"] is False
    assert res["chat"]["ok"] is False
    assert "模型名" in res["chat"]["error"]
    assert res["embedding"] is None


def test_latency_recorded():
    with patch("langchain_openai.ChatOpenAI") as MC:
        MC.return_value.invoke.return_value = _fake_chat_resp()
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="k", model="m1",
        )
    assert isinstance(res["chat"]["latency_ms"], int)
    assert res["chat"]["latency_ms"] >= 0
