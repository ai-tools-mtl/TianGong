"""LLM 调用日志共享 helper（供 chat 端点与 embedding caller 共用）。

embedding caller（archiver / retriever / knowledge_service）调完 embed 后写一条
action="embed" 的日志，让 admin 调用统计能区分 chat / embedding（D7）。
仅存元数据（model / provider / status），绝不存内容（设计 8.3 红线）。

健壮性红线：日志失败绝不能影响 embedding 主流程。helper 内部 try/except + rollback，
任何异常（含瞬态 DB 错误）都被吞掉——embed 已成功就让它成功。
"""

from sqlalchemy.orm import Session

from app.models import LLMCallLog


def log_embed_call(
    db: Session, *,
    user_id,
    model: str,
    provider: str,
    status: str = "success",
    duration_ms: int | None = None,
    error: str | None = None,
    project_id=None,
) -> None:
    """写一条 embedding 调用元数据日志。失败不抛（日志不应影响主流程）。

    embed 调用本身已在上层完成；本函数只补一条观测日志。即便写库失败
    （如瞬态 DB 错误），embed 的业务结果不应回退——故 try/except + rollback。
    """
    try:
        db.add(LLMCallLog(
            user_id=user_id,
            project_id=project_id,
            action="embed",
            model=model,
            provider=provider,
            status=status,
            duration_ms=duration_ms,
            error=error,
        ))
        db.commit()
    except Exception:
        # 日志失败不影响主流程；回滚避免污染 session
        db.rollback()


def log_firecrawl_call(
    db: Session, *,
    user_id,
    mode: str,
    pages: int,
    source: str = "global",
    status: str = "success",
) -> None:
    """写一条 Firecrawl 调用元数据日志。失败不抛(日志不应影响主流程)。

    pages 存在 token_completion 字段(语义复用:Firecrawl 无 token 概念,
    借该字段记页数;配额查询按 action='firecrawl' 聚合 SUM)。
    pages 可为负(退款/校正)。

    spec: docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 3 节。
    """
    try:
        db.add(LLMCallLog(
            user_id=user_id,
            action="firecrawl",
            model=f"firecrawl-{mode}",   # scrape/crawl
            provider=source,             # global/env
            token_completion=pages,
            status=status,
        ))
        db.commit()
    except Exception:
        db.rollback()
