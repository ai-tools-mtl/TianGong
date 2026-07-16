"""检索服务：pgvector 余弦相似 top-K（设计 10.4）。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk
from app.rag.embedding import embed_text
from app.services.llm_config_service import resolve_llm_config

SIMILARITY_THRESHOLD = 0.5


@dataclass
class RetrievalResult:
    content: str
    score: float
    source_section_key: str | None
    project_title: str | None


def retrieve(
    db: Session, *, user_id, query: str, top_k: int = 3
) -> list[RetrievalResult]:
    """检索用户知识库中与 query 最相似的 chunk。

    向量化配置由 user_id 内部解析（断链修复：embed 真用 BYOK/全局配置）。
    无可用配置时返回空结果（检索不可用，调用方按空结果处理）。
    """
    embed_config = resolve_llm_config(db, user_id=user_id)
    if embed_config is None:
        return []
    query_vec = embed_text(query, embed_config=embed_config)

    stmt = (
        select(
            KnowledgeChunk,
            KnowledgeChunk.embedding.cosine_distance(query_vec).label("distance"),
        )
        .where(KnowledgeChunk.user_id == user_id)
        .order_by("distance")
        .limit(top_k)
    )
    rows = db.execute(stmt).all()

    results = []
    for chunk, distance in rows:
        score = 1.0 - distance
        if score < SIMILARITY_THRESHOLD:
            continue
        results.append(RetrievalResult(
            content=chunk.content,
            score=score,
            source_section_key=chunk.source_section_key,
            project_title=chunk.metadata_.get("project_title") if chunk.metadata_ else None,
        ))
    return results
