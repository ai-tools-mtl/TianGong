"""test_llm_connection 测试（mock ChatOpenAI / OpenAIEmbeddings，不真实联网）。"""

from unittest.mock import MagicMock, patch

from app.services import llm_config_service


def _fake_chat_resp(content="hi there"):
    m = MagicMock()
    m.content = content
    return m


def test_chat_ok_embedding_ok():
    with patch("langchain_openai.ChatOpenAI") as MC, \
         patch("langchain_openai.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.return_value = _fake_chat_resp("ok")
        ME.return_value.embed_query.return_value = [0.1] * 128
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model="emb-1",
        )
    assert res["ok"] is True
    assert res["chat"]["ok"] is True
    assert res["chat"]["error"] is None
    assert res["chat"]["sample"] == "ok"
    assert res["embedding"]["ok"] is True
    assert res["embedding"]["dim"] == 128
    assert res["error"] is None
    # 超时参数透传
    _, kwargs = MC.call_args
    assert kwargs["request_timeout"] == 15


def test_chat_ok_no_embedding_model():
    """embedding_model=None → 只测 chat，embedding 字段为 None。"""
    with patch("langchain_openai.ChatOpenAI") as MC, \
         patch("langchain_openai.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.return_value = _fake_chat_resp()
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model=None,
        )
    assert res["ok"] is True
    assert res["embedding"] is None
    ME.assert_not_called()


def test_chat_fail_embedding_ok():
    """chat 抛异常但 embedding 成功 → ok=False，两者各自报告。"""
    with patch("langchain_openai.ChatOpenAI") as MC, \
         patch("langchain_openai.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.side_effect = Exception("1214 model code cannot be empty")
        ME.return_value.embed_query.return_value = [0.1] * 8
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model="emb-1",
        )
    assert res["ok"] is False
    assert res["chat"]["ok"] is False
    assert "模型名" in res["chat"]["error"]
    assert res["embedding"]["ok"] is True  # embedding 仍独立成功


def test_chat_ok_embedding_fail():
    with patch("langchain_openai.ChatOpenAI") as MC, \
         patch("langchain_openai.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.return_value = _fake_chat_resp()
        ME.return_value.embed_query.side_effect = Exception("401 Invalid API Key")
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model="emb-1",
        )
    assert res["ok"] is False
    assert res["chat"]["ok"] is True
    assert res["embedding"]["ok"] is False
    assert "API Key" in res["embedding"]["error"]


def test_both_fail():
    with patch("langchain_openai.ChatOpenAI") as MC, \
         patch("langchain_openai.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.side_effect = Exception("connection refused")
        ME.return_value.embed_query.side_effect = Exception("timed out")
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model="emb-1",
        )
    assert res["ok"] is False
    assert res["chat"]["ok"] is False
    assert res["embedding"]["ok"] is False


def test_latency_recorded():
    with patch("langchain_openai.ChatOpenAI") as MC:
        MC.return_value.invoke.return_value = _fake_chat_resp()
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="k", model="m1", embedding_model=None,
        )
    assert isinstance(res["chat"]["latency_ms"], int)
    assert res["chat"]["latency_ms"] >= 0
