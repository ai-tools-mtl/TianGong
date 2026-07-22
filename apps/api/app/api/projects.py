from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.deps import get_current_user
from app.models import Project, Section, User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import archive_service, project_service, tag_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_out(p: Project, tags: list[str] | None = None) -> ProjectOut:
    return ProjectOut(
        id=str(p.id), title=p.title, stage=p.stage, status=p.status,
        progress_pct=p.progress_pct, metadata=p.metadata_,
        archived_at=p.archived_at,
        tags=tags if tags is not None else [],
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
def list_all(
    status: str | None = None,
    q: str | None = None,
    tag_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    projects = project_service.list_projects(
        db, user=current_user, status=status, q=q, tag_id=tag_id,
    )
    from app.services.tag_service import list_tag_ids_for_projects
    tag_map = list_tag_ids_for_projects(db, project_ids=[p.id for p in projects])
    return [_to_out(p, tags=tag_map.get(p.id, [])) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_one(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.get_project(db, user=current_user, project_id=project_id)
    tag_ids = [str(t.id) for t in tag_service.list_tags_for_project(db, user=current_user, project_id=project_id)]
    return _to_out(p, tags=tag_ids)


@router.patch("/{project_id}", response_model=ProjectOut)
def update(project_id: str, payload: ProjectUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.update_project(
        db, user=current_user, project_id=project_id,
        title=payload.title, metadata=payload.metadata,
    )
    tag_ids = [str(t.id) for t in tag_service.list_tags_for_project(db, user=current_user, project_id=project_id)]
    return _to_out(p, tags=tag_ids)


@router.delete("/{project_id}", status_code=204)
def delete(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project_service.delete_project(db, user=current_user, project_id=project_id)
    return None


@router.post("/{project_id}/tags/{tag_id}")
def attach_tag(project_id: str, tag_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tag_service.attach_tag(db, user=current_user, project_id=project_id, tag_id=tag_id)
    tags = tag_service.list_tags_for_project(db, user=current_user, project_id=project_id)
    return [{"id": str(t.id), "name": t.name} for t in tags]


@router.delete("/{project_id}/tags/{tag_id}")
def detach_tag(project_id: str, tag_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tag_service.detach_tag(db, user=current_user, project_id=project_id, tag_id=tag_id)
    tags = tag_service.list_tags_for_project(db, user=current_user, project_id=project_id)
    return [{"id": str(t.id), "name": t.name} for t in tags]


@router.post("/{project_id}/archive")
def archive(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 归属校验：非本人项目返回 404（防探测，与其他端点一致）
    project = project_service.get_project(db, user=current_user, project_id=project_id)

    # 前置校验：至少一个非空 confirmed 章节（防空项目造垃圾 chunk，spec §6.2）
    has_confirmed = db.scalar(
        select(Section).where(
            (Section.project_id == project.id)
            & (Section.status == "confirmed")
            & (Section.content.is_not(None))
        ).limit(1)
    )
    if has_confirmed is None:
        raise ValidationError("内容不足，无法归档（需至少一个已确认的非空章节）")

    # archive_service.archive 内部二次校验归属并调 rag/archiver（幂等：先删旧 chunk 再重生）
    return archive_service.archive(db, user_id=current_user.id, project_id=project_id)
