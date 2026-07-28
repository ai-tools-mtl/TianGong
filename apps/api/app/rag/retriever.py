"""检索服务：pgvector 余弦相似 top-K（设计 10.4）。"""

from dataclasses import dataclass

from pgvector.sqlalchemy import HALFVEC as HalfVec
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import is_postgres
from app.models import KnowledgeChunk
from app.rag.embedding import embed_text
from app.services.llm_config_service import resolve_embedding_config
from app.services.llm_log_helper import log_embed_call

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
    """检索与 query 最相似的 chunk（三域 + 解析配置向量化）。

    命中范围：scope=global（全员共享）+ scope=personal 且 user_id=本人。
    不命中他人 personal（严格隔离，关键约束 1）。

    向量化配置由 user_id 内部解析（断链修复：embed 真用自定义/全局/env 配置）。
    无可用配置时返回空结果（检索不可用，调用方按空结果处理）。
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

    # D1/G1：HNSW 索引的动态探测参数，随 top_k 放大保证召回率（仅 PG 生效，SQLite 静默忽略）
    if is_postgres():
        db.execute(text("SET LOCAL hnsw.ef_search = :ef"), {"ef": max(40, top_k * 4)})

    # D1.1 halfvec —— query_vec 转成 HalfVec 类型与列类型对齐
    stmt = (
        select(
            KnowledgeChunk,
            KnowledgeChunk.embedding.cosine_distance(HalfVec(query_vec)).label("distance"),
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
