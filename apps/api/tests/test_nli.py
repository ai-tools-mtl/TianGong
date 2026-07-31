"""NLI 矛盾判断模块测试。

当前矛盾覆盖默认禁用（Infinity /classify 不支持句子对，见 nli.py docstring）。
测试覆盖两条路径：
1. 禁用时（默认）：judge_relation 直接返回 neutral，不调用服务
2. 启用时：服务正常透传 label；故障/超时/异常一律降级 neutral（绝不误判矛盾）
"""
from unittest.mock import patch, MagicMock

import pytest


# ── 禁用态（默认）── 不会真正调用服务，直接 neutral，保证 save_memory 走合并不删

def test_judge_relation_disabled_by_default():
    """默认禁用：judge_relation 直接返回 neutral，不调用 httpx。"""
    from app.rag import nli

    # 关键断言：默认禁用时根本不发请求
    with patch("app.rag.nli.httpx.post") as mock_post:
        result = nli.judge_relation("偏好简洁", "偏好详尽")

    assert result == "neutral"
    mock_post.assert_not_called()


# ── 启用态：用 fixture 临时打开开关，测真实协议路径 ──

@pytest.fixture
def enabled_override(monkeypatch):
    """临时启用矛盾覆盖开关（默认是禁用的）。"""
    from app.rag import nli
    monkeypatch.setattr(nli, "CONTRADICTION_OVERRIDE_ENABLED", True)


def test_judge_relation_contradiction(enabled_override):
    """启用时，NLI 明确返回 contradiction 时透传。"""
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


def test_judge_relation_service_down_returns_neutral(enabled_override):
    """启用时服务挂掉，降级 neutral（核心安全阀）。"""
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", side_effect=Exception("connection refused")):
        result = nli.judge_relation("偏好简洁", "偏好详尽")

    assert result == "neutral"  # 绝不误判矛盾


def test_judge_relation_timeout_returns_neutral(enabled_override):
    """启用时超时，降级 neutral。"""
    import httpx
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", side_effect=httpx.TimeoutException("timeout")):
        result = nli.judge_relation("a", "b")

    assert result == "neutral"


def test_judge_relation_http_error_returns_neutral(enabled_override):
    """启用时 HTTP 4xx/5xx，降级 neutral。"""
    from app.rag import nli

    fake_resp = MagicMock()
    fake_resp.raise_for_status.side_effect = Exception("500 server error")

    with patch("app.rag.nli.httpx.post", return_value=fake_resp):
        result = nli.judge_relation("a", "b")

    assert result == "neutral"


def test_judge_relation_entailment(enabled_override):
    """启用时返回 entailment，透传。"""
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
