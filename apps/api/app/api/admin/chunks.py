"""G4 分块可视化干预端点（spec §5.4）。"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import require_admin
from app.models import User
from app.services.knowledge_service import list_chunks_by_file, update_chunk

router = APIRouter(tags=["admin"])  # 空 prefix：项目约定（路径字面量写装饰器）


def _chunk_out(chunk) -> dict:
    return {
        "id": str(chunk.id),
        "content": chunk.content,
        "edited_text": chunk.edited_text,
        "keywords": chunk.keywords or [],
        "questions": chunk.questions or [],
        "weight": chunk.weight if chunk.weight is not None else 1.0,
        "locked": bool(chunk.locked),
        "chunk_index": chunk.chunk_index,
        "source_section_key": chunk.source_section_key,
    }


@router.get("/admin/knowledge/files/{file_id}/chunks")
def list_chunks(
    file_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    chunks = list_chunks_by_file(db, file_id=file_id)
    return [_chunk_out(c) for c in chunks]


class ChunkUpdateRequest(BaseModel):
    keywords: list[str] | None = None
    questions: list[str] | None = None
    weight: float | None = None
    edited_text: str | None = None
    locked: bool | None = None
    force_unlock: bool = False


@router.patch("/admin/knowledge/chunks/{chunk_id}")
def patch_chunk(
    chunk_id: uuid.UUID,
    payload: ChunkUpdateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        chunk = update_chunk(
            db, chunk_id=chunk_id, payload=payload.model_dump(exclude_none=True),
            force_unlock=payload.force_unlock,
        )
    except PermissionError:
        raise HTTPException(409, "chunk locked, use force_unlock to override")
    except ValueError:
        raise HTTPException(404, "chunk not found")
    return _chunk_out(chunk)
