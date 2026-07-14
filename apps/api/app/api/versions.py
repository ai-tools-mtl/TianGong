from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.version import VersionCreate, VersionOut
from app.services import section_service, version_service

router = APIRouter(tags=["versions"])


def _to_out(v) -> VersionOut:
    return VersionOut(
        id=str(v.id), section_id=str(v.section_id), content=v.content,
        summary=v.summary, created_by=v.created_by, note=v.note,
        created_at=v.created_at,
    )


@router.get("/sections/{section_id}/versions", response_model=list[VersionOut])
def list_versions(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    versions = version_service.list_versions(db, section=section)
    return [_to_out(v) for v in versions]


@router.post("/sections/{section_id}/versions", response_model=VersionOut, status_code=201)
def create_version(
    section_id: str,
    payload: VersionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    v = version_service.create_version(db, section=section, note=payload.note)
    return _to_out(v)


@router.post("/sections/{section_id}/versions/{version_id}/rollback")
def rollback(
    section_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    updated = version_service.rollback_to_version(db, section=section, version_id=version_id)
    return {"message": "已回滚", "section_id": str(updated.id)}
