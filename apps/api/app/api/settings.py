"""用户：自有 LLM 配置（BYOK 多配置 CRUD + 选源，/settings/*）。

从原 admin.py 拆出（refactor/admin-api-split）。语义属用户域（普通用户的 BYOK），
非管理员域。权限是 get_current_user（任何登录用户）。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import admin_service, llm_config_service

router = APIRouter(tags=["admin"])  # tag 保持 admin 与原一致，避免 OpenAPI 文档分组变化


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


@router.get("/settings/my-grant")
def get_my_grant(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """普通用户查自己的全局 Key 授权状态（选源器用）。

    复用 admin_service.get_user_grant（Task 2.2）。无记录返回 {is_active: False}。
    注：admin 角色免授权，但本端点仍如实返回其 grant 行（若无行则 is_active=False）；
    选源器前端对 admin 始终展示「全局 Key」选项（admin 走 source=global 免授权路径）。
    """
    return admin_service.get_user_grant(db, user_id=current_user.id) or {"is_active": False}


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
