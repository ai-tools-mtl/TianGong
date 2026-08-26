"""LLM 调用统计聚合（设计 8.2④ + 8.3 红线：只返回元数据聚合，不碰内容）。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import LLMCallLog, User, UserGlobalLLMGrant

# 落地页 LLM 健康卡判定阈值：近 7 天失败率 <= 5% 视为健康。
# 模块级常量方便后续挪到 config；当前由 admin 落地页使用（plan refactor/admin-ia-phase1）。
LLM_HEALTH_FAILURE_THRESHOLD = 0.05


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
      "by_user": [{"user_id","email","calls","success","failed",
                   "prompt_tokens","completion_tokens"}],
      "by_day": [{"date","calls","failed","prompt_tokens","completion_tokens"}],  # 升序、缺天补零
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
            func.sum(func.coalesce(LLMCallLog.token_prompt, 0)).label("prompt_tokens"),
            func.sum(func.coalesce(LLMCallLog.token_completion, 0)).label("completion_tokens"),
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
            "prompt_tokens": int(r.prompt_tokens or 0),
            "completion_tokens": int(r.completion_tokens or 0),
        }
        for r in user_rows
    ]

    # 按天聚合（趋势图用）。D1：func.date 双方言通用（SQLite date() / PG date(timestamptz)），
    # 不用 date_trunc（PG 专有）。日界按 UTC——与 UTC+8 有几小时偏移，趋势用途可接受。
    day_rows = db.execute(
        select(
            func.date(LLMCallLog.created_at).label("day"),
            func.count(LLMCallLog.id).label("calls"),
            func.sum(case((LLMCallLog.status != "success", 1), else_=0)).label("failed"),
            func.sum(func.coalesce(LLMCallLog.token_prompt, 0)).label("prompt_tokens"),
            func.sum(func.coalesce(LLMCallLog.token_completion, 0)).label("completion_tokens"),
        )
        .where(LLMCallLog.created_at >= since)
        .group_by(func.date(LLMCallLog.created_at))
        .order_by(func.date(LLMCallLog.created_at))
    ).all()
    # 归一化 key：PG 返回 datetime.date，SQLite 返回 "YYYY-MM-DD" 字符串，str() 后一致
    day_map = {str(r.day): r for r in day_rows}
    today = datetime.now(timezone.utc).date()
    by_day = []
    for offset in range(days - 1, -1, -1):
        key = (today - timedelta(days=offset)).isoformat()
        r = day_map.get(key)
        by_day.append({
            "date": key,
            "calls": int(r.calls or 0) if r else 0,
            "failed": int(r.failed or 0) if r else 0,
            "prompt_tokens": int(r.prompt_tokens or 0) if r else 0,
            "completion_tokens": int(r.completion_tokens or 0) if r else 0,
        })

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
        "by_day": by_day,
    }


def get_llm_health(db: Session, *, days: int = 7) -> dict:
    """近 N 天 LLM 调用健康摘要（admin 落地页 LLM 健康卡片用）。

    返回结构（聚合数字 + 健康判定，无内容）：
    {
      "days": 7,
      "total": int,
      "failed": int,
      "failure_rate": float,   # 0.0~1.0，total=0 时为 0.0
      "status": "ok"|"warning", # failure_rate <= LLM_HEALTH_FAILURE_THRESHOLD → ok
    }

    失败聚合口径与 get_llm_stats 一致：status != "success" 全计为 failed。
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    row = db.execute(
        select(
            func.count(LLMCallLog.id).label("total"),
            func.sum(case((LLMCallLog.status != "success", 1), else_=0)).label("failed"),
        ).where(LLMCallLog.created_at >= since)
    ).one()
    total = int(row.total or 0)
    failed = int(row.failed or 0)
    failure_rate = failed / total if total > 0 else 0.0
    status = "ok" if failure_rate <= LLM_HEALTH_FAILURE_THRESHOLD else "warning"
    return {
        "days": days,
        "total": total,
        "failed": failed,
        "failure_rate": failure_rate,
        "status": status,
    }


def get_user_stats(db: Session) -> dict:
    """用户聚合统计（用于 admin 仪表盘卡片，Task 3.1）。

    返回：total/active/disabled/new_7d/new_30d/granted_count。
    全部为聚合数字，无私人数据（设计 8.3 红线）。
    """
    now = datetime.now(timezone.utc)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    # 总数/活跃/禁用
    status_counts = db.execute(
        select(User.status, func.count(User.id)).group_by(User.status)
    ).all()
    by_status = {row[0]: int(row[1]) for row in status_counts}
    total = sum(by_status.values())
    active = by_status.get("active", 0)
    disabled = by_status.get("disabled", 0)

    # 新增（按 created_at）
    new_7d = int(db.scalar(select(func.count(User.id)).where(User.created_at >= since_7d)) or 0)
    new_30d = int(db.scalar(select(func.count(User.id)).where(User.created_at >= since_30d)) or 0)

    # 有效授权用户数（granted_count）：revoked_at 为空
    granted_count = int(db.scalar(
        select(func.count(UserGlobalLLMGrant.id)).where(UserGlobalLLMGrant.revoked_at.is_(None))
    ) or 0)

    return {
        "total": total,
        "active": active,
        "disabled": disabled,
        "new_7d": new_7d,
        "new_30d": new_30d,
        "granted_count": granted_count,
    }
