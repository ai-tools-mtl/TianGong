from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.section import SectionOut, SectionUpdate
from app.services import section_service

router = APIRouter(tags=["sections"])


def _to_out(s) -> SectionOut:
    return SectionOut(
        id=str(s.id), project_id=str(s.project_id), order=s.order, key=s.key,
        title=s.title, content=s.content, summary=s.summary, status=s.status,
        created_at=s.created_at, updated_at=s.updated_at,
    )


@router.get("/projects/{project_id}/sections", response_model=list[SectionOut])
def list_sections(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sections = section_service.list_sections(
        db, user_id=current_user.id, project_id=project_id
    )
    return [_to_out(s) for s in sections]


@router.get("/sections/{section_id}", response_model=SectionOut)
def get_section(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    return _to_out(s)


@router.patch("/sections/{section_id}", response_model=SectionOut)
def update_section(
    section_id: str,
    payload: SectionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = section_service.update_section(
        db, user_id=current_user.id, section_id=section_id,
        content=payload.content, status=payload.status,
    )
    return _to_out(s)
