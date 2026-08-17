"""G3 rerank client 测试（mock httpx，不真实调 API）。"""
import pytest
from unittest.mock import patch, MagicMock
from app.rag.reranker import rerank, RerankConfig


def _config():
    return RerankConfig(
        enabled=True, base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="test-key", model="rerank", top_n=3,
    )


@patch("app.rag.reranker.httpx.post")
def test_rerank_returns_sorted_by_relevance(mock_post):
    """rerank 按 relevance_score 降序返回 top_n。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {"index": 2, "relevance_score": 0.95},
            {"index": 0, "relevance_score": 0.80},
            {"index": 1, "relevance_score": 0.60},
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    candidates = ["doc0", "doc1", "doc2"]
    ranked = rerank("query", candidates, config=_config())
    # 按 score 降序返回 (索引, 分数)：doc2(0.95) > doc0(0.80) > doc1(0.60)
    assert ranked == [(2, 0.95), (0, 0.80), (1, 0.60)]


@patch("app.rag.reranker.httpx.post")
def test_rerank_respects_top_n(mock_post):
    """top_n=2 只返回前 2 条。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.8},
            {"index": 2, "relevance_score": 0.7},
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    cfg = _config()
    cfg.top_n = 2
    ranked = rerank("query", ["a", "b", "c"], config=cfg)
    assert len(ranked) == 2
    assert ranked == [(1, 0.9), (0, 0.8)]


def test_rerank_disabled_returns_input_unchanged():
    """rerank 关闭时原样返回（D5 降级）。"""
    cfg = _config()
    cfg.enabled = False
    ranked = rerank("query", ["a", "b", "c"], config=cfg)
    assert ranked == [(0, 0.0), (1, 0.0), (2, 0.0)]


def test_rerank_empty_documents_returns_empty():
    """空 documents 直接返回空（不调 API）。"""
    cfg = _config()
    ranked = rerank("query", [], config=cfg)
    assert ranked == []


@patch("app.rag.reranker.httpx.post")
def test_rerank_failure_returns_input_unchanged(mock_post):
    """API 失败时降级返回原序（D5，不报错）。"""
    mock_post.side_effect = Exception("network error")
    ranked = rerank("query", ["a", "b", "c"], config=_config())
    assert ranked == [(0, 0.0), (1, 0.0), (2, 0.0)]  # 降级，原序零分


@patch("app.rag.reranker.httpx.post")
def test_rerank_http_error_returns_input_unchanged(mock_post):
    """HTTP 错误（如 401/500）时降级返回原序（raise_for_status 抛错被 catch）。"""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.raise_for_status.side_effect = Exception("401 Unauthorized")
    mock_post.return_value = mock_resp

    ranked = rerank("query", ["a", "b"], config=_config())
    assert ranked == [(0, 0.0), (1, 0.0)]  # 降级，原序零分


@patch("app.rag.reranker.httpx.post")
def test_rerank_calls_correct_endpoint(mock_post):
    """验证 rerank 调用了正确的 URL + payload。"""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [{"index": 0, "relevance_score": 0.9}]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    cfg = _config()
    rerank("my query", ["doc"], config=cfg)

    # 验证调用参数
    call_args = mock_post.call_args
    assert call_args.args[0] == "https://open.bigmodel.cn/api/paas/v4/rerank"
    headers = call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer test-key"
    body = call_args.kwargs["json"]
    assert body["model"] == "rerank"
    assert body["query"] == "my query"
    assert body["documents"] == ["doc"]
    assert body["top"] == 3
    assert body["return_documents"] is False


@patch("app.rag.reranker.httpx.post")
def test_rerank_strict_raises_on_failure(mock_post):
    """strict=True 时 API 失败必须抛错（供 admin 测试连通性端点用）。

    非 strict 模式（默认）会 D5 降级返回原序，导致 test 端点无法诊断真实失败。
    """
    import pytest
    mock_post.side_effect = Exception("network error")
    with pytest.raises(Exception, match="network error"):
        rerank("query", ["a", "b"], config=_config(), strict=True)


@patch("app.rag.reranker.httpx.post")
def test_rerank_strict_raises_on_http_error(mock_post):
    """strict=True 时 HTTP 错误（401/500）也抛错。"""
    import pytest
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("401 Unauthorized")
    mock_post.return_value = mock_resp
    with pytest.raises(Exception, match="401"):
        rerank("query", ["a"], config=_config(), strict=True)


@patch("app.rag.reranker.httpx.post")
def test_rerank_strict_success_returns_ranked(mock_post):
    """strict=True 时成功调用正常返回（不抛错）。"""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.5}]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp
    ranked = rerank("query", ["a", "b"], config=_config(), strict=True)
    assert ranked == [(1, 0.9), (0, 0.5)]
