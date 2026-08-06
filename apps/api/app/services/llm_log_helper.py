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
    （如瞬态 DB 错误），embed 的业务结果不应回退。

    事务边界（P3-10 修复）：用 SAVEPOINT（begin_nested）写日志，不调 db.commit()。
    此前直接 db.commit() 会把调用方 session 里未提交的业务数据（如 archiver 的
    chunk 写入）一起提前 flush，破坏事务原子性。SAVEPOINT 失败只回滚到 savepoint，
    不影响外层事务；外层由调用方统一 commit。
    """
    try:
        with db.begin_nested():
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
    except Exception:
        # 日志失败不影响主流程；begin_nested 已回滚 savepoint，session 仍可用
        pass


def log_chat_call(
    db: Session, *,
    user_id,
    action: str,
    model: str,
    provider: str,
    status: str = "success",
    tokens: dict | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
    project_id=None,
) -> None:
    """写一条 chat 类 LLM 调用元数据日志（供 figure 等同步 LLM 调用复用）。

    与 ai.py 内的 _log_llm_call 等价，但放共享层供非 chat 端点（如 figure 生成）
    复用，避免跨 router 调私有函数。仅存元数据（设计 8.3 红线），失败不抛。

    事务边界：同 log_embed_call，用 SAVEPOINT（begin_nested）隔离，不提前 commit。
    """
    try:
        with db.begin_nested():
            db.add(LLMCallLog(
                user_id=user_id,
                project_id=project_id,
                action=action,
                model=model,
                provider=provider,
                token_prompt=tokens.get("prompt") if tokens else None,
                token_completion=tokens.get("completion") if tokens else None,
                duration_ms=duration_ms,
                status=status,
                error=(str(error)[:500] if error else None),
            ))
    except Exception:
        pass


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

    事务边界：同 log_embed_call，用 SAVEPOINT 隔离，不提前 commit 外层数据。
    """
    try:
        with db.begin_nested():
            db.add(LLMCallLog(
                user_id=user_id,
                action="firecrawl",
                model=f"firecrawl-{mode}",   # scrape/crawl
                provider=source,             # global/env
                token_completion=pages,
                status=status,
            ))
    except Exception:
        pass
