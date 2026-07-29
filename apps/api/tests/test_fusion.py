"""G3 RRF 融合纯函数测试。"""
from app.rag.fusion import rrf_fuse, RetrievalCandidate


def _candidate(cid: str, score: float = 0.0, content: str = "") -> RetrievalCandidate:
    return RetrievalCandidate(chunk_id=cid, content=content, vector_score=score, keyword_score=0.0)


def test_rrf_fuse_combines_two_lists():
    """两路召回按 RRF 公式融合：score = sum(1/(k+rank+1))。

    k=60 时：rank0 → 1/61，rank1 → 1/62，rank2 → 1/63。
    """
    vec = [_candidate("a"), _candidate("b"), _candidate("c")]  # a=rank0, b=rank1, c=rank2
    kw = [_candidate("b"), _candidate("d"), _candidate("a")]    # b=rank0, d=rank1, a=rank2
    fused = rrf_fuse(vec_results=vec, kw_results=kw, k=60)
    # a: 1/61 (vec rank0) + 1/63 (kw rank2) = 0.01639 + 0.01587 = 0.03226
    # b: 1/62 (vec rank1) + 1/61 (kw rank0) = 0.01613 + 0.01639 = 0.03252
    # b 两路都靠前（vec rank1 + kw rank0），应排第一
    assert fused[0].chunk_id == "b"
    assert fused[1].chunk_id == "a"
    assert fused[0].fused_score > fused[1].fused_score


def test_rrf_fuse_empty_lists():
    """两路都空，返回空。"""
    fused = rrf_fuse(vec_results=[], kw_results=[], k=60)
    assert fused == []


def test_rrf_fuse_single_list():
    """只有向量路时，RRF 退化为按该路排名（每条只算 vec 路的分）。"""
    vec = [_candidate("a"), _candidate("b")]
    fused = rrf_fuse(vec_results=vec, kw_results=[], k=60)
    assert [f.chunk_id for f in fused] == ["a", "b"]
    # a=1/61, b=1/62，a 分更高排前
    assert fused[0].fused_score > fused[1].fused_score


def test_rrf_fuse_dedup():
    """两路含同一 chunk_id 只算一次融合分（去重，不重复累加同一路）。"""
    vec = [_candidate("x"), _candidate("y")]
    kw = [_candidate("x"), _candidate("z")]  # x 两路都有
    fused = rrf_fuse(vec_results=vec, kw_results=kw, k=60)
    ids = [f.chunk_id for f in fused]
    assert ids.count("x") == 1  # 去重
    # x 两路都出现（vec rank0 + kw rank0），fused_score 最高
    assert fused[0].chunk_id == "x"


def test_rrf_fuse_preserves_content_and_weight():
    """融合后 candidate 保留首次出现的 content/weight/metadata。"""
    from app.rag.fusion import RetrievalCandidate
    vec = [RetrievalCandidate(chunk_id="x", content="vec内容", vector_score=0.9, weight=1.5, metadata={"src": "v"})]
    kw = [RetrievalCandidate(chunk_id="x", content="kw内容(应被忽略)", keyword_score=0.8, weight=2.0, metadata={"src": "k"})]
    fused = rrf_fuse(vec_results=vec, kw_results=kw, k=60)
    assert len(fused) == 1
    # 保留 vec 路首次出现的 content/weight/metadata
    assert fused[0].content == "vec内容"
    assert fused[0].weight == 1.5
    assert fused[0].metadata == {"src": "v"}
    # 但 keyword_score 应补上 kw 路的值
    assert fused[0].keyword_score == 0.8
    # fused_score 应是 vec rank0 + kw rank0 = 1/61 + 1/61
    assert abs(fused[0].fused_score - (2.0 / 61)) < 1e-9


def test_rrf_fuse_default_k_is_60():
    """默认 k=60（spec §5.3）。"""
    import inspect
    from app.rag import fusion
    sig = inspect.signature(fusion.rrf_fuse)
    assert sig.parameters["k"].default == 60
