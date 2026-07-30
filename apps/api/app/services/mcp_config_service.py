# apps/api/app/services/mcp_config_service.py
"""MCP server 配置服务：CRUD + 凭据逐值加密 + 全局开关 + resolve(解密)。

仿 firecrawl_client / mineru_client 模式。service 拥有事务，失败 rollback。
凭据 masking：to_out 只回 {key: {has_value: bool}}；resolve 返回明文（仅内部用）。
"""
import asyncio
import logging
import uuid
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import decrypt_value, encrypt_value
from app.models import SystemSetting
from app.models.mcp_server import McpServer
from app.schemas.mcp import McpTestResult

logger = logging.getLogger(__name__)

GLOBAL_ENABLED_KEY = "mcp_global_enabled"


# ── 凭据加密/解密工具 ──

def _encrypt_dict(d: dict[str, str] | None) -> dict[str, str] | None:
    """逐值加密。None/空 dict 返回 None。"""
    if not d:
        return None
    return {k: encrypt_value(v) for k, v in d.items()}


def _decrypt_dict(d: dict[str, str] | None) -> dict[str, str]:
    """逐值解密成明文。None → {}。"""
    if not d:
        return {}
    return {k: decrypt_value(v) for k, v in d.items()}


def _mask_dict(d: dict[str, str] | None) -> dict[str, dict] | None:
    """转 masking 形态：{key: {has_value: True}}。None → None。"""
    if not d:
        return None
    return {k: {"has_value": bool(v)} for k, v in d.items()}


def to_out(s: McpServer) -> dict[str, Any]:
    """ORM → 输出 dict（凭据 masking）。显式 str 转换，不依赖 from_attributes。"""
    return {
        "id": str(s.id),
        "name": s.name,
        "transport": s.transport,
        "command": s.command,
        "args": s.args,
        "url": s.url,
        "headers": _mask_dict(s.headers_encrypted),
        "env": _mask_dict(s.env_encrypted),
        "enabled": s.enabled,
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    }


# ── CRUD ──

def create_mcp_server(
    db: Session, *, name: str, transport: str,
    command: str | None = None, args: list[str] | None = None,
    url: str | None = None,
    headers: dict[str, str] | None = None, env: dict[str, str] | None = None,
    enabled: bool = True, actor=None,
) -> McpServer:
    """新建 server。name 唯一性校验。凭据逐值加密。"""
    existing = db.scalar(select(McpServer).where(McpServer.name == name))
    if existing:
        raise ConflictError(f"MCP server 名「{name}」已存在")

    server = McpServer(
        name=name, transport=transport, command=command, args=args, url=url,
        headers_encrypted=_encrypt_dict(headers), env_encrypted=_encrypt_dict(env),
        enabled=enabled, updated_by=actor.id if actor else None,
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    return server


def get_mcp_server(db: Session, *, server_id) -> McpServer:
    sid = uuid.UUID(str(server_id)) if isinstance(server_id, str) else server_id
    server = db.get(McpServer, sid)
    if server is None:
        raise NotFoundError("MCP server 不存在")
    return server


def update_mcp_server(
    db: Session, *, server_id, name: str | None = None,
    transport: str | None = None, command: str | None = None,
    args: list[str] | None = None, url: str | None = None,
    headers: dict[str, str] | None = None, env: dict[str, str] | None = None,
    enabled: bool | None = None, actor=None,
) -> McpServer:
    """更新 server。name 改了做唯一性校验。空字段=保留原值（凭据）。

    transport 变化时清空旧 transport 专属字段，避免脏数据残留（spec §3.2 note）。
    """
    server = get_mcp_server(db, server_id=server_id)

    if name is not None and name != server.name:
        existing = db.scalar(select(McpServer).where(McpServer.name == name))
        if existing:
            raise ConflictError(f"MCP server 名「{name}」已存在")
        server.name = name

    old_transport = server.transport
    new_transport = transport if transport is not None else old_transport
    transport_changed = new_transport != old_transport

    if transport is not None:
        server.transport = transport
    if command is not None:
        server.command = command
    if args is not None:
        server.args = args
    if url is not None:
        server.url = url
    if enabled is not None:
        server.enabled = enabled
    if actor is not None:
        server.updated_by = actor.id

    # 凭据：传了新值才覆盖，空/None 保留旧值
    if headers is not None:
        server.headers_encrypted = _encrypt_dict(headers)
    if env is not None:
        server.env_encrypted = _encrypt_dict(env)

    # transport 切换：清空旧专属字段（避免脏数据残留）
    if transport_changed:
        if new_transport == "stdio":
            server.url = None
            server.headers_encrypted = None
        else:  # http / sse
            server.command = None
            server.args = None
            server.env_encrypted = None

    db.commit()
    db.refresh(server)
    return server


def delete_mcp_server(db: Session, *, server_id) -> None:
    server = get_mcp_server(db, server_id=server_id)
    db.delete(server)
    db.commit()


def list_mcp_servers(db: Session) -> list[McpServer]:
    return list(db.scalars(select(McpServer).order_by(McpServer.created_at.desc())))


# ── 全局开关 ──

def get_mcp_enabled(db: Session) -> bool:
    """读全局开关。未设置时默认 True（与 llm_global_enabled 语义一致）。"""
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == GLOBAL_ENABLED_KEY))
    if row is None:
        return True
    return bool(row.value.get("enabled", True))


