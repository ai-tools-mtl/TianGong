"""用户长期记忆管理路由。"""
import uuid as _uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models.user_memory import UserMemory
from app.schemas.memory import MemoryCreate, MemoryOut, MemoryUpdate
from app.services import memory_service

router = APIRouter(prefix="/memories", tags=["memories"])


def _to_out(mem: UserMemory) -> MemoryOut:
    """UserMemory ORM → MemoryOut（UUID/datetime 显式转 str）。

    与 skills.py 的 _to_out 一致：不依赖 from_attributes 自动转换，
    显式 isoformat()/str() 更稳——Pydantic 先校验后序列化，
    UUID→str / None→str（SQLite 不执行 PG 的 server_default）需在此兜住。
    """
    return MemoryOut(
        id=str(mem.id),
        content=mem.content,
        source=mem.source,
        created_at=mem.created_at.isoformat() if mem.created_at else "",
        updated_at=mem.updated_at.isoformat() if mem.updated_at else "",
    )


@router.get("", response_model=list[MemoryOut])
def list_memories(
    source: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户的所有记忆，可选 source 筛选。"""
    memories = memory_service.list_memories(
        db, user_id=current_user.id, source=source
    )
    return [_to_out(m) for m in memories]


@router.post("", response_model=MemoryOut)
def create_memory(
    payload: MemoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手动新增一条记忆。"""
    mem = memory_service.create_memory(
        db, user_id=current_user.id, content=payload.content, source=payload.source
    )
    db.commit()
    return _to_out(mem)


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改一条记忆。"""
    mem = memory_service.update_memory(
        db, memory_id=_uuid.UUID(memory_id), user_id=current_user.id, content=payload.content
    )
    db.commit()
    return _to_out(mem)


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除一条记忆。"""
    memory_service.delete_memory(
        db, memory_id=_uuid.UUID(memory_id), user_id=current_user.id
    )
    db.commit()
    return {"ok": True}
