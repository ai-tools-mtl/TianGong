"""G3 RRF（Reciprocal Rank Fusion）融合算法（spec §5.3 阶段2）。

工业标准融合算法，无需训练、参数少（k=60 经验值）。
论文：Cormack et al., SIGIR 2009。
"""
from dataclasses import dataclass, field


@dataclass
class RetrievalCandidate:
    """检索候选（融合前/后通用）。"""
    chunk_id: str
    content: str
    vector_score: float = 0.0    # 向量路原始分（cosine similarity）
    keyword_score: float = 0.0   # 关键词路原始分（ts_rank_cd）
    fused_score: float = 0.0     # RRF 融合后分
    weight: float = 1.0          # G4 chunk 权重（召回分数乘子）
    metadata: dict = field(default_factory=dict)


def rrf_fuse(
    vec_results: list[RetrievalCandidate],
    kw_results: list[RetrievalCandidate],
    k: int = 60,
) -> list[RetrievalCandidate]:
    """RRF 融合：score = sum(1 / (k + rank + 1))，按融合分降序。

    两路结果按 chunk_id 去重，保留首次出现的 content/metadata/weight。
    vector_score/keyword_score 取该 chunk 在对应路出现的值（去重后不累加原始分）。
    """
    scores: dict[str, float] = {}
    index: dict[str, RetrievalCandidate] = {}

    for rank, c in enumerate(vec_results):
        scores[c.chunk_id] = scores.get(c.chunk_id, 0.0) + 1.0 / (k + rank + 1)
        if c.chunk_id not in index:
            index[c.chunk_id] = c  # 保留首次出现的（含 content/weight/metadata）
            index[c.chunk_id].vector_score = c.vector_score

    for rank, c in enumerate(kw_results):
        scores[c.chunk_id] = scores.get(c.chunk_id, 0.0) + 1.0 / (k + rank + 1)
        if c.chunk_id not in index:
            index[c.chunk_id] = c
        index[c.chunk_id].keyword_score = c.keyword_score  # 补 kw 路的分

    for cid, score in scores.items():
        index[cid].fused_score = score

    return sorted(index.values(), key=lambda c: -c.fused_score)
