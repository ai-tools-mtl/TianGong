"""NLI 矛盾判断模块测试。

核心验证降级安全阀：服务故障/超时/异常时一律返回 neutral（走合并不删，绝不误判矛盾）。
"""
from unittest.mock import patch, MagicMock


def test_judge_relation_contradiction(monkeypatch):
    """NLI 明确返回 contradiction 时透传。"""
    from app.rag import nli

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    # Infinity /classify 返回 [[{"label":"contradiction","score":0.9}, ...]]
    fake_resp.json.return_value = [[
        {"label": "contradiction", "score": 0.9},
        {"label": "entailment", "score": 0.05},
        {"label": "neutral", "score": 0.05},
    ]]

    with patch("app.rag.nli.httpx.post", return_value=fake_resp):
        result = nli.judge_relation("偏好简洁", "偏好详尽")

    assert result == "contradiction"


def test_judge_relation_service_down_returns_neutral():
    """服务挂掉时降级 neutral（核心安全阀）。"""
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", side_effect=Exception("connection refused")):
        result = nli.judge_relation("偏好简洁", "偏好详尽")

    assert result == "neutral"  # 绝不误判矛盾


def test_judge_relation_timeout_returns_neutral():
    """超时降级 neutral。"""
    import httpx
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", side_effect=httpx.TimeoutException("timeout")):
        result = nli.judge_relation("a", "b")

    assert result == "neutral"


def test_judge_relation_http_error_returns_neutral():
    """HTTP 4xx/5xx 降级 neutral。"""
    from app.rag import nli

    fake_resp = MagicMock()
    fake_resp.raise_for_status.side_effect = Exception("500 server error")

    with patch("app.rag.nli.httpx.post", return_value=fake_resp):
        result = nli.judge_relation("a", "b")

    assert result == "neutral"


def test_judge_relation_entailment():
    """返回 entailment 时透传。"""
    from app.rag import nli

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = [[
        {"label": "entailment", "score": 0.95},
        {"label": "contradiction", "score": 0.03},
        {"label": "neutral", "score": 0.02},
    ]]

    with patch("app.rag.nli.httpx.post", return_value=fake_resp):
        result = nli.judge_relation("偏好简洁", "我喜欢简短")

    assert result == "entailment"
