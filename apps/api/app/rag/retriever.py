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
    """检索与 query 最相似的 chunk(三域,关键约束 1)。

    命中范围:scope=global(全员共享)+ scope=personal 且 user_id=本人。
    不命中他人 personal(严格隔离)。
    """
    query_vec = embed_text(query)

    stmt = (
        select(
            KnowledgeChunk,
            KnowledgeChunk.embedding.cosine_distance(query_vec).label("distance"),
        )
        .where(
            (KnowledgeChunk.scope == "global")
            | (
                (KnowledgeChunk.scope == "personal")
                & (KnowledgeChunk.user_id == user_id)
            )
        )
        .order_by("distance")
        .limit(top_k)
    )
    rows = db.execute(stmt).all()

    results = []
    for chunk, distance in rows:
        score = 1.0 - distance
        if score < SIMILARITY_THRESHOLD:
            continue
        meta = chunk.metadata_ or {}
        results.append(RetrievalResult(
            content=chunk.content,
            score=score,
            source_section_key=chunk.source_section_key,
            # 归档类用 project_title,导入类用 title
            project_title=meta.get("project_title") or meta.get("title"),
        ))
    return results
