"""管理员 API + 用户 LLM 设置 API（设计 8.2/8.4）。"""

import uuid as _uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user, require_admin
from app.models import AuditLog, Project, User, UserGlobalLLMGrant, UserLLMConfig
from app.services import admin_service, llm_config_service, stats_service

router = APIRouter(tags=["admin"])


# ── 管理员：用户列表（聚合信息，不含私人数据，设计 8.3 红线）──

@router.get("/admin/users")
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户列表（仅聚合信息：邮箱/角色/状态/项目数/是否自配key/是否被全局授权）。"""
    users = list(db.scalars(select(User).order_by(User.created_at.desc())))
    # 一次性取出所有有效授权（revoked_at is null）的 user_id，避免 N+1。
    active_grant_ids = set(db.scalars(
        select(UserGlobalLLMGrant.user_id).where(UserGlobalLLMGrant.revoked_at.is_(None))
    ))
    result = []
    for u in users:
        project_count = db.scalar(
            select(func.count(Project.id)).where(Project.user_id == u.id)
        )
        has_own_key = db.scalar(
            select(func.count(UserLLMConfig.id)).where(UserLLMConfig.user_id == u.id)
        )
        result.append({
            "id": str(u.id),
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "status": u.status,
            "project_count": project_count or 0,
            "has_own_llm_key": (has_own_key or 0) > 0,
            "has_global_grant": u.id in active_grant_ids,
            "created_at": u.created_at.isoformat(),
        })
    return result


# ── 管理员：用户运营（封禁/解禁/重置密码，设计 8.1）──

class UserStatusUpdate(BaseModel):
    status: str  # active / disabled


class PasswordReset(BaseModel):
    new_password: str


@router.patch("/admin/users/{user_id}/status")
def update_user_status(
    user_id: str,
    payload: UserStatusUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """封禁/解禁用户。自我保护在 service 层强制。"""
    target = admin_service.set_user_status(
        db, actor=admin, user_id=_uuid.UUID(user_id), status=payload.status,
    )
    return {"id": str(target.id), "status": target.status}


@router.post("/admin/users/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    payload: PasswordReset,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """重置用户密码（管理员线下告知，不返回敏感信息）。"""
    admin_service.reset_user_password(
        db, actor=admin, user_id=_uuid.UUID(user_id), new_password=payload.new_password,
    )
    return {"ok": True}


# ── 管理员：全局 Key 授权（Task 2.2）──

@router.get("/admin/users/{user_id}/global-llm-grant")
def get_user_grant(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查用户的全局 Key 授权状态。无记录返回 {is_active: False}。"""
    return admin_service.get_user_grant(db, user_id=_uuid.UUID(user_id)) or {"is_active": False}


@router.post("/admin/users/{user_id}/global-llm-grant")
def grant_global_llm(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """授权用户使用全局 Key。幂等：已有则清 revoked_at 重新激活。自我保护在 service 层强制。"""
    admin_service.grant_global_llm_access(db, actor=admin, user_id=_uuid.UUID(user_id))
    return {"message": "已授权"}


@router.delete("/admin/users/{user_id}/global-llm-grant")
def revoke_global_llm(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """撤销用户的全局 Key 授权。写 revoked_at（保留行审计）。无记录则 no-op。"""
    admin_service.revoke_global_llm_access(db, actor=admin, user_id=_uuid.UUID(user_id))
    return {"message": "已撤销"}


# ── 管理员：LLM 调用统计（设计 8.2④，仅元数据聚合）──

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


# ── 管理员：审计日志列表（设计 8.2⑤）──

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


# ── 管理员：全局 LLM 配置 ──

class GlobalLLMSettings(BaseModel):
    enabled: bool
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    embedding_model: str | None = None
    allowed_models: list[str] | None = None


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


# ── 用户：自有 LLM 配置（BYOK 多配置 CRUD，Task 2.3）──

class UserLLMCreateRequest(BaseModel):
    """新增 BYOK 配置。name 为配置名（如「公司Key」）。"""
    name: str
    provider: str = "custom"
    base_url: str
    api_key: str
    model: str
    embedding_model: str | None = None


class UserLLMUpdateRequest(BaseModel):
    """修改 BYOK 配置。所有字段可选，仅提供才更新（api_key 留空则不变）。"""
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    embedding_model: str | None = None


class UserLLMTestRequest(BaseModel):
    """测试 LLM 连通性（不落库）。"""
    provider: str = "custom"
    base_url: str
    api_key: str
    model: str
    embedding_model: str | None = None


@router.get("/settings/llm")
def get_my_llm(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的所有 BYOK 配置（key 掩码）。空时返回 []。"""
    return llm_config_service.list_user_llm_configs(db, user_id=current_user.id)


@router.post("/settings/llm")
def create_my_llm(
    payload: UserLLMCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新增一条 BYOK 配置。返回新建的配置（含 id，key 掩码）。"""
    cfg = llm_config_service.create_user_llm_config(
        db, user_id=current_user.id,
        name=payload.name, provider=payload.provider, base_url=payload.base_url,
        api_key=payload.api_key, model=payload.model,
        embedding_model=payload.embedding_model,
    )
    return llm_config_service.config_to_dict(cfg)


@router.put("/settings/llm/{config_id}")
def update_my_llm(
    config_id: str,
    payload: UserLLMUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改指定 BYOK 配置（校验归属，越权/不存在 404，防探测）。"""
    cfg = llm_config_service.update_user_llm_config(
        db, user_id=current_user.id, config_id=config_id,
        name=payload.name, provider=payload.provider, base_url=payload.base_url,
        api_key=payload.api_key, model=payload.model,
        embedding_model=payload.embedding_model,
    )
    return llm_config_service.config_to_dict(cfg)


@router.delete("/settings/llm/{config_id}")
def delete_my_llm(
    config_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除指定 BYOK 配置（校验归属，越权/不存在 404）。"""
    llm_config_service.delete_user_llm_config(
        db, user_id=current_user.id, config_id=config_id,
    )
    return {"message": "已删除"}


@router.post("/settings/llm/test")
def test_my_llm(
    payload: UserLLMTestRequest,
    current_user: User = Depends(get_current_user),
):
    """测试 LLM 连通性（不存库，直接用传入配置测试）。"""
    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=payload.model,
            base_url=payload.base_url,
            api_key=payload.api_key,
        )
        resp = llm.invoke([HumanMessage(content="hi")])
        return {"ok": True, "response": resp.content[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
