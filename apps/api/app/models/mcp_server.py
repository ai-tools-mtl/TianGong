# apps/api/app/models/mcp_server.py
"""MCP (Model Context Protocol) server 配置模型（全局作用域）。

admin 配置一组 MCP server（stdio/http/sse），agent 生成时把已启用 server 暴露的
工具加载进 agent 工具列表。凭据（headers/env）逐值加密存储。
详见 spec docs/superpowers/specs/2026-07-30-admin-mcp-config-design.md §2。
"""
import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin

TRANSPORT_STDIO = "stdio"
TRANSPORT_HTTP = "http"
TRANSPORT_SSE = "sse"


class McpServer(Base, IdMixin, TimestampMixin):
    """一条 MCP server 配置。

    - transport 决定使用哪组字段：stdio 用 command+args+env；http/sse 用 url+headers。
    - headers_encrypted / env_encrypted：dict，每个 value 已 encrypt_value。
      API 响应只回 {key: {has_value: true}}，绝不回明文（masking）。
    - enabled=false 的 server 不会被 agent 加载，也不进 resolve_mcp_servers。
    """
    __tablename__ = "mcp_servers"
    __table_args__ = (
        Index("ix_mcp_servers_name", "name", unique=True),
    )

    name: Mapped[str] = mapped_column(String(100))
    transport: Mapped[str] = mapped_column(String(20))  # stdio / http / sse
    command: Mapped[str | None] = mapped_column(String(255), nullable=True)
    args: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    headers_encrypted: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    env_encrypted: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
