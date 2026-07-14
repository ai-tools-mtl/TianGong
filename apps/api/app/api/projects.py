from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import Project, User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=str(p.id), title=p.title, stage=p.stage, status=p.status,
        progress_pct=p.progress_pct, metadata=p.metadata_,
        created_at=p.created_at, updated_at=p.updated_at,
    )


@router.post("", response_model=ProjectOut, status_code=201)
def create(payload: ProjectCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.create_project(
        db, user=current_user, title=payload.title,
        template_id=payload.template_id, metadata=payload.metadata,
    )
    return _to_out(p)


@router.get("", response_model=list[ProjectOut])
def list_all(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = project_service.list_projects(db, user=current_user)
    return [_to_out(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_one(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.get_project(db, user=current_user, project_id=project_id)
    return _to_out(p)


@router.patch("/{project_id}", response_model=ProjectOut)
def update(project_id: str, payload: ProjectUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.update_project(
        db, user=current_user, project_id=project_id,
        title=payload.title, metadata=payload.metadata,
    )
    return _to_out(p)


@router.delete("/{project_id}", status_code=204)
def delete(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project_service.delete_project(db, user=current_user, project_id=project_id)
    return None
