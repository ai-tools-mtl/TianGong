"""检索服务：pgvector 余弦相似 top-K（设计 10.4）。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk
from app.rag.embedding import embed_text

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
    """检索用户知识库中与 query 最相似的 chunk。"""
    query_vec = embed_text(query)

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
