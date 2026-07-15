from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.tag import TagCreate, TagMerge, TagOut, TagUpdate
from app.services import tag_service

router = APIRouter(prefix="/tags", tags=["tags"])


def _to_out(t, project_count: int | None = None) -> TagOut:
    return TagOut(
        id=str(t.id),
        name=t.name,
        project_count=project_count if project_count is not None else getattr(t, "project_count", 0),
    )


@router.get("", response_model=list[TagOut])
def list_all(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tags = tag_service.list_tags(db, user=current_user)
    return [_to_out(t) for t in tags]


@router.post("", response_model=TagOut, status_code=201)
def create(payload: TagCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = tag_service.create_tag(db, user=current_user, name=payload.name)
    return _to_out(t, project_count=0)


@router.patch("/{tag_id}", response_model=TagOut)
def rename(tag_id: str, payload: TagUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = tag_service.rename_tag(db, user=current_user, tag_id=tag_id, name=payload.name)
    return _to_out(t)


@router.post("/merge", response_model=TagOut)
def merge(payload: TagMerge, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = tag_service.merge_tags(
        db, user=current_user, source_id=payload.source_id, target_id=payload.target_id,
    )
    return _to_out(t)


@router.delete("/{tag_id}", status_code=204)
def delete(tag_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tag_service.delete_tag(db, user=current_user, tag_id=tag_id)
    return None