def set_mcp_enabled(db: Session, *, enabled: bool, actor=None) -> None:
    """写全局开关（upsert）。"""
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == GLOBAL_ENABLED_KEY))
    if row is None:
        row = SystemSetting(key=GLOBAL_ENABLED_KEY, value={"enabled": enabled},
                            updated_by=actor.id if actor else None)
        db.add(row)
    else:
        row.value = {"enabled": enabled}
        if actor is not None:
            row.updated_by = actor.id
    db.commit()


# ── resolve（解密，供 agent 加载与测试连接，绝不进 API 响应）──

def resolve_mcp_servers(db: Session) -> list[dict[str, Any]]:
    """返回已启用 server 的明文配置列表（headers/env 已解密）。

    全局开关关闭时返回空。仅内部使用，绝不进 API 响应。
    """
    if not get_mcp_enabled(db):
        return []
    rows = list(db.scalars(
        select(McpServer).where(McpServer.enabled.is_(True)).order_by(McpServer.created_at.desc())
    ))
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "transport": s.transport,
            "command": s.command,
            "args": s.args or [],
            "url": s.url,
            "headers": _decrypt_dict(s.headers_encrypted),
            "env": _decrypt_dict(s.env_encrypted),
        }
        for s in rows
    ]


# ── 测试连接 ──

def _to_connection(server_cfg: dict[str, Any]) -> dict[str, Any]:
    """resolve 出的 server 配置 → MultiServerMCPClient 的 connection dict。"""
    transport = server_cfg["transport"]
    if transport == "stdio":
        conn: dict[str, Any] = {
            "transport": "stdio",
            "command": server_cfg["command"],
            "args": server_cfg["args"] or [],
        }
        if server_cfg["env"]:
            conn["env"] = server_cfg["env"]
        return conn
    # http / sse
    conn = {"transport": transport, "url": server_cfg["url"]}
    if server_cfg["headers"]:
        conn["headers"] = server_cfg["headers"]
    return conn


async def _get_server_tools(server_cfg: dict[str, Any]) -> list:
    """对单个 server 起临时 client，拉取工具列表。失败抛异常。"""
    conn = _to_connection(server_cfg)
    client = MultiServerMCPClient({server_cfg["name"]: conn}, tool_name_prefix=True)
    return await client.get_tools()


def test_mcp_server(db: Session, *, server_id, timeout: float = 10.0) -> McpTestResult:
    """测试单个 server 连通性：起临时 client 调 get_tools，返回工具列表。

    临时连接、不持久化、带超时。失败返回 ok=False + error，不抛异常。
    用 asyncio.run 同步化（本函数在同步 admin 路由里调用，无已存在事件循环）。
    """
    server = get_mcp_server(db, server_id=server_id)
    # 构造一个 resolve 形态的 dict（含明文凭据）
    cfg = {
        "id": str(server.id),
        "name": server.name,
        "transport": server.transport,
        "command": server.command,
        "args": server.args or [],
        "url": server.url,
        "headers": _decrypt_dict(server.headers_encrypted),
        "env": _decrypt_dict(server.env_encrypted),
    }
    try:
        tools = asyncio.run(asyncio.wait_for(_get_server_tools(cfg), timeout=timeout))
        names = [getattr(t, "name", str(t)) for t in tools]
        return McpTestResult(ok=True, tool_count=len(names), tool_names=names, error=None)
    except Exception as e:
        logger.warning("MCP server %s 测试连接失败: %s", server.name, e)
        return McpTestResult(ok=False, tool_count=0, tool_names=[], error=str(e)[:300])
