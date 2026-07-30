# apps/api/app/api/admin/mcp.py
"""admin MCP server 管理路由（/admin/mcp/*）。

仿 admin/skills.py（CRUD）+ admin/console.py（测试连接 + 全局开关）。
每个 handler 挂 require_admin。写操作记审计（detail 不含凭据明文）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import User
from app.schemas.mcp import (
    McpGlobalEnabled, McpServerCreate, McpServerOut, McpServerUpdate, McpTestResult,
)
from app.services import admin_service, mcp_config_service as svc

router = APIRouter(tags=["admin"])


# ── CRUD ──

@router.get("/admin/mcp/servers", response_model=list[McpServerOut])
def list_servers(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [McpServerOut(**svc.to_out(s)) for s in svc.list_mcp_servers(db)]


@router.post("/admin/mcp/servers", response_model=McpServerOut)
def create_server(
    payload: McpServerCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    server = svc.create_mcp_server(
        db, name=payload.name, transport=payload.transport,
        command=payload.command, args=payload.args, url=payload.url,
        headers=payload.headers, env=payload.env, enabled=payload.enabled, actor=admin,
    )
    admin_service._audit(
        db, actor=admin, action="create_mcp_server", target_type="mcp_server",
        target_id=str(server.id),
        detail={"name": server.name, "transport": server.transport, "enabled": server.enabled},
    )
    return McpServerOut(**svc.to_out(server))


@router.get("/admin/mcp/servers/{server_id}", response_model=McpServerOut)
def get_server(
    server_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return McpServerOut(**svc.to_out(svc.get_mcp_server(db, server_id=server_id)))


@router.put("/admin/mcp/servers/{server_id}", response_model=McpServerOut)
def update_server(
    server_id: str,
    payload: McpServerUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    fields = payload.model_dump(exclude_unset=True)
    server = svc.update_mcp_server(
        db, server_id=server_id, actor=admin,
        name=fields.get("name"), transport=fields.get("transport"),
        command=fields.get("command"), args=fields.get("args"), url=fields.get("url"),
        headers=fields.get("headers"), env=fields.get("env"),
        enabled=fields.get("enabled"),
    )
    admin_service._audit(
        db, actor=admin, action="update_mcp_server", target_type="mcp_server",
        target_id=str(server.id),
        detail={"name": server.name, "transport": server.transport, "enabled": server.enabled},
    )
    return McpServerOut(**svc.to_out(server))


@router.delete("/admin/mcp/servers/{server_id}")
def delete_server(
    server_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    svc.delete_mcp_server(db, server_id=server_id)
    admin_service._audit(
        db, actor=admin, action="delete_mcp_server", target_type="mcp_server",
        target_id=server_id, detail={},
    )
    return {"ok": True}


# ── 全局开关 ──

@router.get("/admin/mcp/enabled", response_model=McpGlobalEnabled)
def get_enabled(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return McpGlobalEnabled(enabled=svc.get_mcp_enabled(db))


@router.put("/admin/mcp/enabled", response_model=McpGlobalEnabled)
def set_enabled(
    payload: McpGlobalEnabled,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    svc.set_mcp_enabled(db, enabled=payload.enabled, actor=admin)
    admin_service._audit(
        db, actor=admin, action="set_mcp_global_enabled",
        target_type="system_setting", target_id="mcp_global_enabled",
        detail={"enabled": payload.enabled},
    )
    return McpGlobalEnabled(enabled=payload.enabled)


# ── 测试连接 ──

@router.post("/admin/mcp/servers/{server_id}/test", response_model=McpTestResult)
def test_server(
    server_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """测试单个 server 连通性（拉工具列表）。失败返回 ok=False + error，不抛 500。"""
    return svc.test_mcp_server(db, server_id=server_id)
