"""检索服务：混合检索（向量 + BM25 + RRF + rerank）（设计 10.4 + spec §5.3）。"""
import logging
from dataclasses import dataclass

from pgvector.sqlalchemy import HALFVEC as HalfVec
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

from app.core.database import is_postgres
from app.models import KnowledgeChunk
from app.rag.embedding import embed_text
from app.rag.fusion import rrf_fuse, RetrievalCandidate
from app.rag.reranker import rerank
from app.services.llm_config_service import resolve_embedding_config
from app.services.rag_config_service import resolve_rerank_config
from app.services.llm_log_helper import log_embed_call

logger = logging.getLogger(__name__)
SIMILARITY_THRESHOLD = 0.5
RETRIEVAL_CANDIDATE_POOL = 10  # 召回阶段放大候选池，融合+rerank 后再截断 top_k


@dataclass
class RetrievalResult:
    content: str
    score: float
    source_section_key: str | None
    project_title: str | None


def retrieve(
    db: Session, *, user_id, query: str, top_k: int = 3, scope: str | None = None
) -> list[RetrievalResult]:
    """混合检索：向量路 + 关键词路 → RRF 融合 → rerank → 截断 top_k。

    scope=None（默认）：三域规则，global + 本人 personal（向后兼容）。
    scope="global"：仅 global（admin 检索测试用）。
    scope="personal"：仅本人 personal。
    """
    embed_config = resolve_embedding_config(db, user_id=user_id)
    if embed_config is None:
        return []
    try:
        query_vec = embed_text(query, embed_config=embed_config)
    except Exception:
        # D7：embed 失败也记一条日志，再向上抛
        log_embed_call(
            db, user_id=user_id, model=embed_config.model,
            provider=embed_config.source, status="failed",
        )
        raise
    # D7：写 embedding 调用日志（无 project_id，检索与具体 project 无关）
    log_embed_call(
        db, user_id=user_id, model=embed_config.model,
        provider=embed_config.source, status="success",
    )

    # scope 过滤（G2，双路共用）：默认 None=三域规则（global + 本人 personal，向后兼容）；
    # admin 检索测试可强制 scope="global" 只看全局视角。
    if scope == "global":
        scope_filter = KnowledgeChunk.scope == "global"
    elif scope == "personal":
        scope_filter = (KnowledgeChunk.scope == "personal") & (
            KnowledgeChunk.user_id == user_id
        )
    else:
        scope_filter = (KnowledgeChunk.scope == "global") | (
            (KnowledgeChunk.scope == "personal")
            & (KnowledgeChunk.user_id == user_id)
        )

    # D1/G1：HNSW 索引的动态探测参数，随 top_k 放大保证召回率（仅 PG 生效，SQLite 静默忽略）
    if is_postgres():
        db.execute(text("SET LOCAL hnsw.ef_search = :ef"), {"ef": max(40, top_k * 4)})

    # 向量路召回（cosine + HNSW，halfvec 适配 D1.1）
    vec_stmt = (
        select(
            KnowledgeChunk,
            KnowledgeChunk.embedding.cosine_distance(HalfVec(query_vec)).label("distance"),
        )
        .where(scope_filter)
        .order_by("distance")
        .limit(RETRIEVAL_CANDIDATE_POOL)
    )
    vec_rows = db.execute(vec_stmt).all()

    # 关键词路召回（BM25 via tsvector，仅 PG；SQLite 跳过——无 tsvector/GIN 支持）
    kw_rows = []
    if is_postgres():
        tsquery = func.plainto_tsquery('simple', query)
        kw_stmt = (
            select(
                KnowledgeChunk,
                func.ts_rank_cd(KnowledgeChunk.tsv, tsquery).label("rank"),
            )
            .where(KnowledgeChunk.tsv.match(tsquery))
            .where(scope_filter)
            .order_by(text("rank DESC"))
            .limit(RETRIEVAL_CANDIDATE_POOL)
        )
        kw_rows = db.execute(kw_stmt).all()

    # 构建 candidate（G4：content 用 edited_text or chunk.content，weight 读 chunk.weight）
    vec_candidates = []
    for chunk, distance in vec_rows:
        score = 1.0 - distance
        if score < SIMILARITY_THRESHOLD:
            continue
        vec_candidates.append(RetrievalCandidate(
            chunk_id=str(chunk.id),
            content=chunk.edited_text or chunk.content,
            vector_score=score,
            weight=chunk.weight if chunk.weight is not None else 1.0,
            metadata={"_chunk": chunk},
        ))
    kw_candidates = []
    for chunk, rank in kw_rows:
        kw_candidates.append(RetrievalCandidate(
            chunk_id=str(chunk.id),
            content=chunk.edited_text or chunk.content,
            keyword_score=float(rank),
            weight=chunk.weight if chunk.weight is not None else 1.0,
            metadata={"_chunk": chunk},
        ))

    # G3 RRF 融合
    fused = rrf_fuse(vec_results=vec_candidates, kw_results=kw_candidates)

    # 单路兜底（关键词路空或 SQLite 时，RRF 退化为向量路排序）
    if not fused and vec_candidates:
        fused = vec_candidates

    # G4：weight 加权到 fused_score（admin 设的高权重 chunk 排名靠前）
    for c in fused:
        c.fused_score *= c.weight

    # G3 rerank 精排（D5，失败降级）
    rerank_cfg = resolve_rerank_config(db, user_id=user_id)
    if rerank_cfg.enabled and len(fused) > 1:
        docs = [c.content for c in fused[:RETRIEVAL_CANDIDATE_POOL]]
        ranked_docs = rerank(query, docs, config=rerank_cfg)
        content_order = {d: i for i, d in enumerate(ranked_docs)}
        fused = sorted(fused, key=lambda c: content_order.get(c.content, 999))[:top_k]
    else:
        fused = fused[:top_k]

    # 转换为 RetrievalResult（G4：content 用 edited_text）
    results = []
    for cand in fused:
        chunk = cand.metadata.get("_chunk")
        if not chunk:
            continue
        meta = chunk.metadata_ or {}
        results.append(RetrievalResult(
            content=chunk.edited_text or chunk.content,
            score=cand.fused_score or cand.vector_score,
            source_section_key=chunk.source_section_key,
            # 归档类用 project_title,导入类用 title
            project_title=meta.get("project_title") or meta.get("title"),
        ))
    return results
