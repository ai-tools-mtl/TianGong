"""NLI 矛盾判断模块测试。

当前矛盾覆盖默认启用（自建 NLI 微服务 apps/nli/ 已就绪，支持真实句子对推理）。
测试覆盖两条路径：
1. 启用时（默认）：调 /nli 端点，透传 label；故障/超时/异常一律降级 neutral（绝不误判矛盾）
2. 禁用时：judge_relation 直接返回 neutral，不调用服务
"""
from unittest.mock import patch, MagicMock

import pytest


def _fake_ok(label: str, score: float = 0.9) -> MagicMock:
    """构造自建 NLI 微服务的成功响应：扁平 {"label":..., "score":...}。"""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"label": label, "score": score}
    return resp


# ── 启用态（默认）── 调 /nli 端点透传 label ──

def test_judge_relation_contradiction():
    """默认启用，NLI 返回 contradiction 时透传。"""
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", return_value=_fake_ok("contradiction", 0.99)):
        result = nli.judge_relation("偏好简洁", "偏好详尽")

    assert result == "contradiction"


def test_judge_relation_entailment():
    """返回 entailment 时透传。"""
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", return_value=_fake_ok("entailment", 0.95)):
        result = nli.judge_relation("偏好简洁", "我喜欢简短")

    assert result == "entailment"


def test_judge_relation_service_down_returns_neutral():
    """服务挂掉，降级 neutral（核心安全阀，绝不误判矛盾）。"""
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", side_effect=Exception("connection refused")):
        result = nli.judge_relation("偏好简洁", "偏好详尽")

    assert result == "neutral"


def test_judge_relation_timeout_returns_neutral():
    """超时，降级 neutral。"""
    import httpx
    from app.rag import nli

    with patch("app.rag.nli.httpx.post", side_effect=httpx.TimeoutException("timeout")):
        result = nli.judge_relation("a", "b")

    assert result == "neutral"


def test_judge_relation_http_error_returns_neutral():
    """HTTP 4xx/5xx，降级 neutral。"""
    from app.rag import nli

    fake_resp = MagicMock()
    fake_resp.raise_for_status.side_effect = Exception("500 server error")

    with patch("app.rag.nli.httpx.post", return_value=fake_resp):
        result = nli.judge_relation("a", "b")

    assert result == "neutral"


# ── 禁用态：开关关闭时不调服务，直接 neutral ──

@pytest.fixture
def disabled_override(monkeypatch):
    """临时关闭矛盾覆盖开关（默认是启用的）。"""
    from app.rag import nli
    monkeypatch.setattr(nli, "CONTRADICTION_OVERRIDE_ENABLED", False)


def test_judge_relation_disabled_returns_neutral_without_call(disabled_override):
    """禁用时 judge_relation 直接返回 neutral，不调用 httpx。"""
    from app.rag import nli

    with patch("app.rag.nli.httpx.post") as mock_post:
        result = nli.judge_relation("偏好简洁", "偏好详尽")

    assert result == "neutral"
    mock_post.assert_not_called()
