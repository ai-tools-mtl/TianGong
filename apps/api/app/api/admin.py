"""管理员 API + 用户 LLM 设置 API（设计 8.2/8.4）。"""

import uuid as _uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user, require_admin
from app.models import Project, User, UserLLMConfig
from app.services import admin_service, llm_config_service

router = APIRouter(tags=["admin"])


# ── 管理员：用户列表（聚合信息，不含私人数据，设计 8.3 红线）──

@router.get("/admin/users")
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户列表（仅聚合信息：邮箱/角色/状态/项目数/是否自配key）。"""
    users = list(db.scalars(select(User).order_by(User.created_at.desc())))
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


# ── 管理员：全局 LLM 配置 ──

class GlobalLLMSettings(BaseModel):
    enabled: bool
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


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
        },
    )
    return result


# ── 用户：自有 LLM 配置（BYOK）──

class UserLLMRequest(BaseModel):
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
    """获取当前用户的 LLM 配置（掩码 key）。"""
    return llm_config_service.get_user_llm_config(db, user_id=current_user.id)


@router.put("/settings/llm")
def set_my_llm(
    payload: UserLLMRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """设置/更新用户自有 LLM 配置。"""
    llm_config_service.set_user_llm_config(
        db, user_id=current_user.id,
        provider=payload.provider, base_url=payload.base_url,
        api_key=payload.api_key, model=payload.model,
        embedding_model=payload.embedding_model,
    )
    return {"message": "LLM 配置已更新"}


@router.delete("/settings/llm")
def delete_my_llm(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    llm_config_service.delete_user_llm_config(db, user_id=current_user.id)
    return {"message": "已清除，将使用全局配置"}


@router.post("/settings/llm/test")
def test_my_llm(
    payload: UserLLMRequest,
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
