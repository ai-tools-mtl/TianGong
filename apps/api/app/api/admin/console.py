"""管理员：系统控制台域（/admin/llm-config + /admin/stats/* + /admin/audit-logs）。

从原 admin.py 拆出（refactor/admin-api-split）。包含：
- GET  /admin/llm-config         全局 LLM 配置
- PUT  /admin/llm-config         保存全局 LLM 配置（写审计）
- GET  /admin/stats/llm          LLM 调用统计聚合
- GET  /admin/stats/llm/health   LLM 健康摘要（落地页用）
- GET  /admin/stats/users        用户聚合统计
- GET  /admin/audit-logs         审计日志分页
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import AuditLog, User
from app.services import admin_service, llm_config_service, stats_service

router = APIRouter(tags=["admin"])


class GlobalLLMSettings(BaseModel):
    enabled: bool
    base_url: str | None = None
    api_key: str | None = None
    # 1214 修复闸 3：model 可选（不更新时不传），但给了就必须非空，
    # 防止 admin 漏填 model 存入空串 → 后续触发智谱 1214。
    model: str | None = Field(default=None, min_length=1)
    embedding_model: str | None = None
    allowed_models: list[str] | None = None


# ── LLM 调用统计（设计 8.2④，仅元数据聚合）──

@router.get("/admin/stats/llm")
def get_llm_stats_endpoint(
    days: int = 7,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """LLM 调用统计聚合（绝不返回 prompt/completion 内容）。"""
    if days < 1 or days > 90:
        days = 7
    return stats_service.get_llm_stats(db, days=days)


@router.get("/admin/stats/llm/health")
def get_llm_health_endpoint(
    days: int = 7,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """LLM 调用健康摘要（admin 落地页 LLM 健康卡片用）。

    返回 {days, total, failed, failure_rate, status}。阈值由
    stats_service.LLM_HEALTH_FAILURE_THRESHOLD（当前 5%）决定 status=ok/warning。
    """
    if days < 1 or days > 90:
        days = 7
    return stats_service.get_llm_health(db, days=days)


@router.get("/admin/stats/users")
def get_user_stats_endpoint(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户聚合统计（仪表盘卡片用：总数/活跃/禁用/新增/有效授权数）。"""
    return stats_service.get_user_stats(db)


# ── 审计日志列表（设计 8.2⑤）──

@router.get("/admin/audit-logs")
def list_audit_logs(
    page: int = 1,
    size: int = 50,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """审计日志列表（分页，时间倒序）。"""
    if page < 1:
        page = 1
    if size < 1 or size > 200:
        size = 50

    total = db.scalar(select(func.count(AuditLog.id))) or 0
    rows = list(db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ))
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": str(r.id),
                "actor_id": str(r.actor_id) if r.actor_id else None,
                "actor_username": r.actor_username,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ── 全局 LLM 配置 ──

@router.get("/admin/llm-config")
def get_global_llm(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return llm_config_service.get_global_llm_settings(db)


@router.put("/admin/llm-config")
def set_global_llm(
    payload: GlobalLLMSettings,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = llm_config_service.set_global_llm_settings(
        db, enabled=payload.enabled,
        base_url=payload.base_url, api_key=payload.api_key, model=payload.model,
        embedding_model=payload.embedding_model, allowed_models=payload.allowed_models,
    )
    # 审计：detail 只记非敏感字段，绝不传 api_key 明文（设计 8.3 脱敏）
    admin_service._audit(
        db,
        actor=admin,
        action="set_global_llm",
        target_type="system_setting",
        target_id="llm_global_config",
        detail={
            "enabled": payload.enabled,
            "base_url": payload.base_url,
            "model": payload.model,
            "embedding_model": payload.embedding_model,
            "allowed_models": payload.allowed_models,
        },
    )
    return result
