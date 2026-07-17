"""LLM 调用统计聚合（设计 8.2④ + 8.3 红线：只返回元数据聚合，不碰内容）。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import LLMCallLog, User


def get_llm_stats(db: Session, *, days: int = 7) -> dict:
    """聚合近 N 天 LLM 调用。

    返回结构（全部为元数据聚合，无 prompt/completion 内容）：
    {
      "days": 7,
      "total_calls": int,
      "total_success": int,
      "total_failed": int,
      "avg_duration_ms": float | None,
      "total_prompt_tokens": int,       # 断链 C3：token_prompt 之和（None 计 0）
      "total_completion_tokens": int,   # 断链 C3：token_completion 之和（None 计 0）
      "by_model": [{"model","calls","success","failed","avg_duration_ms",
                    "prompt_tokens","completion_tokens"}],
      "by_user": [{"user_id","email","calls","success","failed"}],
    }
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 顶层汇总
    top = db.execute(
        select(
            func.count(LLMCallLog.id).label("total_calls"),
            func.sum(case((LLMCallLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((LLMCallLog.status != "success", 1), else_=0)).label("failed"),
            func.avg(LLMCallLog.duration_ms).label("avg_duration"),
            # 断链 C3：token 用量聚合（NULL 视作 0，不影响求和）
            func.sum(func.coalesce(LLMCallLog.token_prompt, 0)).label("prompt_tokens"),
            func.sum(func.coalesce(LLMCallLog.token_completion, 0)).label("completion_tokens"),
        ).where(LLMCallLog.created_at >= since)
    ).one()
    total_calls = top.total_calls or 0
    total_success = int(top.success or 0)
    total_failed = int(top.failed or 0)
    avg_duration = float(top.avg_duration) if top.avg_duration is not None else None
    total_prompt_tokens = int(top.prompt_tokens or 0)
    total_completion_tokens = int(top.completion_tokens or 0)

    # 按 model 聚合
    model_rows = db.execute(
        select(
            LLMCallLog.model.label("model"),
            func.count(LLMCallLog.id).label("calls"),
            func.sum(case((LLMCallLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((LLMCallLog.status != "success", 1), else_=0)).label("failed"),
            func.avg(LLMCallLog.duration_ms).label("avg_duration"),
            func.sum(func.coalesce(LLMCallLog.token_prompt, 0)).label("prompt_tokens"),
            func.sum(func.coalesce(LLMCallLog.token_completion, 0)).label("completion_tokens"),
        )
        .where(LLMCallLog.created_at >= since)
        .group_by(LLMCallLog.model)
        .order_by(func.count(LLMCallLog.id).desc())
    ).all()
    by_model = [
        {
            "model": r.model,
            "calls": int(r.calls or 0),
            "success": int(r.success or 0),
            "failed": int(r.failed or 0),
            "avg_duration_ms": float(r.avg_duration) if r.avg_duration is not None else None,
            "prompt_tokens": int(r.prompt_tokens or 0),
            "completion_tokens": int(r.completion_tokens or 0),
        }
        for r in model_rows
    ]

    # 按用户聚合（user_id LEFT JOIN users 取 email；user_id 为 null 归到 anonymous）
    user_rows = db.execute(
        select(
            LLMCallLog.user_id.label("user_id"),
            User.email.label("email"),
            func.count(LLMCallLog.id).label("calls"),
            func.sum(case((LLMCallLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((LLMCallLog.status != "success", 1), else_=0)).label("failed"),
        )
        .select_from(LLMCallLog)
        .outerjoin(User, User.id == LLMCallLog.user_id)
        .where(LLMCallLog.created_at >= since)
        .group_by(LLMCallLog.user_id, User.email)
        .order_by(func.count(LLMCallLog.id).desc())
    ).all()
    by_user = [
        {
            "user_id": str(r.user_id) if r.user_id is not None else None,
            "email": r.email or "(anonymous)",
            "calls": int(r.calls or 0),
            "success": int(r.success or 0),
            "failed": int(r.failed or 0),
        }
        for r in user_rows
    ]

    return {
        "days": days,
        "total_calls": total_calls,
        "total_success": total_success,
        "total_failed": total_failed,
        "avg_duration_ms": avg_duration,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "by_model": by_model,
        "by_user": by_user,
    }
