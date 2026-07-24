"""用户：自有 LLM 配置（自定义 LLM 配置多配置 CRUD + 选源，/settings/*）。

从原 admin.py 拆出（refactor/admin-api-split）。语义属用户域（普通用户的自定义 LLM 配置），
非管理员域。权限是 get_current_user（任何登录用户）。
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import admin_service, llm_config_service

router = APIRouter(tags=["admin"])  # tag 保持 admin 与原一致，避免 OpenAPI 文档分组变化


class UserLLMCreateRequest(BaseModel):
    """新增自定义 LLM 配置。name 为配置名（如「公司Key」）。"""
    name: str
    provider: str = "custom"
    base_url: str
    api_key: str
    # 1214 修复闸 3：model 必填且非空，防止存入空 model 触发智谱 1214。
    model: str = Field(..., min_length=1)
    embedding_model: str | None = None


class UserLLMUpdateRequest(BaseModel):
    """修改自定义 LLM 配置。所有字段可选，仅提供才更新（api_key 留空则不变）。"""
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    # model 可选更新：None=不改。不强制 min_length（否则无法表达"不改 model"），
    # 空 model 由闸 1（get_llm）/闸 2（global 解析）兜底拦截。
    model: str | None = None
    embedding_model: str | None = None


class UserLLMTestRequest(BaseModel):
    """测试 LLM 连通性（不落库）。chat 必测；embedding_model 提供则一并测。"""
    base_url: str
    api_key: str
    # 1214 修复闸 3：测试连通性也必须有 model（无 model 必报 1214）。
    model: str = Field(..., min_length=1)
    embedding_model: str | None = None


class ListModelsRequest(BaseModel):
    """拉取 provider 可用模型列表（不落库）。"""
    base_url: str
    api_key: str
    provider_template_id: str | None = None


@router.get("/settings/llm")
def get_my_llm(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的所有自定义配置（key 掩码）。空时返回 []。"""
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


@router.get("/settings/llm/templates")
def list_llm_templates(current_user: User = Depends(get_current_user)):
    """返回 provider 模板预设列表（添加配置时选模板自动填）。"""
    from app.services.llm_provider_templates import PROVIDER_TEMPLATES
    return [
        {
            "id": t.id, "name": t.name, "base_url": t.base_url,
            "default_model": t.default_model,
            "default_embedding_model": t.default_embedding_model,
            "models_endpoint": t.models_endpoint,
            "docs_url": t.docs_url, "note": t.note,
        }
        for t in PROVIDER_TEMPLATES
    ]


@router.post("/settings/llm/models")
def list_my_provider_models(
    payload: ListModelsRequest,
    current_user: User = Depends(get_current_user),
):
    """拉取 provider 可用模型列表（不落库）。"""
    return llm_config_service.list_provider_models(
        base_url=payload.base_url, api_key=payload.api_key,
        provider_template_id=payload.provider_template_id,
    )


@router.post("/settings/llm")
def create_my_llm(
    payload: UserLLMCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新增一条自定义配置。返回新建的配置（含 id，key 掩码）。"""
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
    """修改指定自定义配置（校验归属，越权/不存在 404，防探测）。"""
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
    """删除指定自定义配置（校验归属，越权/不存在 404）。"""
    llm_config_service.delete_user_llm_config(
        db, user_id=current_user.id, config_id=config_id,
    )
    return {"message": "已删除"}


@router.post("/settings/llm/test")
def test_my_llm(
    payload: UserLLMTestRequest,
    current_user: User = Depends(get_current_user),
):
    """测试 LLM 连通性（不存库，直接用传入配置测试 chat + 可选 embedding）。"""
    return llm_config_service.test_llm_connection(
        base_url=payload.base_url, api_key=payload.api_key,
        model=payload.model, embedding_model=payload.embedding_model,
    )
