# apps/api/app/schemas/mcp.py
"""MCP server schemas（CRUD + 全局开关 + 测试结果）。

凭据 masking：API 响应中 headers/env 形如 {key: {has_value: bool}}，绝不回明文。
"""
from pydantic import BaseModel, Field


class McpServerBase(BaseModel):
    name: str = Field(..., max_length=100, description="唯一标识")
    transport: str = Field(..., pattern="^(stdio|http|sse)$")
    command: str | None = Field(None, max_length=255, description="stdio 专用")
    args: list[str] | None = Field(None, description="stdio 专用，参数数组")
    url: str | None = Field(None, max_length=500, description="http/sse 专用")
    headers: dict[str, str] | None = Field(None, description="http/sse 凭据（明文，仅写）")
    env: dict[str, str] | None = Field(None, description="stdio 环境变量（明文，仅写）")
    enabled: bool = True


class McpServerCreate(McpServerBase):
    """创建 server。"""


class McpServerUpdate(BaseModel):
    """更新 server（全 Optional，partial）。空字段=不改。"""
    name: str | None = Field(None, max_length=100)
    transport: str | None = Field(None, pattern="^(stdio|http|sse)$")
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    env: dict[str, str] | None = None
    enabled: bool | None = None


class McpServerOut(BaseModel):
    """server 输出（列表 + 详情共用）。

    headers/env 返回 {key: {has_value: bool}} 形态（masking）。
    """
    model_config = {"from_attributes": True}

    id: str
    name: str
    transport: str
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, dict] | None = None
    env: dict[str, dict] | None = None
    enabled: bool
    created_at: str
    updated_at: str


class McpGlobalEnabled(BaseModel):
    enabled: bool


class McpTestResult(BaseModel):
    ok: bool
    tool_count: int
    tool_names: list[str]
    error: str | None = None
