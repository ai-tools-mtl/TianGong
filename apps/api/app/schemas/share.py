"""协作系统 API 请求/响应模型（计划 17）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


# ── 成员 ──

class MemberAdd(BaseModel):
    """添加成员请求（按邮箱）。"""
    email: EmailStr


class MemberOut(BaseModel):
    """成员响应（含用户基本信息，避免前端二次查询）。"""
    id: str
    project_id: str
    user_id: str
    email: str
    name: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 分享链接 ──

class ShareLinkCreate(BaseModel):
    """创建分享链接请求。"""
    permissions: Literal["comment", "readonly"] = "comment"
    # None 或 <=0 表示永不过期
    expires_days: int | None = Field(default=None, ge=1, le=365)


class ShareLinkOut(BaseModel):
    """分享链接响应。"""
    id: str
    project_id: str
    token: str
    permissions: str
    expires_at: datetime | None = None
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 公开端点响应 ──

class SharedInfo(BaseModel):
    """GET /shared/{token} 公开端点响应：项目标题 + 权限 + collabora 访问信息。"""
    title: str
    permissions: str
    project_id: str
    # 前端用此 token 调 /shared/{token}/collabora-url（保持与 token 一致）
    share_token: str
